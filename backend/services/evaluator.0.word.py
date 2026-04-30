import difflib

def evaluate_pronunciation(expected: str, actual: str):
  """
  expected: 정답 단어/문장
  actual: Whisper가 인식한 결과
  """
  expected = expected.lower().strip()
  actual = actual.lower().strip().replace(".", "").replace(",", "")

  # 인식 실패
  if not actual:
    return {
      "score": 0,
      "error": "no speech detected",
      "feedback": "음성을 인식하지 못했어요. 다시 시도해주세요."
    }

  # 완전 일치
  if expected == actual:
    return {
      "score": 100,
      "error": None,
      "feedback": "완벽해요 👍"
    }

  # -----------------------------------
  # 규칙 기반 예시 (Rule-based)
  # -----------------------------------
  if expected == "cat" and actual in ["ca", "kat", "cut"]:
    return {
      "score": 75,
      "error": "final consonant weak",
      "feedback": "끝소리 't' 발음이 약해요."
    }

  if expected == "rabbit" and "labbit" in actual:
    return {
      "score": 70,
      "error": "r/l confusion",
      "feedback": "'r' 발음이 'l'처럼 들려요."
    }
  
  # if expected == "rabbit" and not actual.endswith("t"):
  #   return {
  #     "score": 70,
  #     "error": "final consonant weak",
  #     "feedback": "끝소리 't' 발음이 약해요."
  #   }

  if expected == "boat" and actual in ["bo", "bot"]:
    return {
      "score": 72,
      "error": "ending sound missing",
      "feedback": "마지막 't' 소리를 더 또렷하게 발음해보세요."
    }

  # -----------------------------------
  # 기본 유사도 계산 (difflib)
  # -----------------------------------
  matcher = difflib.SequenceMatcher(None, expected, actual)
  score = int(matcher.ratio() * 100)

  return {
    "score": score,
    "error": "pronunciation mismatch",
    "feedback": f'"{actual}" 로 들렸어요. 다시 시도해보세요.'
  }
