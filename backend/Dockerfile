# 1. Base image (Python 3.12 Slim 사용)
FROM python:3.12-slim

# 2. 필수 시스템 패키지 설치 및 최적화
# ffmpeg: 오디오 처리, git: whisperx 설치용
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# 3. 작업 디렉토리 설정
WORKDIR /app

# 4. 의존성 설치
# requirements.txt에 whisperx가 포함되어 있으므로 중복 설치를 피합니다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. 모델 및 데이터 미리 다운로드 (빌드 시점에 캐싱하여 런타임 지연 방지)
# 이 과정은 소스 코드 복사(COPY . .) 이전에 실행되어 코드 수정 시에도 다시 받지 않습니다.
RUN python -c "import nltk; nltk.download('averaged_perceptron_tagger'); nltk.download('cmudict'); nltk.download('punkt')" && \
    python -c "from g2p_en import G2p; G2p()" && \
    python -c "from pypinyin import pinyin; pinyin('你好')"

# WhisperX 모델 및 언어별 정렬 모델 (영어, 중국어) 미리 로드
RUN python -c "import whisperx; whisperx.load_model('base', 'cpu', compute_type='int8')" && \
    python -c "import whisperx; whisperx.load_align_model('en', 'cpu'); whisperx.load_align_model('zh', 'cpu')"

# 6. 소스 코드 복사 (수정 잦은 코드는 마지막에 복사하여 빌드 캐시 효율 극대화)
COPY . .

# 7. 환경 변수 설정
ENV PORT=8080 \
    WHISPER_MODEL=base \
    WHISPER_DEVICE=cpu \
    WHISPER_COMPUTE_TYPE=int8

# 8. 앱 실행 (Cloud Run 표준 포트 대응)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
