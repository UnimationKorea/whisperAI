import re
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
  def evaluate(self, expected: str, actual: str, word_list: list = None, aligned_segments: list = None) -> dict:
    # 특수문자 제거 (마침표, 느낌표, 물음표 등 제외)
    expected = re.sub(r'[^\w\s]', '', expected).lower().strip()
    actual = re.sub(r'[^\w\s]', '', actual).lower().strip()
    word_list = [re.sub(r'[^\w\s]', '', w).lower() for w in (word_list or [])]

    if not actual:
      return {
        "score": 0,
        "feedback": "음성을 인식하지 못했어요. 다시 시도해주세요."
      }

    # 1. 음소 유사도 점수 계산 (정답 단어와 인식 단어 비교)
    if HAS_G2P:
      phoneme_score = self._calculate_phoneme_score(expected, actual)
    else:
      # Fallback: 문자 기반 유사도
      matcher = difflib.SequenceMatcher(None, expected, actual)
      phoneme_score = int(matcher.ratio() * 100)

    # 2. 발음 명확도(Clarity) 분석 (철자별 신뢰도 기반)
    clarity_score = 100
    if aligned_segments:
      clarity_score = self._calculate_clarity_score(expected, aligned_segments)
    
    # 3. 최종 점수 산출 (음소 유사도와 명확도의 조합)
    # 음소 자체가 틀리면 감점이 크고, 음소는 맞는데 발음이 흐릿하면 명확도 점수가 영향을 줍니다.
    score = int((phoneme_score * 0.7) + (clarity_score * 0.3))

    # 완벽 일치 시 점수 보정
    if expected == actual and phoneme_score >= 95:
      # 발음이 아주 약간 흐릿하더라도 텍스트가 정확하면 최소 점수 보장
      score = max(score, 90 if clarity_score > 60 else 70)
    
    if expected == actual and phoneme_score >= 98 and clarity_score >= 90:
      score = 100

    # 4. 피드백 생성
    feedback = self._generate_feedback(expected, actual, word_list, score, clarity_score)

    return {
      "score": score,
      "feedback": feedback
    }

  def _calculate_clarity_score(self, expected: str, aligned_segments: list) -> int:
    """철자별 신뢰도를 평균내어 발음의 명확도 점수 계산"""
    total_score = 0
    char_count = 0
    
    for segment in aligned_segments:
      if "words" in segment:
        for w in segment["words"]:
          # 정답 단어와 일치하거나 매우 유사한 단어의 철자 점수를 분석
          if w.get("word", "").lower().strip() in [expected, ""]:
            # WhisperX에서 return_char_alignments=True일 때 각 word는 'chars' 리스트를 가질 수 있음
            chars = w.get("chars", [])
            for c in chars:
              if "score" in c:
                total_score += c["score"]
                char_count += 1
    
    if char_count == 0:
      return 100 # 데이터가 없으면 기본값
      
    return int((total_score / char_count) * 100)

  def _calculate_phoneme_score(self, expected: str, actual: str) -> int:
    """g2p_en을 사용하여 음소 유사도 계산 (특수문자 제외)"""
    # 알파벳이나 숫자가 포함된 유효한 음소만 추출
    expected_phonemes = [p for p in g2p(expected) if p.strip() and re.search(r'[a-zA-Z0-9]', p)]
    actual_phonemes = [p for p in g2p(actual) if p.strip() and re.search(r'[a-zA-Z0-9]', p)]
    print(f"expected: {expected_phonemes}, actual: {actual_phonemes}")

    # 유사도 계산 (SequenceMatcher 사용)
    matcher = difflib.SequenceMatcher(None, expected_phonemes, actual_phonemes)
    return int(matcher.ratio() * 100)

  def _generate_feedback(self, expected: str, actual: str, word_list: list, score: int, clarity_score: int) -> str:
    """세밀한 발음 교정 피드백 생성"""
    
    # 1. 특정 단어별 정밀 피드백 (L/R, G 등)
    if expected == "rabbit":
      # 인식된 텍스트에 l 발음이 섞여있는지 확인
      if "labbit" in word_list or actual.startswith("lab") or "L" in [p[0] for p in g2p(actual) if p]:
        return "👉 'r' 발음이 'l'처럼 들려요. 혀끝을 윗니 뒤에 대지 말고 안쪽으로 살짝 말아보세요!"
      elif "habit" in word_list or actual.startswith("hab"):
        return "👉 'r' 발음이 'h'처럼 들려요. 입술을 좀 더 동그랗게 모으고 소리를 내보세요."

    if expected == "dog" and any(w in ["dot", "dock"] for w in word_list):
      return "👉 끝소리 'g'가 't'나 'k'처럼 들려요. 목청을 조금 더 울려보세요."

    # 2. 명확도 기반 피드백 (철자 점수가 낮을 때)
    if clarity_score < 60:
      return "👉 단어는 맞게 인식되었지만 발음이 많이 흐릿해요. 한 글자씩 또박또박 발음해보세요!"
    elif clarity_score < 80 and score >= 80:
      return "👉 발음이 약간 뭉개졌어요. 조금만 더 명확하게 발음하면 완벽할 것 같아요!"

    # 3. 일반적인 점수대별 피드백
    if score >= 90:
      return "거의 완벽합니다! 아주 좋아요."
    elif score >= 75:
      return "잘 읽으셨어요! 특정 음절의 발음을 조금 더 명확하게 해볼까요?"
    elif score >= 50:
      return "발음이 조금 불분명해요. 한 글자씩 천천히 다시 말해보세요."
    else:
      return "인식된 발음이 예상과 많이 달라요. 정답 단어를 다시 확인하고 도전해보세요!"
