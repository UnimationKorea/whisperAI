import os
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
  
  # 1. Phonetic Hint 생성 (유사 발음 유도)
  # 비슷한 발음의 단어들을 프롬프트에 나열하여 모델의 '강제 보정'을 방지합니다.
  # 모델이 '사전에 없는 단어'라도 소리에 충실하게 인식하도록 힌트를 제공합니다.
  phonetic_hints = {
    "rabbit": "rabbit, labbit, habit, rare",
    "dog": "dog, dot, dock, log",
    "cat": "cat, cap, cut, sat",
    "caw": "caw, how, claw, saw, raw",
  }
  hint = phonetic_hints.get(expected_word.lower(), expected_word)
  
  # WhisperX 내부의 Faster-Whisper 모델을 직접 사용하여 정밀 전사
  segments_gen, info = model.model.transcribe(
    audio_np, 
    # beam_size=10, # 빔 사이즈를 높여 더 많은 후보 탐색
    language=language,
    # initial_prompt=f"Pronounce the word: {expected_word}",
    # initial_prompt=f"Focus on these sounds: {hint}. The user is pronouncing: {expected_word}",
    initial_prompt=f"The user is pronouncing: {hint}", # 강력한 힌트 제공
    temperature=0,
    vad_filter=True,
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
  
  # 2. Alignment (정렬)
  try:
    language_code = result["language"]
    model_a, metadata = get_align_model(language_code, device)
    
    # 정렬 실행 (단어 단위 타임스탬프 획득)
    result_aligned = whisperx.align(
      result["segments"], 
      model_a, 
      metadata, 
      audio_np, 
      device, 
      return_char_alignments=False
    )
    
    # 3. 단어 리스트 추출 (제안하신 방식 적용)
    word_list = []
    for segment in result_aligned["segments"]:
      if "words" in segment:
        for w in segment["words"]:
          # WhisperX는 종종 단어가 인식되지 않으면 'word' 키가 없을 수 있음
          if "word" in w:
            word_list.append(w["word"].lower().strip())
    
    # 전체 문장 생성 (비교용)
    actual_text = " ".join(word_list).replace(".", "").replace(",", "")
    
    # 4. 발음 평가 서비스 호출 (단어 리스트 전달)
    evaluation = evaluate_pronunciation(expected_word, actual_text, word_list, language)

    return {
      "recognized_text": actual_text,
      "word_list": word_list,
      "score": evaluation["score"],
      "feedback": evaluation["feedback"],
      "language": language_code,
      "word_segments": result_aligned.get("word_segments", []) # 추후 정밀 분석용
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
    # 1. 파일 데이터 읽기
    file_bytes = await file.read()
    
    # 2. Raw PCM (Int16) -> Numpy (Float32) 변환
    audio_np = np.frombuffer(file_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    # 3. 공통 함수 호출
    result = await run_evaluation_process(model, device, audio_np, expected, language)

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