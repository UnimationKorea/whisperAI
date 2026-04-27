# 1. Base image (Python 3.12 Slim 사용)
FROM python:3.12-slim

# 2. 필수 시스템 패키지 설치 (ffmpeg: 오디오 처리, libgomp1: CTranslate2 가속용)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 3. 작업 디렉토리 설정
WORKDIR /app

# 4. 의존성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. 소스 코드 복사
COPY . .

# 6. Whisper 모델 미리 다운로드 (빌드 시점에 캐싱)
# 환경 변수에 따라 달라질 수 있으므로, 기본값(tiny)으로 미리 다운로드합니다.
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('tiny', device='cpu', compute_type='int8')"

# 7. 환경 변수 설정
ENV PORT=8080
ENV WHISPER_MODEL=tiny
ENV WHISPER_DEVICE=cpu
ENV WHISPER_COMPUTE_TYPE=int8

# 8. 실행 명령 (Cloud Run은 PORT 환경 변수를 사용함)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]
