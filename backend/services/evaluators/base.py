from abc import ABC, abstractmethod

class BaseEvaluator(ABC):
  @abstractmethod
  def evaluate(self, expected: str, actual: str, word_list: list = None, gop_score: int = None) -> dict:
    """
    expected: 정답 텍스트
    actual: 인식된 텍스트
    word_list: 단어 단위 리스트 (Optional)
    gop_score: 강제 정렬을 통해 계산된 GOP 점수 (Optional)
    """
    pass
