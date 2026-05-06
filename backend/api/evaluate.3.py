import os
import re
import tempfile
import time
import json
import logging
import numpy as np
import whisperx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Request
from services.evaluator import evaluate_pronunciation

router = APIRouter()
logger = logging.getLogger(__name__)

# Alignment 모델 캐시 (메모리 절약 및 속도 향상)
ALIGN_MODELS = {}

def get_align_model(language_code, device):
  key = f"{language_code}_{device}"
  if key not in ALIGN_MODELS:
    logger.info(f"⏳ Alignment 모델 로딩 중... ({language_code})")
    model_a, metadata = whisperx.load_align_model(language_code=language_code, device=device)
    ALIGN_MODELS[key] = (model_a, metadata)
    logger.info(f"✅ Alignment 모델 로딩 완료 ({language_code})")
  return ALIGN_MODELS[key]

# --------------------------------------------------
# 공통 처리 함수: WhisperX 인식 + Alignment + 발음 평가
# --------------------------------------------------
async def run_evaluation_process(model, device, audio_np, expected_word, language="en"):
  """
  model: WhisperX 모델 객체
  device: 실행 장치 (cpu/cuda)
  audio_np: 처리할 오디오 데이터 (Numpy Float32)
  expected_word: 사용자가 읽어야 할 정답 단어
  """

  # 1. WhisperX 전사 (Transcription)
  # WhisperX의 transcribe는 faster-whisper와 결과 형식이 다를 수 있으므로 주의
  # result = model.transcribe(audio_np, language="en")
  
  # 1. WhisperX 전사 (Transcription)
  # 중복 인식(Repetition) 방지를 위해 페널티 파라미터를 추가하고 VAD를 강화합니다.
  segments_gen, info = model.model.transcribe(
    audio_np, 
    # beam_size=10, # 빔 사이즈를 높여 더 많은 후보 탐색
    language=language,
    initial_prompt=f"The word is: {expected_word}", # 마침표를 찍어 문장이 끝남을 명시
    temperature=0,
    vad_filter=True,
    # VAD를 너무 엄격하게 하면 단어의 첫/끝 음소가 잘릴 수 있으므로 약간 완화
    vad_parameters=dict(min_silence_duration_ms=700, speech_pad_ms=300),
    repetition_penalty=1.2,   # 반복 단어에 페널티 부여
    no_repeat_ngram_size=1,    # 동일한 n-gram 반복 방지
    word_timestamps=True # 단어별 타임스탬프 활성화
  )
  
  # 제너레이터를 리스트로 변환 (WhisperX Alignment에 필요)
  segments = []
  for s in segments_gen:
    segments.append({
      "start": s.start,
      "end": s.end,
      "text": s.text
    })

  result = {
    "segments": segments,
    "language": info.language
  }
  
  # 2. Alignment (정렬) - 실제 인식된 텍스트 기반
  try:
    language_code = result["language"]
    model_a, metadata = get_align_model(language_code, device)
    
    # 실제 전사된 결과물을 기반으로 정렬을 수행하여 정확한 타임스탬프와 정보를 얻습니다.
    # (강제 정렬 대신 실제 발음 데이터 보존)
    result_aligned = whisperx.align(
      result["segments"], 
      model_a, 
      metadata, 
      audio_np, 
      device, 
      return_char_alignments=True
    )
    
    # 피드백용 단어 리스트 추출
    word_list_for_feedback = []
    for segment in result_aligned["segments"]:
      if "words" in segment:
        for w in segment["words"]:
          if "word" in w:
            word_list_for_feedback.append(w["word"].lower().strip())
    
    # 3. 실제 전사 텍스트 결합
    # actual_text = " ".join([s["text"] for s in result["segments"]]).strip().lower()
    # 3. 실제 전사 텍스트 결합 및 중복 제거 (Deduplication) + 특수문자 제거
    # 인식 결과에서 연속적으로 중복된 단어가 나타날 경우 (예: "tiger tiger") 하나만 남깁니다.
    raw_actual_text = " ".join([s["text"] for s in result["segments"]]).strip().lower()
    words = raw_actual_text.split()
    deduplicated_words = []
    for i, w in enumerate(words):
      if i == 0 or w != words[i-1]:
        deduplicated_words.append(w)
    
    # actual_text = " ".join(deduplicated_words)
    # 최종 결과에서 마침표, 느낌표 등 특수문자 완전 제거
    actual_text = re.sub(r'[^\w\s]', '', " ".join(deduplicated_words)).strip()
    
    # 4. 발음 평가 서비스 호출
    # 철자 수준의 상세 분석을 위해 aligned_segments를 추가로 전달합니다.
    evaluation = evaluate_pronunciation(
      expected_word, 
      actual_text, 
      word_list=word_list_for_feedback, 
      language=language,
      aligned_segments=result_aligned.get("segments")
    )

    return {
      "expected": expected_word,
      "recognized_text": actual_text,
      "score": evaluation["score"],
      "feedback": evaluation["feedback"],
      "language": language_code,
      "word_segments": result_aligned.get("word_segments", []),
      "char_segments": result_aligned.get("char_segments", []) # 철자별 상세 정보 추가
    }
    
  except Exception as e:
    logger.error(f"❌ Alignment 실패: {e}")
    # Alignment 실패 시 기본 전사 결과라도 반환
    recognized_text = "".join([s["text"] for s in result["segments"]]).strip().lower()
    evaluation = evaluate_pronunciation(expected_word, recognized_text, language=language)
    return {
      "recognized_text": recognized_text,
      "score": evaluation["score"],
      "feedback": evaluation["feedback"],
      "language": result["language"],
      "error": "alignment_failed"
    }


