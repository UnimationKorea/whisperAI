import re
import difflib
import logging
import numpy as np
import pyworld as pw
from pypinyin import pinyin, Style  # type: ignore
from .base import BaseEvaluator

logger = logging.getLogger(__name__)


class ChineseEvaluator(BaseEvaluator):
  def evaluate(
    self,
    expected: str,
    candidates: list,
    raw_text: str = "",
    candidate_results: dict = None,
    mode: str = "word",
    audio_np=None,
  ) -> dict:
    """
    중국어 평가 메인 진입점.
    audio_np: 원본 오디오 배열 (float32, 16kHz) — pitch contour 분석에 사용됩니다.
    """
    if mode == "sentence":
      return self._evaluate_sentence(expected, raw_text, candidate_results, audio_np=audio_np)
    else:
      return self._evaluate_word(expected, candidates, raw_text, candidate_results, audio_np=audio_np)

  # ──────────────────────────────────────────────────────────────
  # Pitch Contour 분석 메서드 (pyworld 기반)
  # ──────────────────────────────────────────────────────────────

  def _extract_f0(self, audio_np: np.ndarray, sr: int = 16000):
    """
    pyworld(DIO + StoneMask)로 오디오에서 F0(기본 주파수) 배열을 추출합니다.
    반환:
      voiced_f0  — 유성음 구간의 F0 값 배열 (Hz, 0 제외)
      raw_f0     — 전체 프레임 F0 (무성음 프레임은 0)
      time_axis  — 각 프레임의 타임스탬프 (초)
    """
    # pyworld는 float64 배열을 요구합니다.
    audio_64 = audio_np.astype(np.float64)

    # DIO 알고리즘으로 초기 F0 추정
    raw_f0, time_axis = pw.dio(
      audio_64,
      sr,
      f0_floor=75.0,   # 최저 기본 주파수 (남성 저음 기준)
      f0_ceil=800.0,   # 최고 기본 주파수 (여성 고음 기준)
      frame_period=5.0  # 5ms 간격으로 프레임 분할
    )

    # StoneMask 알고리즘으로 F0 정제 (오류 프레임 보정)
    refined_f0 = pw.stonemask(audio_64, raw_f0, time_axis, sr)

    # 유성음 프레임만 추출 (F0 > 0인 구간)
    voiced_f0 = refined_f0[refined_f0 > 0]
    return voiced_f0, refined_f0, time_axis

  def _classify_tone_from_f0(self, voiced_f0: np.ndarray) -> tuple:
    """
    유성음 F0 배열을 분석하여 중국어 성조(1~5)를 추정합니다.
    반환:
      detected_tone — 추정 성조 번호 (1~5)
      confidence    — 추정 신뢰도 (0.0~1.0)
      norm_curve    — 정규화 F0 곡선 리스트 (0~1, 프론트엔드 시각화용)

    중국어 표준음 성조 패턴:
      1성 (高平調 55): 높고 평탄
      2성 (陽平   35): 낮→높 상승
      3성 (上聲  214): 낮→더낮→약상승 (谷型)
      4성 (去聲   51): 높→낮 하강
      경성 (輕聲)    : 짧고 약함
    """
    # 유효 데이터가 너무 적으면 판별 불가 → 경성(5) 반환
    if len(voiced_f0) < 5:
      return 5, 0.0, []

    f0_min = voiced_f0.min()
    f0_max = voiced_f0.max()

    # 변화폭이 5Hz 미만 → 사실상 평탄 → 1성으로 분류
    if f0_max - f0_min < 5.0:
      norm_curve = (np.ones_like(voiced_f0) * 0.8).tolist()
      return 1, 0.8, norm_curve

    # [0, 1] 범위로 정규화
    norm = (voiced_f0 - f0_min) / (f0_max - f0_min)
    n = len(norm)

    # 구간별 평균: 시작(처음 1/3), 중간(가운데 1/3), 끝(마지막 1/3)
    s = float(norm[: n // 3].mean())
    m = float(norm[n // 3 : 2 * n // 3].mean())
    e = float(norm[2 * n // 3 :].mean())

    # ── 성조별 판별 규칙 ──────────────────────────────────────────
    # 1성 (高平): 시작/끝 모두 높고, 전체 변화 작음
    if e > 0.55 and s > 0.55 and abs(e - s) < 0.35:
      tone = 1
      confidence = round(1.0 - abs(e - s), 2)

    # 2성 (上升): 끝이 시작보다 현저히 높음
    elif e - s > 0.25:
      tone = 2
      confidence = round(min(1.0, (e - s) * 2), 2)

    # 4성 (下降): 시작이 끝보다 현저히 높음
    elif s - e > 0.25:
      tone = 4
      confidence = round(min(1.0, (s - e) * 2), 2)

    # 3성 (谷型): 중간이 시작/끝보다 낮음 (V자형)
    elif m < s - 0.15 and m < e - 0.15:
      tone = 3
      confidence = round(min(1.0, ((s - m) + (e - m)) / 2), 2)

    # 판별 불가 → 경성
    else:
      tone = 5
      confidence = 0.3

    return tone, confidence, norm.tolist()

  def _analyze_pitch_segment(
    self,
    audio_np: np.ndarray,
    start_sec: float = None,
    end_sec: float = None,
    sr: int = 16000,
  ) -> dict:
    """
    오디오의 특정 구간(start_sec ~ end_sec)에서 F0를 추출하고 성조를 분류합니다.
    구간이 지정되지 않으면 전체 오디오를 분석합니다.
    반환: {"tone": int, "confidence": float, "f0_curve": list}
    """
    try:
      # 구간 슬라이싱
      if start_sec is not None and end_sec is not None:
        start_idx = int(start_sec * sr)
        end_idx = int(end_sec * sr)
        segment = audio_np[start_idx:end_idx]
      else:
        segment = audio_np

      # 최소 분석 길이 확인 (50ms = 800 샘플 @ 16kHz)
      if len(segment) < 800:
        return {"tone": 5, "confidence": 0.0, "f0_curve": []}

      voiced_f0, _, _ = self._extract_f0(segment, sr)
      tone, confidence, f0_curve = self._classify_tone_from_f0(voiced_f0)
      return {"tone": tone, "confidence": confidence, "f0_curve": f0_curve}

    except Exception as ex:
      logger.warning(f"[Pitch 분석 실패] {ex}")
      return {"tone": 5, "confidence": 0.0, "f0_curve": []}

  # ──────────────────────────────────────────────────────────────
  # Pinyin / Tone 텍스트 처리 메서드
  # ──────────────────────────────────────────────────────────────

  def _get_pinyin_details(self, text: str):
    """
    한자를 병음과 성조 객체 리스트로 반환합니다.
    예: "你好" -> [{"char": "你", "pinyin": "ni", "tone": 3}, {"char": "好", "pinyin": "hao", "tone": 3}]
    """
    if not text:
      return []
    py_list = pinyin(text, style=Style.TONE3, neutral_tone_with_five=True)
    results = []
    for i, item in enumerate(py_list):
      token = item[0]
      char = text[i] if i < len(text) else ""
      match = re.match(r"([a-z]+)([1-5])", token.lower())
      if match:
        results.append({"char": char, "pinyin": match.group(1), "tone": int(match.group(2))})
      else:
        results.append({"char": char, "pinyin": token.lower(), "tone": 5})
    return results

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
      match = re.match(r"([a-z]+)([1-5])", token.lower())
      if match:
        results.append((match.group(1), int(match.group(2))))
      else:
        # 성조 숫자가 없는 경우 경성(5)으로 처리
        results.append((token.lower(), 5))
    return results

  # ──────────────────────────────────────────────────────────────
  # 단어 평가 (Word Mode)
  # ──────────────────────────────────────────────────────────────

  def _evaluate_word(
    self,
    expected: str,
    candidates: list,
    raw_text: str = "",
    candidate_results: dict = None,
    audio_np=None,
  ) -> dict:
    """
    중국어 단어 평가 로직:
      후보군 매칭 + 병음 유사도 + 성조 분석 + pitch contour
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

      print(
        f"  - '{cand}' ({cand_py_str}): Align({alignment_score:.3f})"
        f" + Pinyin({pinyin_similarity:.3f}) = Comp({composite_score:.3f}){bonus_str}"
      )

      if composite_score > highest_composite_score:
        highest_composite_score = composite_score
        best_candidate = cand
        best_aligned_result = res.get("result")

    print(f"🏆 Final Selected Candidate: '{best_candidate}'")
    print(f"--------------------------------------------------\n")

    # 임계값 체크: 복합 점수가 너무 낮으면 전혀 다른 단어로 판단
    if highest_composite_score < 0.55:
      return {
        "score": 0,
        "recognized_text": raw_text,
        "error": { "code": "1302", "msg": "Different word detected" }, # 전혀 다른 단어를 말한 것으로 판단함 (Precondition Failed)
        "analysis_data": {
          "expected": self._get_pinyin_details(expected),
          "recognized": self._get_pinyin_details(raw_text),
          "word_details": [
            {
              "idx": 0,
              "expected": expected,
              "actual": raw_text,
              "is_correct": False,
              "score": 0,
            }
          ],
        },
      }

    # 2. 최종 점수 및 피드백 산출
    actual = best_candidate

    # 발음 명확도(Clarity) 계산: WhisperX 정렬 시의 confidence score 평균
    aligned_segments = best_aligned_result.get("segments", []) if best_aligned_result else []
    clarity_score = self._calculate_clarity_score(expected, aligned_segments)

    # 기본 점수 산출
    base_score = 100 if actual in candidates else 0

    # 명확도 기반 최종 점수 보정 (발음이 흐릿하면 추가 감점)
    clarity_threshold = 60 # 명확도 커트라인 고정
    if actual == expected:
      if clarity_score < clarity_threshold:
        final_score = int(base_score * (clarity_score / clarity_threshold))
      else:
        final_score = base_score
        # 고득점 보정 (명확도 92점 이상이면 100점 처리)
        if clarity_score >= 92:
          final_score = 100
    else:
      # 오답 후보 선택 시 명확도 비율대로 점수 적용
      final_score = int(base_score * (clarity_score / 100))

    # ── Pitch Contour 분석 (pyworld) ─────────────────────────────
    pitch_analysis = {
      "detected_tone": 5,
      "expected_tone": 5,
      "confidence": 0.0,
      "f0_curve": [],
      "penalty": 0,
      "available": False,  # 분석 수행 여부
    }

    if audio_np is not None:
      # 정답 단어의 기대 성조 목록 (첫 번째 글자 기준)
      expected_tones = [t for _, t in expected_py_data]
      expected_tone = expected_tones[0] if expected_tones else 5

      pitch_result = self._analyze_pitch_segment(audio_np)
      detected_tone = pitch_result["tone"]
      tone_confidence = pitch_result["confidence"]

      print(f"🎵 [Pitch Contour] 기대 성조: {expected_tone}성 / 감지 성조: {detected_tone}성 (신뢰도: {tone_confidence:.2f})")

      # 신뢰도가 충분할 때만 성조 페널티 적용
      # 경성(5)은 기대 성조로도, 감지 성조로도 페널티 면제
      pitch_penalty = 0
      if (
        tone_confidence >= 0.5
        and expected_tone != 5
        and detected_tone != 5
        and detected_tone != expected_tone
      ):
        pitch_penalty = 15  # 성조 불일치 시 최대 15점 감점
        print(f"  → 성조 불일치 페널티 적용: -{pitch_penalty}점")
      else:
        print(f"  → 성조 일치 또는 판정 보류 ✅")

      pitch_analysis = {
        "detected_tone": detected_tone,
        "expected_tone": expected_tone,
        "confidence": tone_confidence,
        "f0_curve": pitch_result["f0_curve"],
        "penalty": pitch_penalty,
        "available": True,
      }
      final_score = max(0, final_score - pitch_penalty)
    # ─────────────────────────────────────────────────────────────

    # 상세 정보 구성
    word_details = [
      {
        "idx": 0,
        "expected": expected,
        "actual": actual,
        "is_correct": (actual == expected),
        "score": final_score,
      }
    ]

    return {
      "score": max(0, min(100, final_score)),
      "recognized_text": actual,
      "analysis_data": {
        "expected": self._get_pinyin_details(expected),
        "recognized": self._get_pinyin_details(raw_text), # raw_text(refined) 기반
        "selected": self._get_pinyin_details(actual),
        "word_details": word_details,
        "aligned_result": best_aligned_result,
        "pitch_analysis": pitch_analysis,
      },
    }

  # ──────────────────────────────────────────────────────────────
  # 문장 평가 (Sentence Mode)
  # ──────────────────────────────────────────────────────────────

  def _evaluate_sentence(
    self,
    expected: str,
    raw_text: str = "",
    candidate_results: dict = None,
    audio_np=None,
  ) -> dict:
    """
    중국어 문장 평가 로직:
      글자 단위 정렬 + 성조 분석 + pitch contour (글자별 타임스탬프 활용)
      1. WhisperX 정렬 결과에서 글자별 타임스탬프 수집
        char_timestamps = { 0: {start: 0.12, end: 0.38}, 1: {start: 0.38, end: 0.65}, ... }
                              ↑ "你"                          ↑ "好"
      2. 각 글자별로 오디오 구간 슬라이싱 → pitch 분석
        audio_np[0.12s ~ 0.38s] → _analyze_pitch_segment() → {tone: 3, confidence: 0.72}
      3. 기대 성조(pinyin에서 추출)와 감지 성조 비교
        expected_tone = 3, detected_tone = 2 → tone_error = True
      4. tone_error가 있으면 최종 점수 상한 제한
        final_score = min(final_score, 85 - (tone_errors * 5))
    """
    # 0. 전처리: 불필요한 기호 제거
    expected_clean = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", expected)
    raw_clean = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", raw_text)

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

    recognized_pinyin_details = self._get_pinyin_details(raw_clean)

    # ── 글자별 Pitch 분석을 위한 타임스탬프 수집 ─────────────────
    # WhisperX 정렬 결과(best_aligned_result)에서 글자(char) 단위
    # 타임스탬프를 추출하여 {글자인덱스: {start, end}} 형태로 저장합니다.
    char_timestamps = {}
    if audio_np is not None and best_aligned_result:
      char_idx = 0
      for seg in best_aligned_result.get("segments", []):
        for char_info in seg.get("chars", []):
          start = char_info.get("start")
          end = char_info.get("end")
          if start is not None and end is not None:
            char_timestamps[char_idx] = {"start": start, "end": end}
          char_idx += 1
    # ─────────────────────────────────────────────────────────────

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
          sim_val = 0.0
          if exp_char == raw_char:
            # 완벽 일치
            char_score = 100
            sim_val = 1.0
            print(f"    -> Exact Match! Score: {char_score}")
          else:
            # 글자는 다르지만 발음/성조 체크
            e_p, e_t = exp_py[exp_idx] if exp_idx < len(exp_py) else ("", 5)
            r_p, r_t = raw_py[raw_idx] if raw_idx < len(raw_py) else ("", 5)

            if e_p == r_p:
              sim_val = 1.0
              if e_t == r_t:
                # 이체자 등: 표기만 다르고 발음/성조 동일
                char_score = 90
                print(f"    -> Pinyin & Tone Match (variant?)! Score: {char_score}")
              else:
                # 발음은 같은데 성조만 틀림
                char_score = 60
                tone_error = True
                print(f"    -> Pinyin Match, Tone Error ({e_t} vs {r_t}). Score: {char_score}")
            else:
              # 발음 자체가 다름 (점수는 최하점 처리, 유사도 정보만 클라이언트에 전달)
              sim_val = difflib.SequenceMatcher(None, e_p, r_p).ratio()
              char_score = 20
              print(f"    -> Pinyin Mismatch! {e_p} vs {r_p} (sim: {sim_val:.2f}). Score: {char_score}")

          if raw_idx is not None and raw_idx < len(recognized_pinyin_details):
            recognized_pinyin_details[raw_idx]["similarity"] = round(sim_val, 2)

        elif exp_char:
          # 글자가 누락됨
          char_score = 0
          print(f"  [Char {exp_idx}] '{exp_char}' -> Missing in transcription. Score: {char_score}")

        if exp_idx is not None:
          total_score += char_score

          # ── 글자별 Pitch Contour 분석 ────────────────────────────
          # WhisperX 정렬 타임스탬프가 있는 글자에 대해서만 수행합니다.
          pitch_info = None
          if audio_np is not None and exp_idx in char_timestamps:
            ts = char_timestamps[exp_idx]
            pitch_result = self._analyze_pitch_segment(audio_np, ts["start"], ts["end"])
            expected_tone = exp_py[exp_idx][1] if exp_idx < len(exp_py) else 5

            # 성조 일치 여부 판정
            # (신뢰도 < 0.5이거나 경성인 경우 판정 보류)
            tone_match = (
              pitch_result["tone"] == expected_tone
              or pitch_result["confidence"] < 0.5
              or expected_tone == 5
              or pitch_result["tone"] == 5
            )
            pitch_info = {
              "expected_tone": expected_tone,
              "detected_tone": pitch_result["tone"],
              "confidence": pitch_result["confidence"],
              "match": tone_match,
            }

            if not tone_match:
              print(
                f"    🎵 Pitch: {expected_tone}성 기대, "
                f"{pitch_result['tone']}성 감지 "
                f"(conf={pitch_result['confidence']:.2f}) → 성조 불일치"
              )
              # pitch 기반 성조 오류도 tone_error에 반영
              tone_error = True
          # ─────────────────────────────────────────────────────────

          word_details.append(
            {
              "idx": exp_idx,
              "expected": exp_char,
              "actual": raw_char,
              "is_correct": (char_score >= 90),
              "tone_error": tone_error,
              "score": char_score,
              **({"pitch": pitch_info} if pitch_info is not None else {}),
            }
          )

    # 2. 최종 종합 점수 산출
    avg_score = int(total_score / char_count) if char_count > 0 else 0

    # 물리적 명확도(Acoustic Score) 반영
    clarity_score = self._calculate_clarity_score(
      expected,
      best_aligned_result.get("segments", []) if best_aligned_result else [],
    )

    # 가중치 합산: 텍스트 일치(70%) + 발음 명확도(30%)
    final_score = int((avg_score * 0.7) + (clarity_score * 0.3))

    # 성조 보정 (텍스트 기반 + pitch 기반 통합)
    # 성조 오류가 있는 글자마다 감점하여 최대 점수를 제한합니다.
    tone_errors = sum(1 for d in word_details if d.get("tone_error"))
    if tone_errors > 0:
      final_score = min(final_score, 85 - (tone_errors * 5))

    # 3. 맞춤형 피드백 생성
    tone_error_chars = [d["expected"] for d in word_details if d.get("tone_error")]
    if final_score >= 90:
      feedback = "太棒了! 성조와 발음이 완벽합니다. 👍"
    elif tone_error_chars:
      feedback = (
        f"발음은 좋지만 [{', '.join(tone_error_chars[:3])}] 등의 성조가 정확하지 않아요. "
        f"성조에 주의해서 다시 읽어보세요."
      )
    elif final_score >= 60:
      feedback = "不错! 전반적으로 알아들을 수 있지만, 몇몇 글자가 누락되거나 틀렸습니다."
    else:
      feedback = "加油! 천천히 한 글자씩 또박또박 성조를 살려서 읽어보세요."

    print(f"📈 Match Score: {avg_score}, Clarity: {clarity_score} -> Final: {final_score}")
    print(f"------------------------------------------\n")

    return {
      "score": max(0, min(100, final_score)),
      "recognized_text": raw_text,
      "analysis_data": {
        "expected": self._get_pinyin_details(expected_clean),
        "recognized": recognized_pinyin_details,
        "word_details": word_details,
        "aligned_result": best_aligned_result,
      },
    }
