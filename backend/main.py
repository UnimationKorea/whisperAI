import os
import asyncio
import json
import logging
import time
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from faster_whisper import WhisperModel

# .env 로드
load_dotenv()

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경 변수
PORT = int(os.getenv("PORT", "8001"))
MODEL_SIZE = os.getenv("WHISPER_MODEL", "tiny")
DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

# Whisper 모델 로드 (서버 시작 시 한 번만)
logger.info(f"⏳ Whisper 모델 로딩 중... (Size: {MODEL_SIZE}, Device: {DEVICE})")
model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
logger.info("✅ Whisper 모델 로딩 완료")

app = FastAPI(title="Whisper STT Backend")

app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
  allow_credentials=True,
  allow_methods=["*"],
  allow_headers=["*"],
)

@app.get("/health")
async def health_check():
  return {
    "status": "healthy",
    "model": MODEL_SIZE,
    "device": DEVICE,
    "compute_type": COMPUTE_TYPE
  }

@app.websocket("/ws/stt")
async def websocket_endpoint(websocket: WebSocket):
  await websocket.accept()
  logger.info("✅ WebSocket 연결됨")
  
  audio_buffer = bytearray()
  
  try:
    while True:
      # 클라이언트로부터 데이터 수신 (바이너리 오디오 또는 JSON 설정)
      message = await websocket.receive()
      
      if "bytes" in message:
        # 오디오 데이터 수신
        data = message["bytes"]
        audio_buffer.extend(data)
        
        # 일정량 이상 쌓이면 처리 (예: 약 1초 분량, 16kHz 16bit mono 기준 32000 bytes)
        # 테스트를 위해 임시로 일정 크기마다 인식 시도
        if len(audio_buffer) > 32000 * 2:  # 약 2초
          # 오디오 처리 로직 (실제 서비스에서는 VAD 등을 사용하는 것이 좋음)
          # 여기서는 전체 버퍼를 numpy로 변환하여 인식
          audio_np = np.frombuffer(audio_buffer, dtype=np.int16).astype(np.float32) / 32768.0
          
          start_time = time.time()
          segments, info = model.transcribe(audio_np, beam_size=5, language="ko")
          
          text = ""
          for segment in segments:
            text += segment.text
          
          if text.strip():
            logger.info(f"🗣️ 인식 결과: {text} (소요시간: {time.time() - start_time:.2f}s)")
            await websocket.send_json({
              "type": "transcript",
              "content": text,
              "language": info.language,
              "probability": info.language_probability
            })
          
          # 버퍼 비우기 (단순 구현: 인식 후 리셋)
          audio_buffer.clear()
              
      elif "text" in message:
        # JSON 메시지 처리 (예: 설정 변경 등)
        try:
          msg_json = json.loads(message["text"])
          if msg_json.get("type") == "config":
            logger.info(f"⚙️ 설정 수신: {msg_json}")
        except:
          pass
                  
  except WebSocketDisconnect:
    logger.info("📴 WebSocket 연결 해제")
  except Exception as e:
    logger.error(f"❌ WebSocket 핸들러 오류: {e}")
    try:
      await websocket.send_json({"type": "error", "content": str(e)})
    except Exception:
      pass
  finally:
    audio_buffer.clear()
    logger.info("🔌 WebSocket 핸들러 종료")

if __name__ == "__main__":
  import uvicorn
  uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
