from abc import ABC, abstractmethod

class BaseEvaluator(ABC):
  @abstractmethod
  def evaluate(self, expected: str, candidates: list, raw_text: str = "", candidate_results: dict = None, difficulty: int = 3, mode: str = "word", feedback_map: dict = None) -> dict:
    """
    언어별 평가 엔진의 공통 인터페이스입니다.
    expected: 정답 텍스트
    candidates: 발음 후보군 리스트
    raw_text: Whisper가 인식한 원본 텍스트
    candidate_results: 각 후보군별 강제 정렬 결과 및 점수
    difficulty: 평가 난이도 (1~5)
    mode: 평가 모드 (word/sentence)
    feedback_map: 후보군별 맞춤형 피드백 맵 (Optional)
    """
    pass