# --------------------------------------------------
# 1. 오디오 파일 업로드 평가 (POST)
# --------------------------------------------------
@router.post("/evaluate")
async def evaluate(
  request: Request, 
  file: UploadFile = File(...), 
  expected: str = Form(...),
  language: str = Form("en")
):
  model = request.app.state.model
  device = getattr(request.app.state, "device", "cpu")
  
  try:
    # 1. 파일 데이터 읽기 및 임시 파일 저장
    # (Header가 포함된 파일을 Raw PCM으로 읽으면 잡음이 발생하므로 whisperx.load_audio 사용)

    # 2. Raw PCM (Int16) -> Numpy (Float32) 변환
    # audio_np = np.frombuffer(file_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    
    # with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:

    file_bytes = await file.read()
    filename = file.filename.lower()

    if filename.endswith(".raw") or filename.endswith(".pcm"):
      # 2-1. Raw PCM 처리 (FFmpeg 불필요, 로컬 실행용)
      # 프론트엔드에서 16kHz, Mono, Int16으로 보낸다고 가정합니다.
      audio_np = np.frombuffer(file_bytes, dtype=np.int16).astype(np.float32) / 32768.0
      result = await run_evaluation_process(model, device, audio_np, expected, language)
    else:
      # 2-2. 표준 오디오 형식 처리 (FFmpeg 필요, Cloud Run/Docker용)
      with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp_file:
        tmp_file.write(file_bytes)
        tmp_path = tmp_file.name

      try:
      # 2. 오디오 로드 (16kHz 리샘플링 및 헤더 자동 제거)
        audio_np = whisperx.load_audio(tmp_path)

      # 3. 공통 함수 호출
        result = await run_evaluation_process(model, device, audio_np, expected, language)
      finally:
      # 임시 파일 삭제
        if os.path.exists(tmp_path):
          os.remove(tmp_path)

    return {
      "expected": expected,
      "recognized_text": result["recognized_text"],
      "score": result["score"],
      "feedback": result["feedback"],
      "language": result["language"],
      "word_segments": result.get("word_segments", [])
    }

  except Exception as e:
    logger.error(f"❌ 평가 도중 오류 발생: {e}")
    return {"error": str(e)}, 500