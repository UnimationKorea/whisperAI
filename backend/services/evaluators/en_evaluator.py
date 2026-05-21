import re
import difflib
import logging
from g2p_en import G2p  # type: ignore
from .base import BaseEvaluator

logger = logging.getLogger(__name__)

class EnglishEvaluator(BaseEvaluator):
  def __init__(self):
    self.g2p = G2p()

  def evaluate(self, expected: str, candidates: list, raw_text: str = "", candidate_results: dict = None, mode: str = "word") -> dict:
    """
    영어 평가 메인 진입점: 모드(단어/문장)에 따라 채점 로직을 분기합니다.
    """
    if mode == "sentence":
      return self._evaluate_sentence(expected, raw_text, candidate_results)
    else:
      return self._evaluate_word(expected, candidates, raw_text, candidate_results)

  def _evaluate_word(self, expected: str, candidates: list, raw_text: str = "", candidate_results: dict = None) -> dict:
    """
    [단어 채점 로직]
    영어 전용 평가 로직: 
    1. Whisper의 자유 인식 결과(raw_text)와 후보군 간의 '음소 거리' 계산
    2. 정렬 점수(Acoustic)와 음소 유사도(Phonetic)를 결합하여 최적의 단어 선택
    3. 선택된 단어로 최종 점수 및 피드백 산출
    """
    expected = expected.lower().strip()
    raw_text = raw_text.lower().strip()
    
    # 1. 최적의 후보(actual) 선택 (음소 편집 거리 보정 적용)
    best_candidate = expected
    highest_composite_score = -1
    best_aligned_result = None

    # raw_text의 음소 추출
    raw_phonemes = self.g2p(raw_text)
    # 문장 부호 및 공백 제거
    raw_phonemes = [p for p in raw_phonemes if re.match(r'\w+', p)]

    # 제시어(Target)의 음소 추출
    expected_phonemes = self.g2p(expected)
    expected_phonemes = [p for p in expected_phonemes if re.match(r'\w+', p)]

    print(f"\n--- [Word Evaluation: {expected}] ---")
    print(f"Target Phonemes: {expected_phonemes}")
    print(f"Initial raw transcription: '{raw_text}' -> Phonemes: {raw_phonemes}")
    print(f"--- [Phonetic Correction Selection (English)] ---")

    if not candidates:
      candidates = [expected]

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
      composite_score = (alignment_score * 0.6) + (phonetic_similarity * 0.4)
      
      # 제시어 우선권 부여: 음소 유사도가 최소한의 기준(0.2)을 넘을 때만 부여
      # 발음이 아예 다르면(예: cat vs oh) 가점을 주지 않아 오인식을 방지합니다.
      bonus_str = ""
      if cand == expected and phonetic_similarity > 0.2:
        composite_score += 0.1
        bonus_str = " [+0.1 Expected Bonus]"
      
      print(f"  - '{cand}' ({cand_phonemes}): Align({alignment_score:.3f}) + Phonetic({phonetic_similarity:.3f}) = Comp({composite_score:.3f}){bonus_str}")

      if composite_score > highest_composite_score:
        highest_composite_score = composite_score
        best_candidate = cand
        best_aligned_result = res.get("result")

    print(f"🏆 Selected Candidate: '{best_candidate}'")
    print(f"--------------------------------------------------\n")

    # 3. 임계값 체크: 너무 낮은 점수는 무시 (전혀 다른 단어로 간주)
    # 복합 점수가 0.55 미만이면 발음 유사도나 물리적 정렬 중 하나가 매우 낮다는 의미입니다.
    if highest_composite_score < 0.55:
      return {
        "score": 0,
        "recognized_text": raw_text,
        "error": { "code": "1302", "msg": "Different word detected" }, # 전혀 다른 단어를 말한 것으로 판단함 (Precondition Failed)
        "analysis_data": {
          "expected_phonemes": expected_phonemes,
          "recognized_phonemes": raw_phonemes, # raw_text(refined) 기반
          # "selected_phonemes": self.g2p(best_candidate),
          "char_analysis": [],
          "word_details": [{
            "idx": 0,
            "expected": expected,
            "actual": raw_text,
            "is_correct": False,
            "score": 0
          }],
          # "aligned_result": best_aligned_result
        },
      }

    # 4. 최종 선택된 단어로 명확도(Clarity) 및 점수 산출
    actual = best_candidate
    aligned_segments = best_aligned_result.get("segments", []) if best_aligned_result else []
    
    # 명확도 점수 및 상세 분석 정보 계산
    clarity_score, char_analysis = self._calculate_clarity_score(expected, aligned_segments)

    # 순위 기반 점수 산출
    score_gap = 15 # 오답 후보 선택 시 단계별 감점 고정
    try:
      index = candidates.index(actual)
      base_score = 100 - (index * score_gap)
    except ValueError:
      base_score = 0

    # 최종 점수 산출 (명확도 가중치 적용)
    clarity_threshold = 70 # 명확도 합격 커트라인 고정
    if base_score >= 100 - score_gap:
      # 정답 후보인 경우 (1순위 후보)
      if clarity_score < clarity_threshold:
        # 명확도가 낮으면 커트라인 비율대로 감점
        final_score = int(base_score * (clarity_score / clarity_threshold))
      else:
        # 커트라인 넘으면 기본 점수 유지
        final_score = base_score
    elif base_score > 0:
      # 오답 후보인 경우 (2순위 이하) 명확도 비율대로 적용
      final_score = int(base_score * (clarity_score / 100))
    else:
      # 후보군에 없는 경우
      final_score = 0

    # 최종 점수 보정 (92점 이상이면 100점으로 처리)
    if actual == expected and clarity_score >= 92:
      final_score = 100

    # 인식어(refined_raw_text)의 음소 추출
    recognized_phonemes = self.g2p(raw_text)
    recognized_phonemes = [p for p in recognized_phonemes if re.match(r'\w+', p)]
    
    # 선택된 후보 단어의 음소 추출
    selected_phonemes = self.g2p(actual)
    selected_phonemes = [p for p in selected_phonemes if re.match(r'\w+', p)]

    word_details = [{
      "idx": 0,
      "expected": expected,
      "actual": actual if actual != expected else expected,
      "is_correct": (actual == expected)
    }]

    return {
      "score": min(100, max(0, final_score)),
      "recognized_text": actual,
      "analysis_data": {
        "expected_phonemes": expected_phonemes,
        "recognized_phonemes": recognized_phonemes,
        "selected_phonemes": selected_phonemes,
        "char_analysis": char_analysis,
        # word_details와 aligned_result를 analysis_data 내부로 통합합니다.
        "word_details": word_details,
        "aligned_result": best_aligned_result
      }
    }

  def _evaluate_sentence(self, expected: str, raw_text: str = "", candidate_results: dict = None) -> dict:
    """
    [문장 채점 로직]
    문장 내 개별 단어들의 발음 정확도를 분석하여 종합 점수를 산출합니다.
    """
    # 0. 텍스트 클리닝: 모든 특수문자 제거 후 소문자 단어 리스트로 변환
    expected_clean = re.sub(r'[^a-zA-Z0-9\s]', '', expected).lower().strip()
    expected_words = expected_clean.split()
    
    # 문장 모드에서는 후보군이 없으므로 정답 문장 자체의 정렬 결과를 사용합니다.
    res = candidate_results.get(expected, {})
    best_aligned_result = res.get("result")
    aligned_segments = best_aligned_result.get("segments", []) if best_aligned_result else []

    print(f"\n--- [Sentence Evaluation: {expected}] ---")
    
    # 정답 문장의 음소 추출 및 출력
    expected_phonemes = self.g2p(expected_clean)
    expected_phonemes = [p for p in expected_phonemes if re.match(r'\w+', p)]
    print(f"Target Phonemes: {expected_phonemes}")
    print(f"Raw transcription: '{raw_text}'")

    word_scores = []
    missing_words = []
    word_analysis = [] # 분석 데이터 수집용 리스트 초기화
    
    # 정렬된 데이터에서 단어별 정보를 추출합니다.
    aligned_words = []
    for seg in aligned_segments:
      if "words" in seg:
        for w in seg["words"]:
          aligned_words.append(w)

    # 1. 단어별 일치 여부 및 신뢰도 분석
    total_clarity = 0
    matched_count = 0
    
    # 자유 전사 결과에서 단어 리스트 추출 (크로스 체크용, 특수문자 제거)
    raw_words = re.sub(r'[^a-zA-Z0-9\s]', '', raw_text).lower().split()
    
    print("Individual Word Analysis:")
    for i, target_w in enumerate(expected_words):
      # 해당 단어가 자유 전사 결과에 포함되어 있는지 확인 (존재 여부 1차 필터)
      is_in_raw = target_w in raw_words
      
      # 정렬 결과에서 가장 적절한 단어 찾기
      found_word = None
      for aw in aligned_words:
        # 정렬 데이터의 단어에서도 모든 특수문자 제거 후 비교
        clean_aw = re.sub(r'[^a-zA-Z0-9\s]', '', aw.get("word", "")).lower().strip()
        if clean_aw == target_w:
          found_word = aw
          aligned_words.remove(aw)
          break
      
      # [인식 판정 조건]
      # 1. 정렬 데이터가 존재하고 신뢰도가 0.5(50점) 이상인 경우
      # 2. 혹은 신뢰도는 낮지만 자유 전사 결과에 해당 단어가 명확히 포함된 경우
      score_val = found_word.get("score", 0) if found_word else 0
      
      # 1. 자유 전사에 단어가 있는 경우: 0.4점 이상이면 인정
      # 2. 자유 전사에 단어가 없는 경우: 정렬 점수가 아주 높아야 함 (0.8 이상)
      is_recognized = False
      if found_word:
        if is_in_raw and score_val >= 0.4:
          is_recognized = True
        elif not is_in_raw and score_val >= 0.8: # 매우 확실할 때만 인정
          is_recognized = True

      if is_recognized:
        word_score = int(score_val * 100)
        total_clarity += word_score
        matched_count += 1
        print(f"  - '{target_w}': {word_score} points")
      else:
        missing_words.append(target_w)
        # 로그 출력용 상태 상세화
        if not found_word:
          status = "Not found in audio"
        elif not is_in_raw:
          status = f"Different word detected in transcription (Alignment score: {int(score_val*100)})"
        else:
          status = f"Low confidence ({int(score_val*100)})"
        print(f"  - '{target_w}': ⚠️ Missing / {status}")
        word_score = 0
      
      # 분석 데이터용 정보 추가
      word_analysis.append({
        "target_w": target_w,
        "word_score": word_score
      })

    # 2. 문장 점수 산출
    # (인식된 단어 비율 * 0.4) + (인식된 단어들의 평균 명확도 * 0.6) - 고정 가중치 적용
    match_ratio = matched_count / len(expected_words)
    avg_clarity = (total_clarity / matched_count) if matched_count > 0 else 0
    
    match_weight = 0.4
    clarity_weight = 0.6
    
    final_score = int((match_ratio * 100 * match_weight) + (avg_clarity * clarity_weight))
    

    
    # 3. 피드백 생성
    if match_ratio == 1.0:
      if avg_clarity >= 90:
        feedback = "훌륭합니다! 문장 전체를 아주 명확하게 발음하셨네요. ✨"
      elif avg_clarity >= 70:
        feedback = "좋은 시도입니다! 전반적으로 이해하기 쉽지만, 몇몇 단어를 조금 더 또박또박 읽어보세요."
      else:
        feedback = "단어는 모두 인식되었지만, 전체적으로 발음이 조금 흐릿합니다. 천천히 다시 읽어볼까요?"
    else:
      missing_str = ", ".join(missing_words)
      feedback = f"문장 중 [{missing_str}] 부분이 잘 들리지 않았어요. 단어의 끝소리까지 명확하게 발음해 보세요."

    # 3. 단어별 상세 정보 생성 (프론트엔드 하이라이트용)
    word_details = []
    
    # difflib을 사용하여 정답 문장과 자유 전사 결과 간의 차이 분석
    # (i like dog vs i love my dog 비교 등)
    # [디버깅 로그]
    print(f"\n--- [DEBUG: Word Details Generation] ---")
    print(f"Expected Words: {expected_words}")
    print(f"Raw Words: {raw_words}")
    
    try:
      matcher = difflib.SequenceMatcher(None, expected_words, raw_words)
      opcodes = matcher.get_opcodes()
      print(f"Opcodes: {opcodes}")
      
      for tag, i1, i2, j1, j2 in opcodes:
        if tag == 'equal':
          for k in range(i2 - i1):
            word_details.append({
              "idx": i1 + k,
              "expected": expected_words[i1 + k],
              "actual": raw_words[j1 + k],
              "is_correct": True
            })
        elif tag == 'replace':
        # 교체된 경우 (예: love -> like)
        # 개수가 맞지 않을 수 있으므로 최대한 매칭
          for k in range(max(i2 - i1, j2 - j1)):
            exp_idx = i1 + k
            raw_idx = j1 + k
            if exp_idx < i2:
              word_details.append({
                "idx": exp_idx,
                "expected": expected_words[exp_idx],
                "actual": raw_words[raw_idx] if raw_idx < j2 else None,
                "is_correct": False
              })
        elif tag == 'delete':
        # 누락된 경우 (예: my 가 사라짐)
          for k in range(i2 - i1):
            word_details.append({
              "idx": i1 + k,
              "expected": expected_words[i1 + k],
              "actual": None,
              "is_correct": False
            })
    except Exception as e:
      print(f"❌ Error during difflib analysis: {e}")

    # [최종 보정] 만약 로직 버그로 word_details가 비어있다면 강제 생성
    if not word_details and expected_words:
      print("⚠️ Warning: word_details is empty! Fallback triggered.")
      for idx, word in enumerate(expected_words):
        word_details.append({
          "idx": idx,
          "expected": word,
          "actual": None,
          "is_correct": False
        })

    # 인덱스 순서대로 정렬 및 중복 제거
    word_details.sort(key=lambda x: x["idx"])
    
    print(f"📈 Match Ratio: {match_ratio:.2f}, Avg Clarity: {avg_clarity:.2f}")
    print(f"✅ Final Sentence Score: {final_score}")
    print(f"📄 Word Details: {word_details}")
    print("------------------------------------------\n")

    return {
      "score": min(100, max(0, final_score)),
      "recognized_text": raw_text, # 문장 모드에서는 Whisper가 들은 그대로를 보여줌
      "analysis_data": {
        "word_analysis": word_analysis,
        # word_details와 aligned_result를 analysis_data 내부로 통합합니다.
        "word_details": word_details,
        "aligned_result": best_aligned_result
      }
    }

  def _calculate_clarity_score(self, expected: str, aligned_segments: list):
    """철자별 신뢰도를 평균내어 발음의 명확도 점수 계산"""
    total_score = 0
    char_count = 0
    char_analysis = []
    
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
        char_analysis.append({"char": char_val, "score": char_score})
        print(f"  └ '{char_val}': {char_score:.4f}")
    
    if char_count == 0:
      print("⚠️ No character scores found.")
      return 0, []
      
    avg_score = total_score / char_count
    final_clarity = int(avg_score * 100)
    print(f"📊 Final Clarity: {final_clarity} (Average: {avg_score:.4f})")
    print("------------------------------------------\n")
    return final_clarity, char_analysis

