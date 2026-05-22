import os
import re
import tempfile
import time
import json
import logging
import numpy as np
from fastapi import APIRouter, UploadFile, File, Form, Request
from services.evaluator import evaluate_pronunciation
import whisperx

router = APIRouter()
logger = logging.getLogger(__name__)

# 전역 변수로 모델 관리 (메모리 절약 및 재사용)
align_models = {}

def get_align_model(language_code, device):
  if language_code not in align_models:
    logger.info(f"🚀 Loading alignment model for {language_code}...")
    align_models[language_code] = whisperx.load_align_model(language_code=language_code, device=device)
  return align_models[language_code]

async def run_evaluation_process(model, device, audio_np, expected_word, language="en", mode="word", candidates=None):
  """
  Multi-Alignment Scoring: 후보군 중 가장 유사한 발음을 탐색합니다.
  """
  expected_word = expected_word.lower().strip()
  print(f"\n[Evaluation Mode: {mode.upper()}] Target: {expected_word}")
  
  # 후보군이 전달되지 않은 경우 기본값으로 [정답단어] 사용
  if not candidates:
    candidates = [expected_word]
  
  # 오디오 길이 계산 (초 단위)
  duration = audio_np.shape[0] / 16000
  
  # 0. 초기 자유 전사 (언어를 고정하지 않고 자동 감지하여 타 언어 오인식/번역 방지)
  raw_segments_gen, info = model.model.transcribe(
    audio_np, 
    # language=language, # 언어를 고정하면 타 언어 입력 시 번역될 위험이 있음
    temperature=0,
    vad_filter=True
  )
  detected_lang = info.language
  lang_prob = info.language_probability
  initial_raw_text = "".join([s.text for s in raw_segments_gen]).strip().lower()
  
  print(f"\n📢 [Detected Language: {detected_lang} ({lang_prob:.2f})]")
  print(f"📢 [Initial Whisper Transcription: '{initial_raw_text}']")

  # 0-1. 언어 불일치 가드 및 정밀 전사
  # 감지된 언어가 목표 언어와 확연히 다를 경우(특히 한국어) 즉시 차단
  if detected_lang != language and lang_prob > 0.7:
    lang_names = {"ko": "한국어", "en": "영어", "zh": "중국어", "ja": "일본어"}
    target_name = lang_names.get(language, language)
    detected_name = lang_names.get(detected_lang, detected_lang)
    
    print(f"⚠️ Language Mismatch: Detected {detected_name} instead of {target_name}")
    return {
      "language": language,
      "expected": expected_word,
      "recognized_text": initial_raw_text,
      "score": 0,
      # "error": f"{detected_name}로 감지되었습니다. {target_name}로 다시 말씀해 주세요.",
      "error": { "code": "1301", "msg": "Language Mismatch" }, 
      "analysis_data": {
        "initial_raw_text": initial_raw_text,
      }
    }
  else:
    # 언어가 일치하거나 확신도가 낮을 경우, 목표 언어로 고정하여 정밀 전사 재실행
    # 이를 통해 발음이 다소 부정확하더라도 목표 언어 내에서 가장 유사한 텍스트를 얻을 수 있습니다.
    print(f"✨ Refining transcription with fixed language: {language}")
    raw_segments_gen, _ = model.model.transcribe(
      audio_np, 
      language=language,
      temperature=0,
      vad_filter=True
    )
    refined_raw_text = "".join([s.text for s in raw_segments_gen]).strip().lower()
    print(f"📢 [Refined Whisper Transcription: '{refined_raw_text}']")

  # 1. 모든 후보군에 대해 정렬 실행 및 결과 수집
  candidate_results = {}
  
  # 1. 각 후보군에 대해 정렬 실행 및 점수 비교
  try:
    model_a, metadata = get_align_model(language, device)
    
    print(f"🔍 [Multi-Alignment Search: {expected_word}]")
    for cand in candidates:
      # Japanese(ja)의 경우, Wav2Vec2 정렬 모델이 한자(Kanji)를 인식하지 못하므로 히라가나로 변환하여 정렬을 수행합니다.
      align_text = cand
      if language == "ja":
        import pykakasi
        kks = pykakasi.kakasi()
        converted = kks.convert(cand)
        align_text = "".join([item['hira'] for item in converted])
        
      # 후보 단어로 가상 세그먼트 생성
      temp_segments = [{"start": 0, "end": duration, "text": align_text}]
      
      # 정렬 실행
      result_aligned = whisperx.align(
        temp_segments, 
        model_a, 
        metadata, 
        audio_np, 
        device, 
        return_char_alignments=True
      )
      
      # 평균 점수 계산
      total_score = 0
      count = 0
      for segment in result_aligned["segments"]:
        if "words" in segment:
          for w in segment["words"]:
            if "score" in w:
              total_score += w["score"]
              count += 1
      
      avg_score = (total_score / count) if count > 0 else 0
      candidate_results[cand] = {
        "avg_score": avg_score,
        "result": result_aligned
      }
      print(f"  - Candidate '{cand}': {avg_score:.4f}")

    # 2. 발음 평가 서비스 호출 (최종 단어 선택 권한을 평가기에게 위임)
    evaluation = evaluate_pronunciation(
      expected_word, 
      candidates, 
      raw_text=refined_raw_text,
      language=language,
      mode=mode,
      candidate_results=candidate_results,
      audio_np=audio_np,
    )

    actual_text = evaluation["recognized_text"]
    # best_result_aligned = evaluation.get("aligned_result", {})

    print(f"✅ Final Choice: '{actual_text}'\n")

    # word_segments를 aligned_result라는 이름으로 변환하여 analysis_data에 포함합니다.
    # aligned_result_data = best_result_aligned.get("word_segments", []) if best_result_aligned else []
    # analysis_data = {
    #   **evaluation.get("analysis_data", {}),
    #   "word_details": evaluation.get("word_details", []),
    #   "aligned_result": aligned_result_data
    # }

    return {
      "language": language,
      "expected": expected_word,
      "recognized_text": actual_text,
      "initial_raw_text": initial_raw_text,
      "refined_raw_text": refined_raw_text,
      "score": evaluation.get("score", 0),
      # 각 언어별 evaluator가 직접 조립해준 analysis_data를 그대로 반환합니다.
      "analysis_data": evaluation.get("analysis_data", {}),
      "error": evaluation.get("error")
    }
    
  except Exception as e:
    logger.error(f"❌ Alignment 실패: {e}")
    return {
      "language": language,
      "expected": expected_word,
      "recognized_text": "recognition_error",
      "score": 0,
      "analysis_data": {},
      "error": { "code": "500", "msg": str(e) },
    }

