# backend/Dockerfile
# 1. 미리 빌드된 전용 베이스 이미지 사용 (빌드 시간 90% 단축)
# 주의: 이 이미지가 Artifact Registry에 먼저 존재해야 합니다.
FROM gcr.io/whisperai-494605/whisper-repo/whisper-base:latest

# 2. 작업 디렉토리 설정
WORKDIR /app

# 3. 소스 코드 복사
# 베이스 이미지에 이미 모든 라이브러리가 설치되어 있으므로 코드만 복사하면 됩니다.
COPY . .

# setuptools 추가 설치 (Python 3.12 대응 및 pkg_resources 오류 해결)
RUN pip install --no-cache-dir setuptools

# 4. 환경 변수 설정
ENV PORT=8080 \
    WHISPER_MODEL=base \
    WHISPER_DEVICE=cpu \
    WHISPER_COMPUTE_TYPE=int8 \
    HF_HOME=/root/.cache \
    TORCH_HOME=/root/.cache \
    XDG_CACHE_HOME=/root/.cache

# 5. 앱 실행 (Cloud Run 표준 포트 대응)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
