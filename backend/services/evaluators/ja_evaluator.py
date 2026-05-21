import re
import difflib
import logging
import pykakasi
from .base import BaseEvaluator

logger = logging.getLogger(__name__)

class JapaneseEvaluator(BaseEvaluator):
  def __init__(self):
    super().__init__()
    self.kks = pykakasi.kakasi()

  def _to_hiragana(self, text: str) -> str:
    """한자, 가타카나 등을 히라가나로 모두 변환합니다."""
    result = self.kks.convert(text)
    return "".join([item['hira'] for item in result])

  def _count_mora(self, kana_text: str) -> int:
    """
    Mora(박자) 수를 계산합니다.
    - 요음(ゃ, ゅ, ょ 등)은 단독 박자로 세지 않음
    - 촉음(っ), 장음(ー), 발음(ん)은 1박자로 계산
    """
    small_kana = set('ゃゅょャュョぁぃぅぇぉァィゥェォ')
    # 알파벳, 숫자, 띄어쓰기 등 불필요한 기호 제거 후 히라가나/가타카나/장음만 카운트
    clean_kana = re.sub(r'[^\wぁ-んァ-ンー]', '', kana_text) 
    
    count = 0
    for char in clean_kana:
        if char in small_kana:
            continue
        count += 1
    return count

  def evaluate(self, expected: str, candidates: list, raw_text: str = "", candidate_results: dict = None, mode: str = "word", feedback_map: dict = None) -> dict:
    if mode == "sentence":
      return self._evaluate_sentence(expected, raw_text, candidate_results)
    else:
      return self._evaluate_word(expected, candidates, raw_text, candidate_results)

  def _evaluate_word(self, expected: str, candidates: list, raw_text: str, candidate_results: dict) -> dict:
    print(f"\n--- [Japanese Word Evaluation: {expected}] ---")
    
    expected_kana = self._to_hiragana(expected)
    expected_mora = self._count_mora(expected_kana)
    print(f"Target Kana: '{expected_kana}' (Mora: {expected_mora})")

    best_candidate = expected
    highest_composite_score = -1
    best_aligned_result = None

    if not candidates:
      candidates = [expected]

    print(f"🔍 [Candidate Search & Mora Analysis]")
    for cand in candidates:
      res = candidate_results.get(cand, {})
      alignment_score = res.get("avg_score", 0)
      
      cand_kana = self._to_hiragana(cand)
      cand_mora = self._count_mora(cand_kana)
      
      # 발음 유사도 (히라가나 기준 편집 거리)
      similarity = difflib.SequenceMatcher(None, expected_kana, cand_kana).ratio()
      
      # 복합 점수 (음향 60% + 히라가나 유사도 40%)
      composite_score = (alignment_score * 0.6) + (similarity * 0.4)
      
      bonus_str = ""
      if cand == expected and similarity > 0.2:
        composite_score += 0.1
        bonus_str = " [+0.1 Expected Bonus]"
        
      print(f"  - '{cand}' ({cand_kana}, {cand_mora} mora): Align({alignment_score:.3f}) + Kana({similarity:.3f}) = Comp({composite_score:.3f}){bonus_str}")
      
      if composite_score > highest_composite_score:
        highest_composite_score = composite_score
        best_candidate = cand
        best_aligned_result = res.get("result")

    print(f"🏆 Final Selected Candidate: '{best_candidate}'")
    print(f"--------------------------------------------------\n")

    if highest_composite_score < 0.55:
      raw_hira = self._to_hiragana(raw_text)
      expected_res = candidate_results.get(expected, {}) if candidate_results else {}
      return {
        "score": 0,
        "recognized_text": raw_text,
        "error": { "code": "1302", "msg": "Different word detected" }, # 전혀 다른 단어를 말한 것으로 판단함 (Precondition Failed)
        "analysis_data": {
          "expected": {
            "kana": expected_kana,
            "mora": expected_mora,
            "align": expected_res.get("avg_score", 0)
          },
          "recognized": {
            "kana": raw_hira,
            "mora": self._count_mora(raw_hira),
            "align": 0
          },
          # word_details와 aligned_result를 analysis_data 내부로 통합합니다.
          "word_details": [{"idx": 0, "expected": expected, "actual": raw_text, "is_correct": False, "score": 0}]
        }
      }

    actual = best_candidate
    actual_kana = self._to_hiragana(actual)
    actual_mora = self._count_mora(actual_kana)

    # Whisper가 실제 인식한 원본 텍스트(raw_text) 정보 추출
    raw_hira = self._to_hiragana(raw_text)
    raw_mora = self._count_mora(raw_hira)
    raw_align = candidate_results.get(raw_text, {}).get("avg_score", 0) if (candidate_results and raw_text in candidate_results) else 0
    
    # 발음 명확도(Clarity)
    aligned_segments = best_aligned_result.get("segments", []) if best_aligned_result else []
    clarity_score = self._calculate_clarity_score(expected, aligned_segments)
    
    # 기본 점수 산출 (차등 감점 제거)
    if actual in candidates:
      base_score = 100
    else:
      base_score = 0
      
    # Mora(박자) 차이에 따른 추가 페널티
    mora_diff = abs(expected_mora - actual_mora)
    mora_penalty = mora_diff * 15 # 박자가 틀릴 때마다 15점 차감
    
    clarity_threshold = 60
    if actual == expected:
      if clarity_score < clarity_threshold:
        final_score = int(base_score * (clarity_score / clarity_threshold))
      else:
        final_score = base_score
        if clarity_score >= 92:
          final_score = 100
    else:
      final_score = int(base_score * (clarity_score / 100))
      
    final_score = max(0, final_score - mora_penalty)

    print(f"📈 Match Score: {base_score}, Clarity: {clarity_score}, Mora Penalty: -{mora_penalty} -> Final: {final_score}")

    return {
      "score": final_score,
      "recognized_text": actual,
      "analysis_data": {
        "expected": {
          "kana": expected_kana,
          "mora": expected_mora,
          "align": candidate_results.get(expected, {}).get("avg_score", 0) if candidate_results else 0
        },
        "recognized": {
          "kana": raw_hira,
          "mora": raw_mora,
          "align": raw_align
        },
        "selected": {
          "kana": actual_kana,
          "mora": actual_mora,
          "align": candidate_results.get(actual, {}).get("avg_score", 0) if candidate_results else 0
        },
        # word_details와 aligned_result를 analysis_data 내부로 통합합니다.
        "word_details": [{
          "idx": 0,
          "expected": expected,
          "actual": actual,
          "is_correct": (actual == expected),
          "score": final_score
        }],
        "aligned_result": best_aligned_result
      }
    }

  def _evaluate_sentence(self, expected: str, raw_text: str, candidate_results: dict) -> dict:
    print(f"\n--- [Japanese Sentence Evaluation: {expected}] ---")
    
    # 구두점 제거
    expected_clean = re.sub(r'[^\w\sぁ-んァ-ン一-龥ー]', '', expected)
    raw_clean = re.sub(r'[^\w\sぁ-んァ-ン一-龥ー]', '', raw_text)
    
    expected_kana = self._to_hiragana(expected_clean)
    raw_kana = self._to_hiragana(raw_clean)
    
    expected_mora = self._count_mora(expected_kana)
    raw_mora = self._count_mora(raw_kana)
    
    print(f"Target Kana: '{expected_kana}' (Mora: {expected_mora})")
    print(f"Raw Kana: '{raw_kana}' (Mora: {raw_mora})")

    res = candidate_results.get(expected, {})
    best_aligned_result = res.get("result")
    
    # 히라가나 기반 글자 단위 유사도 비교
    matcher = difflib.SequenceMatcher(None, expected_kana, raw_kana)
    opcodes = matcher.get_opcodes()
    
    word_details = []
    total_score = 0
    char_count = len(expected_kana)
    
    print(f"🔍 [Mora & Phonetic Level Analysis]")
    
    for tag, i1, i2, j1, j2 in opcodes:
      for k in range(max(i2 - i1, j2 - j1)):
        exp_idx = i1 + k if (i1 + k) < i2 else None
        raw_idx = j1 + k if (j1 + k) < j2 else None
        
        exp_char = expected_kana[exp_idx] if exp_idx is not None else None
        raw_char = raw_kana[raw_idx] if raw_idx is not None else None
        
        char_score = 0
        if exp_char and raw_char:
          print(f"  - [{exp_char}] vs [{raw_char}]", end=" ")
          if exp_char == raw_char:
            char_score = 100
            print(f"    -> Exact Match! Score: {char_score}")
          else:
            similarity = difflib.SequenceMatcher(None, exp_char, raw_char).ratio()
            if similarity >= 0.5:
              char_score = int(20 + (similarity * 40))
              print(f"    -> Kana Similar ({similarity:.2f}). Score: {char_score}")
            else:
              char_score = 20
              print(f"    -> Kana Mismatch. Score: {char_score}")
        elif exp_char:
          char_score = 0
          print(f"  [Char {exp_idx}] '{exp_char}' -> Missing. Score: {char_score}")
          
        if exp_idx is not None:
          total_score += char_score
          word_details.append({
            "idx": exp_idx,
            "expected": exp_char,
            "actual": raw_char,
            "is_correct": (char_score >= 90),
            "score": char_score
          })

    avg_score = int(total_score / char_count) if char_count > 0 else 0
    
    aligned_segments = best_aligned_result.get("segments", []) if best_aligned_result else []
    clarity_score = self._calculate_clarity_score(expected, aligned_segments)
    
    # 박자 리듬 페널티 (전체 문장의 모라 수 차이)
    mora_diff = abs(expected_mora - raw_mora)
    mora_penalty = mora_diff * 5 # 문장에서는 박자 차이당 5점 감점
    
    final_score = int((avg_score * 0.7) + (clarity_score * 0.3))
    final_score = max(0, final_score - mora_penalty)
    
    print(f"📈 Kana Match: {avg_score}, Clarity: {clarity_score}, Mora Penalty: -{mora_penalty} -> Final: {final_score}")
    print(f"------------------------------------------\n")
    
    return {
      "score": max(0, min(100, final_score)),
      "recognized_text": raw_text,
      "analysis_data": {
        "expected": {
          "kana": expected_kana,
          "mora": expected_mora,
          "align": res.get("avg_score", 0) if res else 0
        },
        "recognized": {
          "kana": raw_kana,
          "mora": raw_mora,
          "align": 0
        },
        # word_details와 aligned_result를 analysis_data 내부로 통합합니다.
        "word_details": word_details,
        "aligned_result": best_aligned_result
      }
    }
