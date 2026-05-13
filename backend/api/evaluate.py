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

async def run_evaluation_process(model, device, audio_np, expected_word, language="en", difficulty=3, mode="word", candidates=None, feedback_map=None):
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
  
  # 0. 초기 자유 전사 (Whisper가 처음 들은 그대로 확인용)
  raw_segments_gen, _ = model.model.transcribe(
    audio_np, 
    language=language,
    temperature=0,
    vad_filter=True
  )
  raw_text = "".join([s.text for s in raw_segments_gen]).strip().lower()
  print(f"\n📢 [Initial Whisper Transcription: '{raw_text}']")

  # 1. 모든 후보군에 대해 정렬 실행 및 결과 수집
  candidate_results = {}
  
  # 1. 각 후보군에 대해 정렬 실행 및 점수 비교
  try:
    model_a, metadata = get_align_model(language, device)
    
    print(f"🔍 [Multi-Alignment Search: {expected_word}]")
    for cand in candidates:
      # 후보 단어로 가상 세그먼트 생성
      temp_segments = [{"start": 0, "end": duration, "text": cand}]
      
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
      raw_text=raw_text,
      language=language,
      difficulty=difficulty,
      mode=mode,
      candidate_results=candidate_results,
      feedback_map=feedback_map
    )

    actual_text = evaluation["recognized_text"]
    best_result_aligned = evaluation.get("aligned_result", {})

    print(f"✅ Final Choice: '{actual_text}'\n")

    return {
      "language": language,
      "expected": expected_word,
      "recognized_text": actual_text,
      "score": evaluation.get("score", 0),
      "word_details": evaluation.get("word_details", []),
      "feedback": evaluation.get("feedback", ""),
      "char_segments": best_result_aligned.get("char_segments", []) if best_result_aligned else [],
      "word_segments": best_result_aligned.get("word_segments", []) if best_result_aligned else []
    }
    
  except Exception as e:
    logger.error(f"❌ Alignment 실패: {e}")
    return {
      "language": language,
      "expected": expected_word,
      "recognized_text": "recognition_error",
      "score": 0,
      "feedback": f"분석 오류: {str(e)}",
      "word_details": [],
      "char_segments": [],
      "word_segments": [],
      "error": str(e)
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
  difficulty: int = Form(3),
  mode: str = Form("word"),
  candidates: str = Form(None),   # JSON string
  feedback_map: str = Form(None)  # JSON string
):
  model = request.app.state.model
  device = getattr(request.app.state, "device", "cpu")
  
  # JSON 문자열 파싱
  parsed_candidates = None
  parsed_feedback_map = None
  
  try:
    if candidates:
      parsed_candidates = json.loads(candidates)
    if feedback_map:
      parsed_feedback_map = json.loads(feedback_map)
  except Exception as e:
    logger.warning(f"Failed to parse candidates or feedback_map: {e}")

  try:
    # 1. 파일 데이터 읽기
    file_bytes = await file.read()
    filename = file.filename.lower()

    if filename.endswith(".raw") or filename.endswith(".pcm"):
      # 2-1. Raw PCM 처리 (FFmpeg 불필요, 로컬 실행용)
      audio_np = np.frombuffer(file_bytes, dtype=np.int16).astype(np.float32) / 32768.0
      result = await run_evaluation_process(
        model, device, audio_np, expected, language, difficulty, mode, 
        candidates=parsed_candidates, feedback_map=parsed_feedback_map
      )
    else:
      # 2-2. 표준 오디오 형식 처리 (FFmpeg 필요, Cloud Run/Docker용)
      with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp_file:
        tmp_file.write(file_bytes)
        tmp_path = tmp_file.name

      try:
        audio_np = whisperx.load_audio(tmp_path)
        result = await run_evaluation_process(
          model, device, audio_np, expected, language, difficulty, mode, 
          candidates=parsed_candidates, feedback_map=parsed_feedback_map
        )
      finally:
        if os.path.exists(tmp_path):
          os.remove(tmp_path)

    return {
      "language": result["language"],
      "expected": expected,
      "recognized_text": result["recognized_text"],
      "score": result["score"],
      "feedback": result["feedback"],
      "word_details": result.get("word_details", []),
      "char_segments": result.get("char_segments", []),
      "word_segments": result.get("word_segments", [])
    }

  except Exception as e:
    logger.error(f"❌ 평가 도중 오류 발생: {e}")
    return {"error": str(e)}, 500