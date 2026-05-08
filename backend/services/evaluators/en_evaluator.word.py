import re
import difflib
import logging
from g2p_en import G2p
from .base import BaseEvaluator

logger = logging.getLogger(__name__)

class EnglishEvaluator(BaseEvaluator):
  def __init__(self):
    self.g2p = G2p()

  def evaluate(self, expected: str, candidates: list, raw_text: str = "", candidate_results: dict = None, difficulty: int = 3) -> dict:
    """
    영어 전용 평가 로직: 
    1. Whisper의 자유 인식 결과(raw_text)와 후보군 간의 '음소 거리' 계산
    2. 정렬 점수(Acoustic)와 음소 유사도(Phonetic)를 결합하여 최적의 단어 선택
    3. 선택된 단어로 최종 점수 및 피드백 산출
    """
    expected = expected.lower().strip()
    raw_text = raw_text.lower().strip()
    
    # 1. 최적의 후보(actual) 선택 로직 (방법 D: 음소 편집 거리 보정)
    best_candidate = expected
    highest_composite_score = -1
    best_aligned_result = None

    # raw_text의 음소 추출
    raw_phonemes = self.g2p(raw_text)
    # 문장 부호 및 공백 제거
    raw_phonemes = [p for p in raw_phonemes if re.match(r'\w+', p)]

    print(f"--- [Phonetic Correction Selection (English)] ---")
    print(f"Initial raw transcription: '{raw_text}' -> Phonemes: {raw_phonemes}")

    for cand in candidates:
      res = candidate_results.get(cand, {})
      alignment_score = res.get("avg_score", 0)
      
      # 후보 단어의 음소 추출
      cand_phonemes = self.g2p(cand)
      cand_phonemes = [p for p in cand_phonemes if re.match(r'\w+', p)]
      
      # 음소 유사도 계산 (1.0 - 정규화된 편집거리)
      dist = self._levenshtein_distance(raw_phonemes, cand_phonemes)
      max_len = max(len(raw_phonemes), len(cand_phonemes), 1)
      phonetic_similarity = 1.0 - (dist / max_len)
      
      # 복합 점수 산출 (가중치: 물리적 정렬 60% + 음소 유사도 40%)
      # Whisper가 raw_text로 정확히 맞췄다면(유사도 1.0), 
      # 물리 점수가 조금 낮아도(예: tiger vs tire) 정답이 선택될 확률이 높음
      composite_score = (alignment_score * 0.6) + (phonetic_similarity * 0.4)
      
      # 제시어 우선권 부여 (정답 단어와 일치하면 강력한 보너스 부여)
      bonus_str = ""
      if cand == expected:
        composite_score += 0.1
        bonus_str = " [+0.1 Expected Bonus]"
      
      print(f"  - '{cand}': Align({alignment_score:.3f}) + Phonetic({phonetic_similarity:.3f}) = Comp({composite_score:.3f}){bonus_str}")

      if composite_score > highest_composite_score:
        highest_composite_score = composite_score
        best_candidate = cand
        best_aligned_result = res.get("result")

    print(f"🏆 Selected Candidate: '{best_candidate}'")
    print(f"--------------------------------------------------\n")

    # 2. 최종 선택된 단어로 명확도(Clarity) 및 점수 산출
    actual = best_candidate
    aligned_segments = best_aligned_result.get("segments", []) if best_aligned_result else []
    
    # 명확도 점수 계산
    clarity_score = self._calculate_clarity_score(expected, aligned_segments)

    # 순위 및 난이도 기반 점수 산출
    score_gap = 5 + (difficulty - 1) * 5 
    try:
      index = candidates.index(actual)
      base_score = 100 - (index * score_gap)
    except ValueError:
      base_score = 0

    # 최종 점수 산출 (난이도 가중치 적용)
    clarity_threshold = 60 + (difficulty * 4)
    if base_score >= 100 - score_gap:
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

    # 3. 피드백 생성
    feedback = self._generate_candidate_feedback(expected, actual, final_score, clarity_score)

    return {
      "score": min(100, max(0, final_score)),
      "feedback": feedback,
      "recognized_text": actual,
      "aligned_result": best_aligned_result
    }

  def _levenshtein_distance(self, s1, s2):
    """편집 거리 알고리즘 (음소 리스트 비교용)"""
    if len(s1) < len(s2):
      return self._levenshtein_distance(s2, s1)
    if not s2:
      return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
      current_row = [i + 1]
      for j, c2 in enumerate(s2):
        insertions = previous_row[j + 1] + 1
        deletions = current_row[j] + 1
        substitutions = previous_row[j] + (c1 != c2)
        current_row.append(min(insertions, deletions, substitutions))
      previous_row = current_row
    return previous_row[-1]

  def _calculate_clarity_score(self, expected: str, aligned_segments: list) -> int:
    """철자별 신뢰도를 평균내어 발음의 명확도 점수 계산"""
    total_score = 0
    char_count = 0
    
    print(f"--- [Clarity Calculation: {expected}] ---")
    for segment in aligned_segments:
      chars = segment.get("chars", [])
      text = segment.get("text", "[unknown]")
      print(f"Segment Text: '{text}'")
      for c in chars:
        char_val = c.get("char", "-")
        char_score = c.get("score", 0)
        total_score += char_score
        char_count += 1
        print(f"  └ '{char_val}': {char_score:.4f}")
    
    if char_count == 0:
      print("⚠️ No character scores found.")
      return 0
      
    avg_score = total_score / char_count
    final_clarity = int(avg_score * 100)
    print(f"📊 Final Clarity: {final_clarity} (Average: {avg_score:.4f})")
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
        "cap": "👉 끝소리 't'가 'p'처럼 들려요. 혀끝을 윗니 뒤에 붙이며 멈춰보세요.",
        "cart": "👉 중간에 'r' 소리가 섞여 들려요. 혀를 굴리지 말고 짧게 끊어보세요.",
        "cad": "👉 끝소리가 'd'처럼 들려요. 좀 더 가볍고 짧게 't' 소리를 내보세요.",
        "ket": "👉 모음 'a'가 'e'처럼 들려요. 입을 더 위아래로 벌려보세요.",
        "cut": "👉 모음 'a'가 'u'처럼 들려요. 입을 더 크게 벌리고 소리 내보세요.",
        "sat": "👉 첫 소리 'c'가 's'처럼 들려요. 목 뒤쪽에서 '큭' 하는 느낌으로 시작하세요.",
      },
      "cow": {
        "core": "👉 소리가 입안에서 너무 굴러가요. 혀를 고정하고 길게 '오-' 소리를 내보세요.",
        "call": "👉 끝에 'l' 소리가 섞여 들려요. 혀를 입천장에 대지 마세요.",
        "claw": "👉 중간에 'l' 소리가 섞여 들려요. 혀를 움직이지 말고 소리 내보세요.",
        "how": "👉 첫 소리가 'h'처럼 들려요. 목 안쪽에서 더 강하게 'ㅋ' 소리를 내주세요.",
        "raw": "👉 첫 소리가 'r'처럼 들려요. 'c'의 'ㅋ' 소리에 집중해보세요.",
        "saw": "👉 첫 소리가 's'처럼 들려요. 'ㅋ' 소리를 더 명확히 내주세요.",
        "caught": "👉 끝에 't' 소리가 들려요. 소리를 그냥 길게 빼면서 마무리하세요."
      },
      "chicken": {
        "kitchen": "👉 요리하는 '주방(kitchen)'처럼 들려요. 'ch' 소리를 더 강하게 터뜨려보세요.",
        "checking": "👉 'checking'처럼 들려요. 마지막 'n' 소리를 짧고 간결하게 마무리하세요.",
        "chick": "👉 단어 끝부분이 생략되었어요. '치킨'하고 끝까지 발음해볼까요?",
        "shicken": "👉 'ch'가 'sh'처럼 부드럽게 들려요. 좀 더 강하게 '치' 소리를 내보세요."
      },
      "horse": {
        "house": "👉 살고 있는 '집(house)'처럼 들려요. 중간에 'r' 소리를 넣어 혀를 살짝 굴려보세요.",
        "hose": "👉 'r' 소리가 빠진 'hose'처럼 들려요. 모음을 조금 더 길고 깊게 발음해 보세요.",
        "force": "👉 첫 소리가 'f'처럼 들려요. 윗니로 입술을 물지 말고 'ㅎ' 소리를 내보세요.",
        "heart": "👉 'heart'처럼 들려요. 끝소리를 's' 발음으로 부드럽게 마무리하세요."
      },
      "sheep": {
        "ship": "👉 'i' 소리가 짧은 'ship'처럼 들려요. 입술을 양옆으로 더 찢으며 '이-'하고 길게 소리 내보세요.",
        "cheap": "👉 첫 소리가 'ch'처럼 강해요. 공기를 살며시 내뱉으며 '쉬-' 소리를 내보세요.",
        "sleep": "👉 'sh' 대신 'sl' 소리가 들려요. 혀를 입천장에 대지 말고 시작해 보세요.",
        "sheet": "👉 끝소리가 't'로 들려요. 입술을 내밀며 '프' 소리로 가볍게 닫아주세요."
      },
      "goat": {
        "coat": "👉 첫 소리가 'c'처럼 들려요. 목청을 울려 '그' 소리로 시작해 보세요.",
        "boat": "👉 첫 소리가 'b'처럼 들려요. 입술을 붙이지 말고 목 안쪽에서 소리를 내보세요.",
        "gate": "👉 모음이 'a'처럼 들려요. 입을 더 동그랗게 모아서 '오' 소리를 내보세요.",
        "ghost": "👉 끝에 's' 소리가 섞여 있어요. '트' 소리로 깔끔하게 멈춰보세요."
      },
      "monkey": {
        "money": "👉 'k' 소리가 빠진 '돈(money)'처럼 들려요. 중간에 '크' 소리를 살짝 넣어주세요.",
        "donkey": "👉 첫 소리가 'd'처럼 들려요. 'ㅁ' 소리로 부드럽게 시작해 보세요.",
        "monk": "👉 끝부분 'key' 발음이 빠졌어요. 끝까지 '멍키'라고 발음해 보세요.",
        "funky": "👉 첫 소리가 'f'처럼 들려요. 입술을 다물고 'ㅁ' 소리를 내보세요."
      },
      "duck": {
        "deck": "👉 모음이 'e'처럼 들려요. 입을 더 아래로 턱을 내리며 '어' 소리를 내보세요.",
        "dock": "👉 모음이 'o'처럼 들려요. 입을 너무 동그랗게 벌리지 말고 발음해 보세요.",
        "dark": "👉 'r' 소리가 섞여 들려요. 혀를 굴리지 말고 짧게 '덕' 하고 끊어보세요.",
        "tuck": "👉 첫 소리가 't'처럼 들려요. 목청을 울리는 '드' 소리로 시작해 보세요."
      },
      "lion": {
        "line": "👉 'line'처럼 들려요. 뒤에 '언' 소리를 추가해서 '라이온'이라고 발음해 보세요.",
        "iron": "👉 첫 소리 'l'이 빠진 'iron'처럼 들려요. 혀끝을 윗니 뒤에 대고 시작해 보세요.",
        "ryan": "👉 첫 소리가 'r'처럼 들려요. 혀를 말지 말고 윗니 뒤에 대보세요.",
        "lying": "👉 'lying'처럼 들려요. 끝소리를 코로 내지 말고 입을 살짝 벌리며 마무리하세요."
      },
      "fox": {
        "box": "👉 첫 소리가 'b'처럼 들려요. 윗니로 아랫입술을 가볍게 물고 바람을 내뱉어 보세요.",
        "ox": "👉 첫 소리 'f'가 빠진 '황소(ox)'처럼 들려요. 아랫입술을 살짝 물고 바람을 세게 내뿜어 보세요.",
        "fax": "👉 모음이 'a'처럼 들려요. 입을 위아래로 더 크게 벌려 '아'와 '오' 사이 소리를 내보세요.",
        "force": "👉 끝소리가 'ce'처럼 들려요. 'ks' 소리를 내며 짧게 끊어보세요."
      },
      "deer": {
        "dear": "👉 발음은 좋지만 'dear'와 혼동될 수 있어요. 문맥에 따라 주의가 필요해요.",
        "beer": "👉 첫 소리가 'b'처럼 들려요. 혀끝을 윗니 뒤에 대고 '드' 소리를 내보세요.",
        "fear": "👉 첫 소리가 'f'처럼 들려요. 입술을 물지 말고 혀를 사용해 보세요.",
        "door": "👉 모음이 'o'처럼 들려요. 입을 양옆으로 살짝 당기며 '이-' 소리를 섞어보세요."
      }
    }

    # 해당되는 피드백 찾기
    specific_feedback = variants_feedback.get(expected, {}).get(actual)
    if specific_feedback:
      return f"{specific_feedback} (점수: {score})"

    return f"👉 '{expected}'와 약간 다르게 들려요. (인식: '{actual}', 점수: {score})"
