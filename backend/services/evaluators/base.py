from abc import ABC, abstractmethod

class BaseEvaluator(ABC):
  @abstractmethod
  def evaluate(self, expected: str, candidates: list, raw_text: str = "", candidate_results: dict = None, mode: str = "word") -> dict:
    """
    언어별 평가 엔진의 공통 인터페이스입니다.
    expected: 정답 텍스트
    candidates: 발음 후보군 리스트
    raw_text: Whisper가 목표 언어로 고정하여 인식한 정밀 전사 결과
    candidate_results: 각 후보군별 강제 정렬 결과 및 점수
    mode: 평가 모드 (word/sentence)
    """
    pass
