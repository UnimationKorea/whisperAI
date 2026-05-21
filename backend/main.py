import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
# from faster_whisper import WhisperModel
import whisperx
import torch

# 라우터 및 모델 관리 함수 가져오기
from api.evaluate import router as evaluate_router, get_align_model

# .env 로드
load_dotenv()

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경 변수
PORT = int(os.getenv("PORT", "8001"))
MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")
DEVICE = os.getenv("WHISPER_DEVICE", "cpu") # GPU 사용 시 "cuda"
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

def create_app():
  app = FastAPI(title="WhisperX STT Backend")

  # CORS 설정
  app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
  )

  # Whisper 모델 로드 및 공유 설정 (app.state)
  # logger.info(f"⏳ Whisper 모델 로딩 중... (Size: {MODEL_SIZE}, Device: {DEVICE})")
  # app.state.model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
  # logger.info("✅ Whisper 모델 로딩 완료")
  # WhisperX 모델 로드
  logger.info(f"⏳ WhisperX 모델 로딩 중... (Size: {MODEL_SIZE}, Device: {DEVICE})")
  # whisperx.load_model은 내부적으로 faster-whisper를 사용합니다.
  app.state.model = whisperx.load_model(MODEL_SIZE, DEVICE, compute_type=COMPUTE_TYPE)
  app.state.device = DEVICE
  logger.info("✅ WhisperX 모델 로딩 완료")

  # 라우터 등록
  app.include_router(evaluate_router)

  @app.on_event("startup")
  async def startup_event():
    """
    서버 시작 시 모델들을 메모리에 미리 로드하여 첫 요청 지연을 방지합니다.
    """
    logger.info("🔥 [Warm-up] 정렬 모델 메모리 로딩 시작...")
    try:
      # 언어별 정렬 모델을 미리 로드
      get_align_model("en", DEVICE)
      get_align_model("zh", DEVICE)
      get_align_model("ja", DEVICE)
      logger.info("✅ [Warm-up] 모든 모델 로딩 완료 및 즉시 사용 가능")
    except Exception as e:
      logger.error(f"❌ [Warm-up] 모델 로딩 실패: {e}")

  @app.get("/health")
  async def health_check():
    return {
      "status": "healthy",
      "model": MODEL_SIZE,
      "device": DEVICE,
      "compute_type": COMPUTE_TYPE,
      "engine": "whisperx"
    }

  return app

app = create_app()

if __name__ == "__main__":
  import uvicorn
  uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
