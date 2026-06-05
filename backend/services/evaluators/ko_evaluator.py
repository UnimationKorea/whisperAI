import re
import difflib
import logging
from .base import BaseEvaluator

logger = logging.getLogger(__name__)


class KoreanEvaluator(BaseEvaluator):
  """
  한국어 발음 평가 엔진.

  평가 파이프라인:
    1. 텍스트 -> G2P (발음 변환): "같이" -> "가치", "국밥" -> "국빱"
    2. 자모 분해 (초성/중성/종성): "강" -> ㄱ + ㅏ + ㅇ
    3. 실제 발음 비교 (자모 단위 일치율)
    4. 발음 규칙 기반 평가 (연음, 비음화, 경음화, 격음화, 구개음화, ㄴ첨가 등)

  사용 라이브러리:
    - g2pk2: 한국어 G2P (Grapheme-to-Phoneme) 변환 (Python 3.10+ 호환, kiwipiepy 우회 적용)
    - jamo: 한국어 자모 분해/결합 (초성/중성/종성)
  """

  def __init__(self):
    super().__init__()
    logger.info("[Wait] [KoreanEvaluator] G2P 모델 초기화 중...")

    # g2pk2: 한국어 텍스트를 표준 발음으로 변환하는 G2P 엔진
    from g2pk2 import G2p as G2pKo
    self.g2p = G2pKo()

    # jamo: 한글 자모 분해/결합 라이브러리
    import jamo as jamo_lib
    self.jamo = jamo_lib

    logger.info("[OK] [KoreanEvaluator] G2P 모델 초기화 완료")

    # ──────────────────────────────────────────────────────────
    # 한국어 발음 규칙 정의
    # 각 규칙은 (이름, 설명, 예시) 형태로 관리합니다.
    # ──────────────────────────────────────────────────────────
    self.pronunciation_rules = {
      "연음": {
        "description": "받침이 뒤 음절 초성으로 이동",
        "examples": ["읽어 -> 일거", "넣어 -> 너어", "옷이 -> 오시"]
      },
      "비음화": {
        "description": "ㄱ/ㄷ/ㅂ -> ㅇ/ㄴ/ㅁ (비음 앞에서)",
        "examples": ["국물 -> 궁물", "한국말 -> 한궁말", "십만 -> 심만"]
      },
      "경음화": {
        "description": "받침 뒤 평음 -> 된소리",
        "examples": ["학교 -> 학꾜", "국밥 -> 국빱", "입구 -> 입꾸"]
      },
      "격음화": {
        "description": "ㅎ + ㄱ/ㄷ/ㅂ/ㅈ -> ㅋ/ㅌ/ㅍ/ㅊ",
        "examples": ["놓다 -> 노타", "좋고 -> 조코", "넣지 -> 너치"]
      },
      "구개음화": {
        "description": "ㄷ/ㅌ + 이 -> ㅈ/ㅊ + 이",
        "examples": ["같이 -> 가치", "굳이 -> 구지", "해돋이 -> 해도지"]
      },
      "ㄴ첨가": {
        "description": "합성어 경계에서 ㄴ 추가",
        "examples": ["색연필 -> 생년필", "한여름 -> 한녀름"]
      },
      "유음화": {
        "description": "ㄴ + ㄹ 또는 ㄹ + ㄴ -> ㄹㄹ",
        "examples": ["신라 -> 실라", "관리 -> 괄리"]
      },
    }

    # ──────────────────────────────────────────────────────────
    # 자모 테이블 (초성/중성/종성 분류용)
    # ──────────────────────────────────────────────────────────
    self.ONSETS = [
      "ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ",
      "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"
    ]
    self.NUCLEI = [
      "ㅏ", "ㅐ", "ㅑ", "ㅒ", "ㅓ", "ㅔ", "ㅕ", "ㅖ", "ㅗ", "ㅘ",
      "ㅙ", "ㅚ", "ㅛ", "ㅜ", "ㅝ", "ㅞ", "ㅟ", "ㅠ", "ㅡ", "ㅢ", "ㅣ"
    ]
    self.CODAS = [
      "", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ",
      "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ",
      "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"
    ]

    # 된소리(경음) 매핑: 평음 -> 경음
    self.FORTIS_MAP = {
      "ㄱ": "ㄲ", "ㄷ": "ㄸ", "ㅂ": "ㅃ", "ㅅ": "ㅆ", "ㅈ": "ㅉ"
    }

    # 격음 매핑: ㅎ과 결합 시
    self.ASPIRATE_MAP = {
      "ㄱ": "ㅋ", "ㄷ": "ㅌ", "ㅂ": "ㅍ", "ㅈ": "ㅊ"
    }

    # 비음 매핑: 장애음 -> 비음
    self.NASAL_MAP = {
      "ㄱ": "ㅇ", "ㄲ": "ㅇ", "ㅋ": "ㅇ",
      "ㄷ": "ㄴ", "ㅌ": "ㄴ", "ㅅ": "ㄴ", "ㅆ": "ㄴ", "ㅈ": "ㄴ", "ㅊ": "ㄴ",
      "ㅂ": "ㅁ", "ㅍ": "ㅁ",
    }

  # ──────────────────────────────────────────────────────────
  # 발음 변환 (G2P) 메서드
  # ──────────────────────────────────────────────────────────

  def _text_to_pronunciation(self, text: str) -> str:
    """
    G2P를 사용하여 한국어 텍스트를 표준 발음 표기로 변환합니다.
    예: "같이" -> "가치", "학교" -> "학꾜", "국밥" -> "국빱"
    """
    if not text:
      return ""
    try:
      pronunciation = self.g2p(text)
      logger.info(f"  [G2P] '{text}' -> '{pronunciation}'")
      return pronunciation
    except Exception as e:
      logger.warning(f"  [G2P] 변환 실패: {text} -> {e}")
      return text

  # ──────────────────────────────────────────────────────────
  # 자모 분해 메서드
  # ──────────────────────────────────────────────────────────

  def _decompose_jamo(self, text: str) -> list:
    """
    한글 텍스트를 자모 단위로 분해합니다.
    각 음절을 (초성, 중성, 종성) 튜플의 리스트로 반환합니다.
    예: "강" -> [("ㄱ", "ㅏ", "ㅇ")]
        "학교" -> [("ㅎ", "ㅏ", "ㄱ"), ("ㄱ", "ㅛ", "")]
    """
    result = []
    for char in text:
      if self._is_hangul(char):
        # 유니코드 한글 분해 공식
        code = ord(char) - 0xAC00
        onset_idx = code // (21 * 28)
        nucleus_idx = (code % (21 * 28)) // 28
        coda_idx = code % 28

        onset = self.ONSETS[onset_idx]
        nucleus = self.NUCLEI[nucleus_idx]
        coda = self.CODAS[coda_idx]

        result.append((onset, nucleus, coda))
        logger.debug(f"  [자모 분해] '{char}' -> ({onset}, {nucleus}, {coda})")
      else:
        # 한글이 아닌 문자는 그대로 보관 (공백, 구두점 등)
        result.append((char, "", ""))
    return result

  def _decompose_to_flat_jamo(self, text: str) -> list:
    """
    한글 텍스트를 평탄화된(flat) 자모 리스트로 변환합니다.
    비교 알고리즘에 사용됩니다.
    예: "강" -> ["ㄱ", "ㅏ", "ㅇ"]
    """
    jamo_list = []
    for onset, nucleus, coda in self._decompose_jamo(text):
      if onset:
        jamo_list.append(onset)
      if nucleus:
        jamo_list.append(nucleus)
      if coda:
        jamo_list.append(coda)
    return jamo_list

  def _is_hangul(self, char: str) -> bool:
    """주어진 문자가 한글 음절 범위(가~힣)에 있는지 확인합니다."""
    return "\uAC00" <= char <= "\uD7A3"

  # ──────────────────────────────────────────────────────────
  # 자모 비교 메서드
  # ──────────────────────────────────────────────────────────

  def _compare_jamo_syllables(self, expected_jamo: list, actual_jamo: list) -> dict:
    """
    음절 단위로 자모를 비교하여 초성/중성/종성 각각의 일치율을 계산합니다.
    expected_jamo: 기대 발음의 자모 분해 결과 [(초,중,종), ...]
    actual_jamo:   인식된 발음의 자모 분해 결과 [(초,중,종), ...]

    반환:
      {
        "onset_match": float,   # 초성 일치율 (0.0~1.0)
        "nucleus_match": float, # 중성 일치율 (0.0~1.0)
        "coda_match": float,    # 종성 일치율 (0.0~1.0)
        "total_match": float,   # 전체 일치율 (0.0~1.0)
        "details": [...]        # 음절별 비교 상세
      }
    """
    details = []
    onset_match_count = 0
    nucleus_match_count = 0
    coda_match_count = 0

    # 음절 수가 다를 수 있으므로 SequenceMatcher로 정렬
    matcher = difflib.SequenceMatcher(None,
      [s[0] + s[1] + s[2] for s in expected_jamo],
      [s[0] + s[1] + s[2] for s in actual_jamo]
    )

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
      if tag == "equal":
        for k in range(i2 - i1):
          exp = expected_jamo[i1 + k]
          act = actual_jamo[j1 + k]
          onset_ok = (exp[0] == act[0])
          nucleus_ok = (exp[1] == act[1])
          coda_ok = (exp[2] == act[2])
          if onset_ok:
            onset_match_count += 1
          if nucleus_ok:
            nucleus_match_count += 1
          if coda_ok:
            coda_match_count += 1
          details.append({
            "expected": exp, "actual": act,
            "onset_match": onset_ok, "nucleus_match": nucleus_ok, "coda_match": coda_ok
          })
      elif tag == "replace":
        for k in range(max(i2 - i1, j2 - j1)):
          exp_idx = i1 + k
          act_idx = j1 + k
          exp = expected_jamo[exp_idx] if exp_idx < i2 else ("", "", "")
          act = actual_jamo[act_idx] if act_idx < j2 else ("", "", "")
          onset_ok = (exp[0] == act[0]) if (exp[0] and act[0]) else False
          nucleus_ok = (exp[1] == act[1]) if (exp[1] and act[1]) else False
          coda_ok = (exp[2] == act[2]) if (exp[2] and act[2]) else False
          if onset_ok:
            onset_match_count += 1
          if nucleus_ok:
            nucleus_match_count += 1
          if coda_ok:
            coda_match_count += 1
          details.append({
            "expected": exp, "actual": act,
            "onset_match": onset_ok, "nucleus_match": nucleus_ok, "coda_match": coda_ok
          })
      elif tag == "delete":
        for k in range(i2 - i1):
          exp = expected_jamo[i1 + k]
          details.append({
            "expected": exp, "actual": ("", "", ""),
            "onset_match": False, "nucleus_match": False, "coda_match": False
          })

    exp_count = len(expected_jamo) if expected_jamo else 1
    onset_rate = onset_match_count / exp_count
    nucleus_rate = nucleus_match_count / exp_count
    coda_rate = coda_match_count / exp_count
    total_rate = (onset_rate + nucleus_rate + coda_rate) / 3.0

    return {
      "onset_match": round(onset_rate, 4),
      "nucleus_match": round(nucleus_rate, 4),
      "coda_match": round(coda_rate, 4),
      "total_match": round(total_rate, 4),
      "details": details
    }

  def _compare_flat_jamo(self, expected_text: str, actual_text: str) -> float:
    """
    두 텍스트의 평탄화 자모 리스트 간 유사도를 계산합니다.
    difflib.SequenceMatcher를 사용하여 LCS 기반 비율을 구합니다.
    """
    exp_jamo = self._decompose_to_flat_jamo(expected_text)
    act_jamo = self._decompose_to_flat_jamo(actual_text)
    if not exp_jamo and not act_jamo:
      return 1.0
    if not exp_jamo or not act_jamo:
      return 0.0
    return difflib.SequenceMatcher(None, exp_jamo, act_jamo).ratio()

  # ──────────────────────────────────────────────────────────
  # 발음 규칙 감지 메서드
  # ──────────────────────────────────────────────────────────

  def _detect_pronunciation_rules(self, original: str, pronunciation: str) -> list:
    """
    원문(original)과 G2P 변환 결과(pronunciation)를 비교하여
    적용된 발음 규칙을 감지합니다.

    반환: [{"rule": "경음화", "position": 1, "original": "교", "changed": "꾜"}, ...]
    """
    detected_rules = []
    orig_jamo = self._decompose_jamo(original)
    pron_jamo = self._decompose_jamo(pronunciation)

    logger.info(f"  [규칙 감지] 원문 자모: {orig_jamo}")
    logger.info(f"  [규칙 감지] 발음 자모: {pron_jamo}")

    # 음절 수가 같은 경우에만 정밀 비교 (음절 수가 다르면 복잡한 변환이 발생한 것)
    if len(orig_jamo) == len(pron_jamo):
      for i in range(len(orig_jamo)):
        o_onset, o_nuc, o_coda = orig_jamo[i]
        p_onset, p_nuc, p_coda = pron_jamo[i]

        # 한글 이외 문자는 건너뜀
        if not self._is_hangul(original[i]) if i < len(original) else True:
          continue

        # ── 경음화 감지: 평음이 된소리로 변한 경우 ──
        if o_onset != p_onset and p_onset in self.FORTIS_MAP.values():
          if o_onset in self.FORTIS_MAP and self.FORTIS_MAP[o_onset] == p_onset:
            detected_rules.append({
              "rule": "경음화",
              "position": i,
              "original": original[i] if i < len(original) else "",
              "changed": pronunciation[i] if i < len(pronunciation) else "",
              "detail": f"초성 {o_onset} -> {p_onset}"
            })
            logger.info(f"    -> 경음화 감지: 위치 {i}, {o_onset} -> {p_onset}")

        # ── 격음화 감지: ㄱ->ㅋ, ㄷ->ㅌ 등 ──
        if o_onset != p_onset and p_onset in self.ASPIRATE_MAP.values():
          if o_onset in self.ASPIRATE_MAP and self.ASPIRATE_MAP[o_onset] == p_onset:
            detected_rules.append({
              "rule": "격음화",
              "position": i,
              "original": original[i] if i < len(original) else "",
              "changed": pronunciation[i] if i < len(pronunciation) else "",
              "detail": f"초성 {o_onset} -> {p_onset}"
            })
            logger.info(f"    -> 격음화 감지: 위치 {i}, {o_onset} -> {p_onset}")

        # ── 비음화 감지: 종성 장애음 -> 비음 ──
        if o_coda != p_coda and o_coda in self.NASAL_MAP:
          if self.NASAL_MAP[o_coda] == p_coda:
            detected_rules.append({
              "rule": "비음화",
              "position": i,
              "original": original[i] if i < len(original) else "",
              "changed": pronunciation[i] if i < len(pronunciation) else "",
              "detail": f"종성 {o_coda} -> {p_coda}"
            })
            logger.info(f"    -> 비음화 감지: 위치 {i}, 종성 {o_coda} -> {p_coda}")

        # ── 구개음화 감지: ㄷ/ㅌ + 이 -> ㅈ/ㅊ ──
        if o_onset in ("ㄷ", "ㅌ") and p_onset in ("ㅈ", "ㅊ"):
          detected_rules.append({
            "rule": "구개음화",
            "position": i,
            "original": original[i] if i < len(original) else "",
            "changed": pronunciation[i] if i < len(pronunciation) else "",
            "detail": f"초성 {o_onset} -> {p_onset}"
          })
          logger.info(f"    -> 구개음화 감지: 위치 {i}, {o_onset} -> {p_onset}")

        # ── 연음 감지: 종성이 사라지고 다음 음절 초성으로 이동 ──
        if o_coda and not p_coda and i + 1 < len(pron_jamo):
          next_p_onset = pron_jamo[i + 1][0]
          next_o_onset = orig_jamo[i + 1][0] if i + 1 < len(orig_jamo) else ""
          if next_o_onset == "ㅇ" and next_p_onset != "ㅇ":
            detected_rules.append({
              "rule": "연음",
              "position": i,
              "original": original[i] if i < len(original) else "",
              "changed": pronunciation[i] if i < len(pronunciation) else "",
              "detail": f"종성 {o_coda} -> 다음 음절 초성 {next_p_onset}"
            })
            logger.info(f"    -> 연음 감지: 위치 {i}, 종성 {o_coda} -> 다음 초성 {next_p_onset}")

        # ── 유음화 감지: ㄴ -> ㄹ (ㄹ 인접) ──
        if o_coda == "ㄴ" and p_coda == "ㄹ":
          detected_rules.append({
            "rule": "유음화",
            "position": i,
            "original": original[i] if i < len(original) else "",
            "changed": pronunciation[i] if i < len(pronunciation) else "",
            "detail": f"종성 ㄴ -> ㄹ"
          })
          logger.info(f"    -> 유음화 감지: 위치 {i}, 종성 ㄴ -> ㄹ")
        if o_onset == "ㄴ" and p_onset == "ㄹ":
          detected_rules.append({
            "rule": "유음화",
            "position": i,
            "original": original[i] if i < len(original) else "",
            "changed": pronunciation[i] if i < len(pronunciation) else "",
            "detail": f"초성 ㄴ -> ㄹ"
          })
          logger.info(f"    -> 유음화 감지: 위치 {i}, 초성 ㄴ -> ㄹ")

    if not detected_rules:
      logger.info("    -> 감지된 발음 규칙 없음")

    return detected_rules

  # ──────────────────────────────────────────────────────────
  # 평가 메인 진입점
  # ──────────────────────────────────────────────────────────

  def evaluate(self, expected: str, candidates: list, raw_text: str = "",
               candidate_results: dict = None, mode: str = "word", audio_np=None) -> dict:
    """
    한국어 평가 메인 진입점: 모드(단어/문장)에 따라 채점 로직을 분기합니다.
    """
    logger.info(f"[KoreanEvaluator] 평가 시작 - 모드: {mode}, 제시어: '{expected}'")

    if mode == "sentence":
      return self._evaluate_sentence(expected, raw_text, candidate_results)
    else:
      return self._evaluate_word(expected, candidates, raw_text, candidate_results)

  # ──────────────────────────────────────────────────────────
  # 단어 평가 (Word Mode)
  # ──────────────────────────────────────────────────────────

  def _evaluate_word(self, expected: str, candidates: list, raw_text: str = "",
                      candidate_results: dict = None) -> dict:
    """
    [단어 채점 로직]
    한국어 단어 발음 평가:
      1. G2P로 제시어와 후보군의 표준 발음을 구합니다.
      2. 자모 분해 후 유사도를 비교하여 최적 후보를 선택합니다.
      3. 발음 규칙 감지 및 점수를 산출합니다.
    """
    expected = expected.strip()
    raw_text = raw_text.strip()

    logger.info(f"[단어 평가] 제시어: '{expected}', 인식 텍스트: '{raw_text}'")

    # 1. G2P 변환: 제시어의 표준 발음 구하기
    expected_pron = self._text_to_pronunciation(expected)
    raw_pron = self._text_to_pronunciation(raw_text) if raw_text else ""

    # 자모 분해
    expected_jamo = self._decompose_jamo(expected_pron)
    raw_jamo = self._decompose_jamo(raw_pron) if raw_pron else []

    logger.info(f"  제시어 발음: '{expected_pron}', 자모: {expected_jamo}")
    logger.info(f"  인식 발음: '{raw_pron}', 자모: {raw_jamo}")

    # 2. 후보군 탐색: 각 후보의 복합 점수를 계산하여 최적 후보 선택
    best_candidate = expected
    highest_composite_score = -1
    best_aligned_result = None

    if not candidates:
      candidates = [expected]

    logger.info(f"  후보군 탐색 시작 (총 {len(candidates)}개)")

    for cand in candidates:
      res = candidate_results.get(cand, {}) if candidate_results else {}
      alignment_score = res.get("avg_score", 0)

      # 후보 단어의 G2P 발음 변환 및 자모 유사도 계산
      cand_pron = self._text_to_pronunciation(cand)
      jamo_similarity = self._compare_flat_jamo(raw_pron, cand_pron)

      # 복합 점수 산출 (음향 60% + 자모 유사도 40%)
      composite_score = (alignment_score * 0.6) + (jamo_similarity * 0.4)

      # 제시어 우선권 부여 (자모 유사도가 최소 기준(0.2)을 넘을 때만)
      bonus_str = ""
      if cand == expected and jamo_similarity > 0.2:
        composite_score += 0.1
        bonus_str = " [+0.1 Expected Bonus]"

      logger.info(f"    후보 '{cand}' -> 발음 '{cand_pron}': Align={alignment_score:.3f}, Jamo={jamo_similarity:.3f}, Comp={composite_score:.3f}{bonus_str}")

      if composite_score > highest_composite_score:
        highest_composite_score = composite_score
        best_candidate = cand
        best_aligned_result = res.get("result")

    logger.info(f"  [Winner] 최종 선택 후보: '{best_candidate}' (복합 점수: {highest_composite_score:.3f})")

    # 3. 임계값 체크: 복합 점수가 너무 낮으면 전혀 다른 단어로 판단
    if highest_composite_score < 0.55:
      logger.info(f"  [Warning] 임계값 미달 ({highest_composite_score:.3f} < 0.55) -> 다른 단어로 판단")
      return {
        "score": 0,
        "recognized_text": raw_text,
        "error": {"code": "1302", "msg": "Different word detected"},
        "analysis_data": {
          "expected": {
            "text": expected,
            "pronunciation": expected_pron,
            "jamo": [list(j) for j in expected_jamo]
          },
          "recognized": {
            "text": raw_text,
            "pronunciation": raw_pron,
            "jamo": [list(j) for j in raw_jamo]
          },
          "word_details": [{
            "idx": 0,
            "expected": expected,
            "recognized": raw_text,
            "is_correct": False,
            "score": 0
          }]
        }
      }

    # 4. 최종 선택된 후보로 상세 점수 산출
    actual = best_candidate
    actual_pron = self._text_to_pronunciation(actual)
    actual_jamo = self._decompose_jamo(actual_pron)

    # G2P 기준 자모 비교 (기대 발음 vs 선택된 후보의 발음)
    jamo_comparison = self._compare_jamo_syllables(
      self._decompose_jamo(expected_pron),
      self._decompose_jamo(actual_pron)
    )

    # 발음 규칙 감지
    detected_rules = self._detect_pronunciation_rules(expected, expected_pron)

    # 발음 명확도 (Acoustic Clarity)
    aligned_segments = best_aligned_result.get("segments", []) if best_aligned_result else []
    clarity_score = self._calculate_clarity_score(expected, aligned_segments)

    logger.info(f"  자모 일치율: {jamo_comparison['total_match']:.4f}")
    logger.info(f"  발음 명확도: {clarity_score}")
    logger.info(f"  감지된 규칙: {[r['rule'] for r in detected_rules]}")

    # 점수 산출
    # 정답이면 기본 100점, 오답 후보면 자모 일치율 기반
    if actual == expected:
      base_score = 100
    elif actual in candidates:
      # 후보군에 있는 오답: 자모 유사도 기반 부분 점수
      jamo_sim = self._compare_flat_jamo(expected_pron, actual_pron)
      base_score = int(jamo_sim * 100)
    else:
      base_score = 0

    # 명확도 보정
    clarity_threshold = 65
    if actual == expected:
      if clarity_score < clarity_threshold:
        final_score = int(base_score * (clarity_score / clarity_threshold))
      else:
        final_score = base_score
        if clarity_score >= 92:
          final_score = 100
    elif actual in candidates:
      final_score = int(base_score * (clarity_score / 100))
    else:
      final_score = 0

    final_score = max(0, min(100, final_score))

    logger.info(f"  [Score] 기본 점수: {base_score}, 명확도: {clarity_score} -> 최종: {final_score}")

    # 음절별 상세 분석 데이터 구성
    word_details = []
    exp_pron_jamo = self._decompose_jamo(expected_pron)
    act_pron_jamo = self._decompose_jamo(actual_pron)
    for i in range(max(len(exp_pron_jamo), len(act_pron_jamo))):
      exp_syl = exp_pron_jamo[i] if i < len(exp_pron_jamo) else ("", "", "")
      act_syl = act_pron_jamo[i] if i < len(act_pron_jamo) else ("", "", "")
      exp_char = expected[i] if i < len(expected) else ""
      act_char = actual[i] if i < len(actual) else ""

      syl_match = {
        "onset": exp_syl[0] == act_syl[0],
        "nucleus": exp_syl[1] == act_syl[1],
        "coda": exp_syl[2] == act_syl[2],
      }
      is_correct = all(syl_match.values())

      # 이 음절에 적용된 발음 규칙 찾기
      applied_rule = ""
      for rule in detected_rules:
        if rule["position"] == i:
          applied_rule = rule["rule"]
          break

      word_details.append({
        "idx": i,
        "expected": exp_char,
        "recognized": act_char,
        "jamo_match": syl_match,
        "pronunciation_rule": applied_rule,
        "is_correct": is_correct,
        "score": 100 if is_correct else 0
      })

    return {
      "score": final_score,
      "recognized_text": actual,
      "analysis_data": {
        "expected": {
          "text": expected,
          "pronunciation": expected_pron,
          "jamo": [list(j) for j in expected_jamo]
        },
        "recognized": {
          "text": raw_text,
          "pronunciation": raw_pron,
          "jamo": [list(j) for j in raw_jamo]
        },
        "selected": {
          "text": actual,
          "pronunciation": actual_pron,
          "jamo": [list(j) for j in actual_jamo]
        },
        "jamo_comparison": jamo_comparison,
        "detected_rules": detected_rules,
        "word_details": word_details,
        "aligned_result": best_aligned_result,
        "clarity_score": clarity_score,
      }
    }

  # ──────────────────────────────────────────────────────────
  # 문장 평가 (Sentence Mode)
  # ──────────────────────────────────────────────────────────

  def _evaluate_sentence(self, expected: str, raw_text: str = "",
                          candidate_results: dict = None) -> dict:
    """
    [문장 채점 로직]
    한국어 문장 발음 평가:
      1. G2P로 정답 문장과 인식 결과의 표준 발음을 구합니다.
      2. 음절 단위 자모 비교를 수행합니다.
      3. 발음 규칙 감지 및 종합 점수를 산출합니다.
    """
    logger.info(f"[문장 평가] 제시어: '{expected}', 인식 텍스트: '{raw_text}'")

    # 1. 전처리: 구두점/특수문자 제거
    expected_clean = re.sub(r"[^\w\s가-힣]", "", expected).strip()
    raw_clean = re.sub(r"[^\w\s가-힣]", "", raw_text).strip()

    # 2. G2P 변환
    expected_pron = self._text_to_pronunciation(expected_clean)
    raw_pron = self._text_to_pronunciation(raw_clean) if raw_clean else ""

    # 자모 분해
    expected_jamo = self._decompose_jamo(expected_pron)
    raw_jamo_list = self._decompose_jamo(raw_pron) if raw_pron else []

    logger.info(f"  정답 발음: '{expected_pron}'")
    logger.info(f"  인식 발음: '{raw_pron}'")

    # 정답 문장의 정렬 결과 로드
    res = candidate_results.get(expected, {}) if candidate_results else {}
    best_aligned_result = res.get("result")

    # 3. 한글 음절만 추출하여 비교 (공백 등 제거)
    expected_syllables = [c for c in expected_pron if self._is_hangul(c)]
    raw_syllables = [c for c in raw_pron if self._is_hangul(c)]

    expected_syl_jamo = self._decompose_jamo("".join(expected_syllables))
    raw_syl_jamo = self._decompose_jamo("".join(raw_syllables))

    # 4. 음절 단위 비교 (difflib.SequenceMatcher)
    matcher = difflib.SequenceMatcher(None, expected_syllables, raw_syllables)
    opcodes = matcher.get_opcodes()

    word_details = []
    total_score = 0
    char_count = len(expected_syllables) if expected_syllables else 1

    logger.info(f"  음절 수: 정답 {len(expected_syllables)}, 인식 {len(raw_syllables)}")

    for tag, i1, i2, j1, j2 in opcodes:
      for k in range(max(i2 - i1, j2 - j1)):
        exp_idx = i1 + k if (i1 + k) < i2 else None
        raw_idx = j1 + k if (j1 + k) < j2 else None

        exp_char = expected_syllables[exp_idx] if exp_idx is not None else None
        raw_char = raw_syllables[raw_idx] if raw_idx is not None else None

        char_score = 0

        if exp_char and raw_char:
          exp_j = self._decompose_jamo(exp_char)
          raw_j = self._decompose_jamo(raw_char)

          if exp_j and raw_j:
            ej = exp_j[0]
            rj = raw_j[0]
            onset_ok = (ej[0] == rj[0])
            nucleus_ok = (ej[1] == rj[1])
            coda_ok = (ej[2] == rj[2])
            match_count = sum([onset_ok, nucleus_ok, coda_ok])

            if match_count == 3:
              char_score = 100
            elif match_count == 2:
              char_score = 60
            elif match_count == 1:
              char_score = 25
            else:
              char_score = 0

            jamo_detail = {
              "onset": onset_ok,
              "nucleus": nucleus_ok,
              "coda": coda_ok
            }
          else:
            jamo_detail = {"onset": False, "nucleus": False, "coda": False}

          logger.info(f"    [{exp_char}] vs [{raw_char}]: 자모일치={jamo_detail}, 점수={char_score}")
        elif exp_char:
          char_score = 0
          jamo_detail = {"onset": False, "nucleus": False, "coda": False}
          logger.info(f"    [{exp_char}] -> 누락, 점수=0")
        else:
          continue  # 삽입된 글자는 무시

        if exp_idx is not None:
          total_score += char_score
          word_details.append({
            "idx": exp_idx,
            "expected": exp_char,
            "recognized": raw_char,
            "jamo_match": jamo_detail if exp_char else {},
            "is_correct": (char_score >= 90),
            "score": char_score
          })

    # 5. 종합 점수 산출
    avg_jamo_score = int(total_score / char_count) if char_count > 0 else 0

    # 발음 명확도 (Acoustic Clarity)
    aligned_segments = best_aligned_result.get("segments", []) if best_aligned_result else []
    clarity_score = self._calculate_clarity_score(expected, aligned_segments)

    # 발음 규칙 감지
    detected_rules = self._detect_pronunciation_rules(expected_clean, expected_pron)

    # 가중치 합산: 자모 일치(70%) + 발음 명확도(30%)
    final_score = int((avg_jamo_score * 0.7) + (clarity_score * 0.3))
    final_score = max(0, min(100, final_score))

    logger.info(f"  [Score] 자모 일치: {avg_jamo_score}, 명확도: {clarity_score} -> 최종: {final_score}")

    return {
      "score": final_score,
      "recognized_text": raw_text,
      "analysis_data": {
        "expected": {
          "text": expected_clean,
          "pronunciation": expected_pron,
          "jamo": [list(j) for j in self._decompose_jamo(expected_pron)]
        },
        "recognized": {
          "text": raw_clean,
          "pronunciation": raw_pron,
          "jamo": [list(j) for j in self._decompose_jamo(raw_pron)] if raw_pron else []
        },
        "detected_rules": detected_rules,
        "word_details": word_details,
        "aligned_result": best_aligned_result,
        "clarity_score": clarity_score,
      }
    }
