import re
import difflib
import logging
from pypinyin import pinyin, Style # type: ignore
from .base import BaseEvaluator

logger = logging.getLogger(__name__)

class ChineseEvaluator(BaseEvaluator):
  def evaluate(self, expected: str, candidates: list, raw_text: str = "", candidate_results: dict = None, difficulty: int = 3, mode: str = "word") -> dict:
    """
    중국어 평가 메인 진입점
    """
    if mode == "sentence":
      return self._evaluate_sentence(expected, raw_text, candidate_results, difficulty)
    else:
      return self._evaluate_word(expected, candidates, raw_text, candidate_results, difficulty)

  def _get_pinyin_tone(self, text: str):
    """
    한자를 병음과 성조 숫자로 분리하여 반환합니다.
    예: "你好" -> [("ni", 3), ("hao", 3)]
    """
    # Style.TONE3: 병음 뒤에 숫자가 붙는 형식 (ni3, hao3)
    py_list = pinyin(text, style=Style.TONE3, neutral_tone_with_five=True)
    results = []
    for item in py_list:
      token = item[0]
      # 숫자(성조) 분리
      match = re.match(r'([a-z]+)([1-5])', token.lower())
      if match:
        results.append((match.group(1), int(match.group(2))))
      else:
        # 성조가 없는 경우 (경성 등)
        results.append((token.lower(), 5))
    return results

  def _evaluate_sentence(self, expected: str, raw_text: str = "", candidate_results: dict = None, difficulty: int = 3) -> dict:
    """
    중국어 문장 평가 로직: 글자 단위 정렬 및 성조 분석
    """
    # 0. 전처리: 중국어 한자, 영문, 숫자만 남김
    expected_clean = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', expected)
    raw_clean = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', raw_text)
    
    print(f"\n--- [Chinese Sentence Evaluation: {expected}] ---")
    print(f"Raw transcription: '{raw_text}' -> Cleaned: '{raw_clean}'")

    # 1. 글자 단위 정렬 (Character-level alignment)
    matcher = difflib.SequenceMatcher(None, expected_clean, raw_clean)
    opcodes = matcher.get_opcodes()
    
    word_details = []
    total_score = 0
    char_count = len(expected_clean)
    
    # 병음 및 성조 정보 추출
    exp_py = self._get_pinyin_tone(expected_clean)
    raw_py = self._get_pinyin_tone(raw_clean)

    print(f"[Debug] Expected Pinyin: {exp_py}")
    print(f"[Debug] Raw Pinyin: {raw_py}")

    aligned_results = []
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
          print(f"  [Char {exp_idx if exp_idx is not None else '-'}] '{exp_char}' vs '{raw_char}'")
          if exp_char == raw_char:
            # 1. 완벽히 일치
            char_score = 100
            print(f"    -> Exact Match! Score: {char_score}")
          else:
            # 2. 글자는 다르지만 발음/성조 체크
            e_p, e_t = exp_py[exp_idx]
            r_p, r_t = raw_py[raw_idx]
            print(f"    -> Char mismatch. Pinyin Check: '{e_p}{e_t}' vs '{r_p}{r_t}'")
            
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
              print(f"    -> Pinyin Mismatch. Score: {char_score}")
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

    # 2. 최종 점수 계산
    final_score = int(total_score / char_count) if char_count > 0 else 0
    
    # 난이도 보정 (난이도가 높을수록 성조에 엄격함)
    if difficulty >= 4:
      # 고난도: 성조가 하나라도 틀리면 감점 대폭 강화
      tone_errors = sum(1 for d in word_details if d.get("tone_error"))
      if tone_errors > 0:
        final_score = min(final_score, 85 - (tone_errors * 5))

    # 3. 피드백 생성
    tone_error_chars = [d["expected"] for d in word_details if d.get("tone_error")]
    if final_score >= 90:
      feedback = "太棒了! 성조와 발음이 완벽합니다. 👍"
    elif tone_error_chars:
      feedback = f"발음은 좋지만 [{', '.join(tone_error_chars[:3])}] 등의 성조가 정확하지 않아요. 성조에 주의해서 다시 읽어보세요."
    elif final_score >= 60:
      feedback = "不错! 전반적으로 알아들을 수 있지만, 몇몇 글자가 누락되거나 틀렸습니다."
    else:
      feedback = "加油! 천천히 한 글자씩 또박또박 성조를 살려서 읽어보세요."

    print(f"📈 Match Score: {final_score}, Tone Errors: {len(tone_error_chars)}")
    print(f"------------------------------------------\n")

    return {
      "score": max(0, min(100, final_score)),
      "feedback": feedback,
      "recognized_text": raw_text,
      "word_details": word_details,
      "aligned_result": candidate_results.get(expected, {}).get("result") if candidate_results else None
    }

  def _evaluate_word(self, expected: str, candidates: list, raw_text: str = "", candidate_results: dict = None, difficulty: int = 3) -> dict:
    """
    중국어 단어 평가 로직 (후보군 매칭 + 성조 분석)
    """
    # 단어 평가도 문장 평가의 로직을 활용하되, 가장 유사한 후보를 선택하는 과정 추가
    # 현재는 단순 매칭 위주로 구현 (추후 영어처럼 복합 점수 도입 가능)
    
    best_candidate = expected
    best_res_data = None
    highest_score = -1

    # 후보군 중 가장 점수가 높은 것 선택
    for cand in candidates:
      res = self._evaluate_sentence(expected, cand, candidate_results, difficulty)
      if res["score"] > highest_score:
        highest_score = res["score"]
        best_candidate = cand
        best_res_data = res

    # 실제 Whisper가 들은 raw_text와 비교하여 최종 보정
    raw_res = self._evaluate_sentence(expected, raw_text, candidate_results, difficulty)
    if raw_res["score"] > highest_score:
      return raw_res
    
    return best_res_data if best_res_data else raw_res
