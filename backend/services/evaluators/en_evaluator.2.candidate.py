import re
import difflib
import logging
from .base import BaseEvaluator

logger = logging.getLogger(__name__)

class EnglishEvaluator(BaseEvaluator):
  def evaluate(self, expected: str, actual: str, word_list: list = None, aligned_segments: list = None, difficulty: int = 3) -> dict:
    expected = expected.lower().strip()
    actual = actual.lower().strip()
    candidates = word_list or [expected]
    
    # 1. 발음 명확도(Clarity) 분석
    clarity_score = 0
    if aligned_segments:
      clarity_score = self._calculate_clarity_score(expected, aligned_segments)

    # 2. 순위 및 난이도 기반 기본 점수 산출
    # 난이도에 따른 감점 폭 설정 (난이도 1: 5점, 3: 15점, 5: 25점)
    score_gap = 5 + (difficulty - 1) * 5 
    
    try:
      # 후보군 리스트에서 몇 번째 단어인지 인덱스 찾기
      index = candidates.index(actual)
      base_score = 100 - (index * score_gap)
    except ValueError:
      # 후보군에 없는 엉뚱한 단어인 경우
      base_score = 0

    # 3. 최종 점수 산출
    # 난이도가 높을수록 명확도(Clarity)에 더 엄격한 기준 적용
    clarity_threshold = 60 + (difficulty * 4) # 1단계: 64점, 5단계: 80점 기준
    
    if base_score >= 100 - score_gap: # 정답 혹은 매우 유사한 경우
      # 명확도가 기준치보다 낮으면 감점
      if clarity_score < clarity_threshold:
        final_score = int(base_score * (clarity_score / clarity_threshold))
      else:
        final_score = base_score
    elif base_score > 0:
      # 오답 후보인 경우 명확도 비율대로 적용
      final_score = int(base_score * (clarity_score / 100))
    else:
      final_score = 0

    # 전문가 모드(5단계) 보정: 정답이더라도 발음이 완벽하지 않으면 100점을 주지 않음
    if difficulty >= 5 and actual == expected and clarity_score < 95:
      final_score = min(95, final_score)
    elif actual == expected and clarity_score >= 92:
      final_score = 100 # 일반 모드 100점 보정

    # 4. 피드백 생성
    feedback = self._generate_candidate_feedback(expected, actual, final_score, clarity_score)

    return {
      "score": min(100, max(0, final_score)),
      "feedback": feedback
    }

  def _calculate_clarity_score(self, expected: str, aligned_segments: list) -> int:
    """철자별 신뢰도를 평균내어 발음의 명확도 점수 계산"""
    total_score = 0
    char_count = 0
    
    print(f"\n--- [Clarity Calculation: {expected}] ---")
    for segment in aligned_segments:
      # if "words" in segment:
      #   for w in segment["words"]:
      #     word_text = w.get("word", "[unknown]")
      #     chars = w.get("chars", [])
      #     print(f"Word: '{word_text}'")

      # WhisperX 버전에 따라 chars가 segment 레벨에 있을 수 있습니다.
      chars = segment.get("chars", [])
      text = segment.get("text", "[unknown]")
      print(f"Segment Text: '{text}'")
      
      for c in chars:
        char_val = c.get("char", "-")
        char_score = c.get("score", 0)
        # score가 존재하면 합산
        total_score += char_score
        char_count += 1
        print(f"  └ '{char_val}': {char_score:.4f}")
    
    if char_count == 0:
      print("⚠️ No character scores found in aligned segments.")
      return 0
      
    avg_score = total_score / char_count
    final_clarity = int(avg_score * 100)
    print(f"📊 Total: {total_score:.4f} / Count: {char_count}")
    print(f"✨ Final Clarity Score: {final_clarity} (Average: {avg_score:.4f})")
    print("------------------------------------------\n")
      
    return final_clarity

  def _generate_candidate_feedback(self, expected: str, actual: str, score: int, clarity: int) -> str:
    """선택된 후보 단어에 따른 맞춤형 피드백"""
    
    # 정답과 일치하는 경우
    if expected == actual:
      if clarity >= 90:
        return f"완벽합니다! (점수: {score}) 원어민 같은 발음이에요. 👍"
      elif clarity >= 70:
        return f"정답입니다! (점수: {score}) 발음을 조금만 더 또박또박 하면 100점을 받을 수 있어요."
      else:
        return f"단어는 맞았지만 발음이 흐릿해요. (점수: {score}) 더 큰 소리로 명확하게 발음해보세요!"

    # 오답 후보군별 전용 피드백
    variants_feedback = {
      "rabbit": {
        "rabbit-it": "👉 'rabbit' 끝에 'it' 소리가 섞여 들려요. 조금 더 깔끔하게 끝내보세요.",
        "rabbit-e": "👉 'rabbit' 끝에 'e' 소리가 덧붙여진 것 같아요. 주의해서 다시 발음해보세요.",
        "labbit": "👉 'r' 발음이 'l'처럼 들려요. 혀끝을 입천장에 대지 말고 살짝 말아보세요!",
        "habit": "👉 'r' 발음이 'h'처럼 들려요. 입술을 좀 더 동그랗게 모으고 시작해보세요.",
        "babbit": "👉 첫 소리가 'b'처럼 들려요. 입술을 붙이지 말고 소리를 내보세요."
      },
      "dog": {
        "dod": "👉 끝소리 'g'가 'd'처럼 들려요. 목 안쪽에서 소리를 더 울려주세요.",
        "dag": "👉 모음 'o'가 'a'처럼 들려요. 입을 더 동그랗게 벌려보세요.",
        "dot": "👉 끝소리 'g'가 't'처럼 짧게 들려요. 목청을 조금 더 울려주세요.",
        "dock": "👉 끝소리 'g'가 'k'처럼 들려요. 공기를 밖으로 훅 내뱉지 마세요.",
        "log": "👉 첫 소리 'd'가 'l'처럼 들려요. 혀끝을 윗니 뒤쪽에 강하게 대보세요."
      },
      "tiger": {
        "tyger": "👉 발음이 유사하지만 중간 모음이 약간 달라요. '타이거'에 집중해보세요.",
        "tighter": "👉 중간 'g' 발음이 't'처럼 들려요. 더 부드럽게 넘어가보세요.",
        "tigger": "👉 중간 모음 'i'가 짧게 들려요. 좀 더 길게 발음해볼까요?",
        "ticker": "👉 'g' 발음이 'k'처럼 들려요. 목 안쪽에서 소리를 더 울려주세요.",
        "diger": "👉 첫 소리 't'가 'd'처럼 들려요. 공기를 좀 더 강하게 뿜어보세요."
      },
      "cat": {
        "cat": "정답입니다!", # Fallback
        "cap": "👉 끝소리 't'가 'p'처럼 들려요. 혀끝을 윗니 뒤에 붙이며 멈춰보세요.",
        "cut": "👉 모음 'a'가 'u'처럼 들려요. 입을 더 크게 벌리고 소리 내보세요.",
        "sat": "👉 첫 소리 'c'가 's'처럼 들려요. 목 뒤쪽에서 '큭' 하는 느낌으로 시작하세요.",
        "cad": "👉 끝소리가 'd'처럼 들려요. 좀 더 가볍게 터뜨려보세요.",
        "cart": "👉 중간에 'r' 소리가 섞여 들려요. 혀를 굴리지 말고 짧게 끊어보세요."
      },
      "caw": {
        "claw": "👉 중간에 'l' 소리가 섞여 들려요. 혀를 움직이지 말고 소리 내보세요.",
        "how": "👉 첫 소리가 'h'처럼 들려요. 목 안쪽에서 더 강하게 'ㅋ' 소리를 내주세요.",
        "raw": "👉 첫 소리가 'r'처럼 들려요. 'c'의 'ㅋ' 소리에 집중해보세요.",
        "saw": "👉 첫 소리가 's'처럼 들려요. 'ㅋ' 소리를 더 명확히 내주세요.",
        "caught": "👉 끝에 't' 소리가 들려요. 소리를 그냥 길게 빼면서 마무리하세요."
      }
    }

    # 해당되는 피드백 찾기
    specific_feedback = variants_feedback.get(expected, {}).get(actual)
    if specific_feedback:
      return specific_feedback

    # 공통 오답 피드백
    return f"👉 '{expected}'와 약간 다르게 들려요. 인식된 발음: '{actual}'"
