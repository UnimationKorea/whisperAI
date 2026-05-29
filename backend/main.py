import os
import sys
import logging

# ⚠️ Python 3.12+ 대응: 일부 라이브러리(transformers, whisperx 등)가 내부적으로 의존하는 pkg_resources 모듈 결손 우회
try:
  import pkg_resources
except ImportError:
  class DummyDistribution:
    version = "99.9.9"
    location = ""

  class DummyVersion:
    def __init__(self, v):
      self.v = v
    def __ge__(self, other): return True
    def __gt__(self, other): return True
    def __le__(self, other): return True
    def __lt__(self, other): return True
    def __eq__(self, other): return True

  class DummyPkgResources:
    def get_distribution(self, name):
      return DummyDistribution()
    def parse_version(self, version):
      return DummyVersion(version)

  sys.modules["pkg_resources"] = DummyPkgResources()
# ==========================================pkg_resources 모듈 결손 우회

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# ⚠️ whisperx, torch는 여기서 import하지 않습니다.
# Cloud Run에서 이 모듈들의 import만으로 30~60초가 소요되어
# uvicorn 포트 바인딩 전에 startup probe 타임아웃이 발생합니다.
# → startup_event 백그라운드 스레드에서 lazy import합니다.

# 라우터 및 모델 관리 함수 가져오기
# (evaluate.py도 whisperx를 lazy import하도록 수정됨)
# from api.evaluate import router as evaluate_router, get_align_model
from api.evaluate import router as evaluate_router

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

  # ── 모델 상태 초기화 (로딩은 startup_event에서 백그라운드로 수행) ──
  # Cloud Run은 컨테이너가 PORT에 리스닝해야 startup probe를 통과합니다.
  # 모듈 레벨에서 동기적으로 모델을 로드하면 uvicorn이 포트에 바인딩하기 전에
  # 타임아웃이 발생하므로, 모델 로딩을 startup_event 백그라운드 스레드로 이동합니다.
  app.state.model = None
  app.state.device = DEVICE
  app.state.model_ready = False
  app.state.warmup_error = None

  # 라우터 등록
  app.include_router(evaluate_router)

  @app.on_event("startup")
  async def startup_event():
    """
    서버 시작 시 모델들을 백그라운드 스레드에서 비동기로 로드합니다.
    uvicorn이 즉시 포트에 바인딩하여 Cloud Run 헬스체크를 통과할 수 있도록 합니다.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    def load_all_models():
      logger.info("🔥 [Warm-up] 백그라운드 모델 메모리 로딩 시작...")
      try:
        # GCE 등 직접 구동 환경 대응: 필수 NLTK 데이터 자동 다운로드
        import nltk
        logger.info("⏳ [Warm-up] NLTK 데이터 확인 및 다운로드 중...")
        nltk.download("averaged_perceptron_tagger", quiet=True)
        nltk.download("averaged_perceptron_tagger_eng", quiet=True)
        nltk.download("cmudict", quiet=True)
        nltk.download("punkt", quiet=True)
        logger.info("✅ [Warm-up] NLTK 데이터 확인 완료")

        # ★ 여기서 whisperx를 최초 import합니다 (torch도 함께 로딩됨)
        import whisperx

        # 1) WhisperX 메인 모델 로드
        logger.info(f"⏳ WhisperX 모델 로딩 중... (Size: {MODEL_SIZE}, Device: {DEVICE})")
        app.state.model = whisperx.load_model(MODEL_SIZE, DEVICE, compute_type=COMPUTE_TYPE)
        logger.info("✅ WhisperX 모델 로딩 완료")

        # 2) 모든 모델 로딩 완료 → 준비 상태로 전환
        # (언어별 정렬 모델 및 평가기는 첫 요청 시 지연 로딩됩니다.)
        app.state.model_ready = True
        logger.info("✅ [Warm-up] 메인 WhisperX 모델 로딩 완료 및 즉시 사용 가능")
      except Exception as e:
        import traceback
        error_msg = f"{e}\n{traceback.format_exc()}"
        logger.error(f"❌ [Warm-up] 모델 로딩 실패: {error_msg}")
        app.state.warmup_error = error_msg

    # 백그라운드 스레드풀에서 모델 로딩을 실행하여 메인 스레드(FastAPI 기동 및 포트 리스닝)의 블로킹을 막습니다.
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    loop.run_in_executor(executor, load_all_models)
    logger.info("🚀 [Startup] 백그라운드 Warm-up 태스크가 시작되었습니다. 즉시 포트 리스닝을 개시합니다.")

  @app.get("/health")
  async def health_check():
    """모델 로딩 상태를 포함한 헬스체크 엔드포인트"""
    return {
      "status": "healthy" if app.state.model_ready else ("error" if app.state.warmup_error else "warming_up"),
      "model": MODEL_SIZE,
      "device": DEVICE,
      "compute_type": COMPUTE_TYPE,
      "engine": "whisperx",
      "model_ready": app.state.model_ready,
      "warmup_error": app.state.warmup_error
    }

  return app

app = create_app()

if __name__ == "__main__":
  import uvicorn
  uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
