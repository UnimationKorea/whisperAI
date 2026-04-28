import os
import time
import json
import logging
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Request
from services.evaluator import evaluate_pronunciation

router = APIRouter()
logger = logging.getLogger(__name__)

# --------------------------------------------------
# 공통 처리 함수: Whisper 인식 + 발음 평가
# --------------------------------------------------
async def run_evaluation_process(model, audio_np, expected_word):
  """
  model: Whisper 모델 객체
  audio_np: 처리할 오디오 데이터 (Numpy Float32)
  expected_word: 사용자가 읽어야 할 정답 단어
  """
  # 1. Whisper 인식 실행
  segments, info = model.transcribe(
    audio_np, 
    beam_size=5, 
    language="en",
    initial_prompt=f"Pronounce the word: {expected_word}",
    temperature=0,      # 결정론적 결과 출력
    vad_filter=True     # 목소리 구간만 추출
  )
  
  # 2. 텍스트 결합 및 전처리
  recognized_text = "".join([s.text for s in segments]).strip().lower().replace(".", "").replace(",", "")
  
  # 3. 발음 평가 서비스 호출
  evaluation = evaluate_pronunciation(expected_word, recognized_text)
  
  return {
    "recognized_text": recognized_text,
    "score": evaluation["score"],
    "feedback": evaluation["feedback"],
    "language": info.language
  }


# --------------------------------------------------
# 1. 실시간 WebSocket & 평가
# --------------------------------------------------
@router.websocket("/ws/evaluate")
async def websocket_endpoint(websocket: WebSocket):
  await websocket.accept()
  logger.info("✅ WebSocket 연결됨")
  
  # app.state에서 Whisper 모델 가져오기
  model = websocket.app.state.model
  audio_buffer = bytearray()
  target_word = ""
  
  try:
    while True:
      message = await websocket.receive()
      
      if "bytes" in message:
        audio_buffer.extend(message["bytes"])
        
        # 약 2초 분량이 쌓이면 처리
        if len(audio_buffer) > 32000 * 2:
          audio_np = np.frombuffer(audio_buffer, dtype=np.int16).astype(np.float32) / 32768.0
          
          # 공통 함수 호출
          result = await run_evaluation_process(model, audio_np, target_word)
          
          if result["recognized_text"]:
            await websocket.send_json({
              "type": "result",
              "content": result["recognized_text"],
              "target": target_word,
              "score": result["score"],
              "feedback": result["feedback"],
              "language": result["language"]
            })
          
          audio_buffer.clear()
            
      elif "text" in message:
        try:
          msg_json = json.loads(message["text"])
          if msg_json.get("type") == "config":
            target_word = msg_json.get("targetWord", "")
            logger.info(f"⚙️ 설정 수신 - 제시어: {target_word}")
        except:
          pass
          
  except WebSocketDisconnect:
    logger.info("📴 WebSocket 연결 해제")
  finally:
    audio_buffer.clear()


# --------------------------------------------------
# 2. 오디오 파일 업로드 평가 (POST)
# --------------------------------------------------
@router.post("/evaluate")
async def evaluate(request: Request, file: UploadFile = File(...), expected: str = Form(...)):
  model = request.app.state.model
  
  try:
    # 1. 파일 데이터 읽기
    file_bytes = await file.read()
    
    # 2. Raw PCM (Int16) -> Numpy (Float32) 변환
    # 프론트엔드에서 16kHz mono 16bit로 보내고 있음
    audio_np = np.frombuffer(file_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    # 공통 함수 호출
    result = await run_evaluation_process(model, audio_np, expected)

    return {
      "expected": expected,
      "recognized_text": result["recognized_text"],
      "score": result["score"],
      "feedback": result["feedback"],
      "language": result["language"]
    }

  except Exception as e:
    logger.error(f"❌ 평가 도중 오류 발생: {e}")
    return {"error": str(e)}, 500