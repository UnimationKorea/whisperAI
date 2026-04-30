import difflib

def evaluate_pronunciation(expected: str, actual: str, word_list: list = None):
  """
  expected: 정답 단어/문장
  actual: 인식된 전체 문장
  word_list: WhisperX가 추출한 개별 단어 리스트
  """
  expected = expected.lower().strip()
  # actual = actual.lower().strip().replace(".", "").replace(",", "")
  actual = actual.lower().strip()
  word_list = [w.lower() for w in (word_list or [])]

  # 1. 기본 인식 실패 처리
  if not actual:
    return {
      "score": 0,
      "error": "no speech detected",
      "feedback": "음성을 인식하지 못했어요. 다시 시도해주세요."
    }

  # 2. 완전 일치 처리
  if expected == actual:
    return {
      "score": 100,
      "error": None,
      "feedback": "완벽해요 👍"
    }

  # 3. 기본 유사도 기반 점수 계산 (difflib)
  matcher = difflib.SequenceMatcher(None, expected, actual)
  base_score = int(matcher.ratio() * 100)
  
  result = {
    "score": base_score,
    "error": None,
    "feedback": "잘 읽으셨어요! 조금만 더 연습해봐요."
  }

  # 4. 정밀 발음 교정 규칙 (Specific Rules)
  
  # Case: Rabbit (R vs L 발음)
  if expected == "rabbit":
    if "labbit" in word_list or actual.startswith("lab"):
      result["score"] = min(result["score"], 60)
      result["feedback"] = "👉 r 발음이 l처럼 들려요. 혀 끝을 입천장에 닿지 않게 주의하세요!"
    elif "habit" in word_list:
      result["score"] = min(result["score"], 70)
      result["feedback"] = "👉 'r' 발음이 'h'처럼 들릴 수 있어요. 혀를 조금 더 굴려주세요."

  # Case: Dog
  if expected == "dog" and actual in ["dot", "dock"]:
    result["score"] = min(result["score"], 80)
    result["feedback"] = "👉 끝소리 'g'를 조금 더 명확하게 발음해보세요."

  # 80점 이상일 때의 기본 긍정 피드백
  if result["score"] >= 90 and result["feedback"] == "잘 읽으셨어요! 조금만 더 연습해봐요.":
    result["feedback"] = "거의 완벽합니다! 아주 좋아요."

  return result
