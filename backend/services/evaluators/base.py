from abc import ABC, abstractmethod

class BaseEvaluator(ABC):
  @abstractmethod
  def evaluate(self, expected: str, candidates: list, raw_text: str = "", candidate_results: dict = None, mode: str = "word", audio_np=None) -> dict:
    """
    언어별 평가 엔진의 공통 인터페이스입니다.
    expected: 정답 텍스트
    candidates: 발음 후보군 리스트
    raw_text: Whisper가 목표 언어로 고정하여 인식한 정밀 전사 결과
    candidate_results: 각 후보군별 강제 정렬 결과 및 점수
    mode: 평가 모드 (word/sentence)
    audio_np: 원본 오디오 배열 (float32, 16kHz) — pitch 분석 등 언어별 추가 분석에 선택적으로 사용
    """
    pass

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

  def _levenshtein_distance(self, s1, s2):
    """편집 거리(Levenshtein Distance) 알고리즘 - 음소/병음/발음 비교용"""
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
