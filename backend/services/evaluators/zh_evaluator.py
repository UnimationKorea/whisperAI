import re
import difflib
import logging
from pypinyin import pinyin, Style # type: ignore
from .base import BaseEvaluator

logger = logging.getLogger(__name__)

class ChineseEvaluator(BaseEvaluator):
  def evaluate(self, expected: str, candidates: list, raw_text: str = "", candidate_results: dict = None, difficulty: int = 3, mode: str = "word", feedback_map: dict = None) -> dict:
    """
    중국어 평가 메인 진입점
    """
    if mode == "sentence":
      return self._evaluate_sentence(expected, raw_text, candidate_results, difficulty)
    else:
      return self._evaluate_word(expected, candidates, raw_text, candidate_results, difficulty, feedback_map)

  def _get_pinyin_tone(self, text: str):
    """
    한자를 병음과 성조 숫자로 분리하여 반환합니다.
    예: "你好" -> [("ni", 3), ("hao", 3)]
    """
    if not text:
      return []
    # Style.TONE3: 병음 뒤에 숫자가 붙는 형식 (ni3, hao3)
    py_list = pinyin(text, style=Style.TONE3, neutral_tone_with_five=True)
    results = []
    for item in py_list:
      token = item[0]
      # 숫자(성조) 분리 (예: ni3 -> 'ni', 3)
      match = re.match(r'([a-z]+)([1-5])', token.lower())
      if match:
        results.append((match.group(1), int(match.group(2))))
      else:
        # 성조 숫자가 없는 경우 경성(5)으로 처리
        results.append((token.lower(), 5))
    return results

  def _evaluate_word(self, expected: str, candidates: list, raw_text: str = "", candidate_results: dict = None, difficulty: int = 3, feedback_map: dict = None) -> dict:
    """
    중국어 단어 평가 로직 (후보군 매칭 + 병음 유사도 + 성조 분석)
    """
    expected = expected.strip()
    raw_text = raw_text.strip()
    
    # 1. 최적의 후보 선택 (Pinyin 유사도 및 Acoustic Score 결합)
    best_candidate = expected
    highest_composite_score = -1
    best_aligned_result = None

    # Whisper가 인식한 원본 텍스트의 병음 추출
    raw_py_data = self._get_pinyin_tone(raw_text)
    raw_py_str = "".join([f"{p}{t}" for p, t in raw_py_data])

    # 제시어(Target)의 병음 추출
    expected_py_data = self._get_pinyin_tone(expected)
    expected_py_str = "".join([f"{p}{t}" for p, t in expected_py_data])

    print(f"\n--- [Chinese Word Evaluation: {expected}] ---")
    print(f"Target Pinyin: {expected_py_str}")
    print(f"Initial raw transcription: '{raw_text}' -> Pinyin: {raw_py_str}")

    if not candidates:
      candidates = [expected]

    print(f"🔍 [Candidate Search & Phonetic Comparison]")
    for cand in candidates:
      res = candidate_results.get(cand, {})
      alignment_score = res.get("avg_score", 0)
      
      # 후보 단어의 pinyin 추출
      cand_py_data = self._get_pinyin_tone(cand)
      cand_py_str = "".join([f"{p}{t}" for p, t in cand_py_data])
      
      # Pinyin 유사도 계산 (1.0 - 정규화된 편집거리)
      dist = self._levenshtein_distance(raw_py_str, cand_py_str)
      max_len = max(len(raw_py_str), len(cand_py_str), 1)
      pinyin_similarity = 1.0 - (dist / max_len)
      
      # 복합 점수 산출 (Acoustic 60% + Pinyin 40%)
      composite_score = (alignment_score * 0.6) + (pinyin_similarity * 0.4)
      
      # 정답(제시어) 우선권 부여: 발음 유사도가 최소 기준(0.2)을 넘을 때만 부여
      bonus_str = ""
      if cand == expected and pinyin_similarity > 0.2:
        composite_score += 0.1
        bonus_str = " [+0.1 Expected Bonus]"
      
      print(f"  - '{cand}' ({cand_py_str}): Align({alignment_score:.3f}) + Pinyin({pinyin_similarity:.3f}) = Comp({composite_score:.3f}){bonus_str}")

      if composite_score > highest_composite_score:
        highest_composite_score = composite_score
        best_candidate = cand
        best_aligned_result = res.get("result")

    print(f"🏆 Final Selected Candidate: '{best_candidate}'")
    print(f"--------------------------------------------------\n")

    # 3. 임계값 체크: 너무 낮은 점수는 무시 (전혀 다른 단어로 간주)
    if highest_composite_score < 0.55:
      return {
        "score": 0,
        "feedback": f"👉 전혀 다른 단어로 들려요. (인식: '{raw_text}') 다시 한 번 또박또박 발음해보세요.",
        "recognized_text": raw_text,
        "word_details": [{
          "idx": 0,
          "expected": expected,
          "actual": raw_text,
          "is_correct": False,
          "score": 0
        }],
        "aligned_result": best_aligned_result
      }

    # 2. 최종 점수 및 피드백 산출
    actual = best_candidate
    
    # 발음 명확도(Clarity) 계산: WhisperX 정렬 시의 confidence score 평균
    aligned_segments = best_aligned_result.get("segments", []) if best_aligned_result else []
    clarity_score = self._calculate_clarity_score(expected, aligned_segments)

    # 후보 순위에 따른 감점 로직 (틀린 후보를 선택했을 경우 점수 차감)
    score_gap = 10 + (difficulty - 1) * 3
    try:
      index = candidates.index(actual)
      base_score = 100 - (index * score_gap) if actual != expected else 100
    except ValueError:
      base_score = 0

    # 명확도 기반 최종 점수 보정 (발음이 흐릿하면 추가 감점)
    clarity_threshold = 45 + (difficulty * 5)
    if actual == expected:
      if clarity_score < clarity_threshold:
        final_score = int(base_score * (clarity_score / clarity_threshold))
      else:
        # 고득점 보정
        final_score = base_score
        if difficulty >= 5 and clarity_score < 95:
          final_score = min(95, final_score)
        elif clarity_score >= 92:
          final_score = 100
    else:
      # 오답 후보 선택 시 명확도 비율대로 점수 적용
      final_score = int(base_score * (clarity_score / 100))

    # 피드백 생성
    feedback = self._generate_candidate_feedback(expected, actual, final_score, clarity_score, feedback_map)

    # 상세 정보 구성
    word_details = [{
      "idx": 0,
      "expected": expected,
      "actual": actual,
      "is_correct": (actual == expected),
      "score": final_score
    }]

    return {
      "score": max(0, min(100, final_score)),
      "feedback": feedback,
      "recognized_text": actual,
      "word_details": word_details,
      "aligned_result": best_aligned_result
    }

  def _evaluate_sentence(self, expected: str, raw_text: str = "", candidate_results: dict = None, difficulty: int = 3) -> dict:
    """
    중국어 문장 평가 로직: 글자 단위 정렬 및 성조 분석
    """
    # 0. 전처리: 불필요한 기호 제거
    expected_clean = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', expected)
    raw_clean = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', raw_text)
    
    # 정답 문장에 대한 정렬 데이터 로드
    res = candidate_results.get(expected, {})
    best_aligned_result = res.get("result")
    
    print(f"\n--- [Chinese Sentence Evaluation: {expected}] ---")
    print(f"Raw transcription: '{raw_text}' -> Cleaned: '{raw_clean}'")

    # 1. 글자 단위 정렬 분석
    matcher = difflib.SequenceMatcher(None, expected_clean, raw_clean)
    opcodes = matcher.get_opcodes()
    
    word_details = []
    total_score = 0
    char_count = len(expected_clean)
    
    # 정답 및 인식 결과의 병음/성조 추출
    exp_py = self._get_pinyin_tone(expected_clean)
    raw_py = self._get_pinyin_tone(raw_clean)

    # 정답 문장의 병음 출력
    exp_py_str = "".join([f"{p}{t}" for p, t in exp_py])
    print(f"Target Pinyin: {exp_py_str}")

    print(f"[Debug] Expected Pinyin: {exp_py}")
    print(f"[Debug] Raw Pinyin: {raw_py}")

    print(f"🔍 [Character-level Analysis]")
    for tag, i1, i2, j1, j2 in opcodes:
      # difflib의 opcode에 따라 매칭 정보 구성
      for k in range(max(i2 - i1, j2 - j1)):
        exp_idx = i1 + k if (i1 + k) < i2 else None
        raw_idx = j1 + k if (j1 + k) < j2 else None
        
        exp_char = expected_clean[exp_idx] if exp_idx is not None else None
        raw_char = raw_clean[raw_idx] if raw_idx is not None else None
        
        char_score = 0
        tone_error = False
        
        if exp_char and raw_char:
          print(f"  - [{exp_char}] vs [{raw_char}]", end=" ")
          if exp_char == raw_char:
            # 1. 완벽히 일치
            char_score = 100
            print(f"    -> Exact Match! Score: {char_score}")
          else:
            # 2. 글자는 다르지만 발음/성조 체크
            # e_p, e_t = exp_py[exp_idx]
            # r_p, r_t = raw_py[raw_idx]
            # print(f"    -> Char mismatch. Pinyin Check: '{e_p}{e_t}' vs '{r_p}{r_t}'")
            # 발음 및 성조 상세 비교
            e_p, e_t = exp_py[exp_idx] if exp_idx < len(exp_py) else ("", 5)
            r_p, r_t = raw_py[raw_idx] if raw_idx < len(raw_py) else ("", 5)
            
            if e_p == r_p:
              if e_t == r_t:
                # 글자 표기만 다르고(이체자 등) 발음/성조 동일
                char_score = 90
                print(f"    -> Pinyin & Tone Match (variant?)! Score: {char_score}")
              else:
                # 발음은 같은데 성조만 틀림
                char_score = 60
                tone_error = True
                print(f"    -> Pinyin Match, Tone Error ({e_t} vs {r_t}). Score: {char_score}")
            else:
              # 발음 자체가 다름
              char_score = 20
              print(f"-> Pinyin Mismatch! {e_p} vs {r_p} ({char_score})")
        elif exp_char:
          # 3. 누락됨
          char_score = 0
          print(f"  [Char {exp_idx}] '{exp_char}' -> Missing in transcription. Score: {char_score}")
        
        if exp_idx is not None:
          total_score += char_score
          word_details.append({
            "idx": exp_idx,
            "expected": exp_char,
            "actual": raw_char,
            "is_correct": (char_score >= 90),
            "tone_error": tone_error,
            "score": char_score
          })

    # 2. 최종 종합 점수 산출
    avg_score = int(total_score / char_count) if char_count > 0 else 0
    
    # 물리적 명확도(Acoustic Score) 반영
    clarity_score = self._calculate_clarity_score(expected, best_aligned_result.get("segments", []) if best_aligned_result else [])
    
    # 가중치 합산: 텍스트 일치(70%) + 발음 명확도(30%)
    final_score = int((avg_score * 0.7) + (clarity_score * 0.3))

    # 난이도 보정 (고난도일수록 성조 오류에 엄격함)
    if difficulty >= 4:
      # 고난도: 성조가 하나라도 틀리면 감점 대폭 강화
      tone_errors = sum(1 for d in word_details if d.get("tone_error"))
      if tone_errors > 0:
        final_score = min(final_score, 85 - (tone_errors * 5))

    # 3. 맞춤형 피드백 생성
    tone_error_chars = [d["expected"] for d in word_details if d.get("tone_error")]
    if final_score >= 90:
      feedback = "太棒了! 성조와 발음이 완벽합니다. 👍"
    elif tone_error_chars:
      feedback = f"발음은 좋지만 [{', '.join(tone_error_chars[:3])}] 등의 성조가 정확하지 않아요. 성조에 주의해서 다시 읽어보세요."
    elif final_score >= 60:
      feedback = "不错! 전반적으로 알아들을 수 있지만, 몇몇 글자가 누락되거나 틀렸습니다."
    else:
      feedback = "加油! 천천히 한 글자씩 또박또박 성조를 살려서 읽어보세요."

    print(f"📈 Match Score: {avg_score}, Clarity: {clarity_score} -> Final: {final_score}")
    print(f"------------------------------------------\n")

    return {
      "score": max(0, min(100, final_score)),
      "feedback": feedback,
      "recognized_text": raw_text,
      "word_details": word_details,
      "aligned_result": best_aligned_result
    }

  def _levenshtein_distance(self, s1, s2):
    """편집 거리(Levenshtein Distance) 알고리즘 - 음소/병음 비교용"""
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
    """발음의 물리적 명확도(Acoustic Confidence) 점수 계산"""
    total_score = 0
    char_count = 0
    for segment in aligned_segments:
      chars = segment.get("chars", [])
      for c in chars:
        total_score += c.get("score", 0)
        char_count += 1
    if char_count == 0:
      return 0
    return int((total_score / char_count) * 100)

  def _generate_candidate_feedback(self, expected: str, actual: str, score: int, clarity: int, feedback_map: dict = None) -> str:
    """선택된 후보 단어에 따른 맞춤형 한국어 피드백 생성"""
    if expected == actual:
      if clarity >= 90:
        return f"완벽합니다! (점수: {score}) 정확한 성조와 발음이에요. 👍"
      elif clarity >= 70:
        return f"정답입니다! (점수: {score}) 성조를 조금만 더 명확하게 발음해보세요."
      else:
        return f"단어는 맞았지만 발음이 다소 흐릿해요. (점수: {score}) 더 또박또박 발음해보세요!"
    
    specific_feedback = feedback_map.get(actual) if feedback_map else None
    if specific_feedback:
      return f"{specific_feedback} (점수: {score})"

    return f"👉 '{expected}'와 다르게 들려요. (인식: '{actual}', 점수: {score})"
