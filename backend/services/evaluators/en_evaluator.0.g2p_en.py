import difflib
import logging
from .base import BaseEvaluator

logger = logging.getLogger(__name__)

# g2p_en 설치 여부 확인 및 로드
try:
  from g2p_en import G2p
  g2p = G2p()
  HAS_G2P = True
except ImportError:
  HAS_G2P = False
  logger.warning("⚠️ 'g2p_en' 라이브러리가 설치되지 않았습니다. 문자 기반 비교로 대체합니다.")

class EnglishEvaluator(BaseEvaluator):
  def evaluate(self, expected: str, actual: str, word_list: list = None) -> dict:
    expected = expected.lower().strip()
    actual = actual.lower().strip()
    word_list = [w.lower() for w in (word_list or [])]

    if not actual:
      return {
        "score": 0,
        "feedback": "음성을 인식하지 못했어요. 다시 시도해주세요."
      }

    if expected == actual:
      return {
        "score": 100,
        "feedback": "완벽해요 👍"
      }

    # 1. Phoneme(음소) 기반 점수 계산
    if HAS_G2P:
      print(f"Phoneme-based evaluation")
      score = self._calculate_phoneme_score(expected, actual)
    else:
      # Fallback: 문자 기반 유사도
      print(f"Character-based evaluation")
      matcher = difflib.SequenceMatcher(None, expected, actual)
      score = int(matcher.ratio() * 100)

    # 2. 피드백 생성
    feedback = self._generate_feedback(expected, actual, word_list, score)

    return {
      "score": score,
      "feedback": feedback
    }

  def _calculate_phoneme_score(self, expected: str, actual: str) -> int:
    """g2p_en을 사용하여 음소 유사도 계산"""
    # 음소 변환 (예: "rabbit" -> ["R", "AE1", "B", "IH0", "T"])
    expected_phonemes = [p for p in g2p(expected) if p.strip()]
    actual_phonemes = [p for p in g2p(actual) if p.strip()]
    print(f"expected: {expected_phonemes}, actual: {actual_phonemes}")

    # 유사도 계산 (SequenceMatcher 사용)
    matcher = difflib.SequenceMatcher(None, expected_phonemes, actual_phonemes)
    return int(matcher.ratio() * 100)

  def _generate_feedback(self, expected: str, actual: str, word_list: list, score: int) -> str:
    """기존의 특정 단어 규칙 및 점수대별 피드백 유지"""
    
    # 특정 단어 규칙 (기존 로직 이식)
    # if expected == "rabbit":
    #   if "labbit" in word_list or actual.startswith("lab"):
    #     return "👉 r 발음이 l처럼 들려요. 혀 끝을 입천장에 닿지 않게 주의하세요!"
    #   elif "habit" in word_list:
    #     return "👉 'r' 발음이 'h'처럼 들릴 수 있어요. 혀를 조금 더 굴려주세요."

    # if expected == "dog" and any(w in ["dot", "dock"] for w in word_list):
    #   return "👉 끝소리 'g'를 조금 더 명확하게 발음해보세요."

    # 기본 피드백
    if score >= 90:
      return "거의 완벽합니다! 아주 좋아요."
    elif score >= 70:
      return "잘 읽으셨어요! 조금만 더 연습해봐요."
    else:
      return "인식된 발음이 조금 달라요. 다시 한번 천천히 말해볼까요?"
