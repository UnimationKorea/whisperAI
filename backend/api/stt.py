import os
import time
import json
import logging
import tempfile
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Request
from services.evaluator import evaluate_pronunciation

router = APIRouter()
logger = logging.getLogger(__name__)

# --------------------------------------------------
# 1. 실시간 WebSocket STT & 평가
# --------------------------------------------------
@router.websocket("/ws/stt")
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
          
          # Whisper 인식
          segments, info = model.transcribe(
            audio_np, 
            beam_size=5, 
            language="en",
            initial_prompt=target_word
          )
          
          recognized_text = "".join([s.text for s in segments]).strip().lower()
          
          if recognized_text:
            # 발음 평가 서비스 호출
            result = evaluate_pronunciation(target_word, recognized_text)
            
            await websocket.send_json({
              "type": "result",
              "content": recognized_text,
              "target": target_word,
              "score": result["score"],
              "feedback": result["feedback"],
              "language": info.language
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
  
  # 임시 파일 저장
  with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
    tmp.write(await file.read())
    temp_path = tmp.name

  try:
    # Whisper 실행
    segments, info = model.transcribe(
      temp_path,
      language="en",
      beam_size=5,
      initial_prompt=f"The expected word is {expected}."
    )

    actual_text = "".join([s.text for s in segments]).strip()

    # 발음 평가 서비스 호출
    result = evaluate_pronunciation(expected, actual_text)

    return {
      "expected": expected,
      "recognized_text": actual_text,
      "score": result["score"],
      "feedback": result["feedback"],
      "language": info.language
    }

  finally:
    if os.path.exists(temp_path):
      os.remove(temp_path)
