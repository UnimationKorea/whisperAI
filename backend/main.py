import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from faster_whisper import WhisperModel

# 라우터 가져오기
from api.evaluate import router as evaluate_router

# .env 로드
load_dotenv()

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경 변수
PORT = int(os.getenv("PORT", "8001"))
MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")
DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

def create_app():
  app = FastAPI(title="Whisper STT Backend")

  # CORS 설정
  app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
  )

  # Whisper 모델 로드 및 공유 설정 (app.state)
  logger.info(f"⏳ Whisper 모델 로딩 중... (Size: {MODEL_SIZE}, Device: {DEVICE})")
  app.state.model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
  logger.info("✅ Whisper 모델 로딩 완료")

  # 라우터 등록
  app.include_router(evaluate_router)

  @app.get("/health")
  async def health_check():
    return {
      "status": "healthy",
      "model": MODEL_SIZE,
      "device": DEVICE,
      "compute_type": COMPUTE_TYPE
    }

  return app

app = create_app()

if __name__ == "__main__":
  import uvicorn
  uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