# --------------------------------------------------
# 1. 오디오 파일 업로드 평가 (POST)
# --------------------------------------------------
@router.post("/evaluate")
async def evaluate(
  request: Request, 
  file: UploadFile = File(...), 
  expected: str = Form(...),
  language: str = Form("en"),
  mode: str = Form("word"),
  candidates: str = Form(None)   # JSON string
):
  model = request.app.state.model
  device = getattr(request.app.state, "device", "cpu")
  
  # JSON 문자열 파싱
  parsed_candidates = None
  
  try:
    if candidates:
      parsed_candidates = json.loads(candidates)
  except Exception as e:
    logger.warning(f"Failed to parse candidates: {e}")

  try:
    # 1. 파일 데이터 읽기
    file_bytes = await file.read()
    filename = file.filename.lower()

    if filename.endswith(".raw") or filename.endswith(".pcm"):
      # 2-1. Raw PCM 처리 (FFmpeg 불필요, 로컬 실행용)
      audio_np = np.frombuffer(file_bytes, dtype=np.int16).astype(np.float32) / 32768.0
      result = await run_evaluation_process(
        model, device, audio_np, expected, language, mode, 
        candidates=parsed_candidates
      )
    else:
      # 2-2. 표준 오디오 형식 처리 (FFmpeg 필요, Cloud Run/Docker용)
      with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp_file:
        tmp_file.write(file_bytes)
        tmp_path = tmp_file.name

      try:
        audio_np = whisperx.load_audio(tmp_path)
        result = await run_evaluation_process(
          model, device, audio_np, expected, language, mode, 
          candidates=parsed_candidates
        )
      finally:
        if os.path.exists(tmp_path):
          os.remove(tmp_path)

    return {
      "language": result["language"], # 언어
      "expected": expected, # 정답
      "recognized_text": result["recognized_text"], # recognized text
      "initial_raw_text": result.get("initial_raw_text", ""), # 초기 인식 텍스트
      "refined_raw_text": result.get("refined_raw_text", ""), # 정제된 인식 텍스트
      "score": result["score"], # 발음 점수
      # word_details와 aligned_result가 analysis_data 내부에 포함되어 전달되므로 상위 필드에서 제거합니다.
      "analysis_data": result.get("analysis_data", {}), # 분석 데이터
      "error": result.get("error", None) # 오류 메시지
    }

  except Exception as e:
    logger.error(f"❌ 평가 도중 오류 발생: {e}")
    return {"error": str(e)}, 500