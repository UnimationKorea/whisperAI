from .base import BaseEvaluator

class JapaneseEvaluator(BaseEvaluator):
  def evaluate(self, expected: str, actual: str, word_list: list = None, aligned_segments: list = None) -> dict:
    # TODO: 길이 + 리듬(Mora) 기반 평가 로직 구현 예정
    # 현재는 단순 문자 기반 유사도 사용
    import difflib
    matcher = difflib.SequenceMatcher(None, expected, actual)
    score = int(matcher.ratio() * 100)
    
    return {
      "score": score,
      "feedback": "일본어 평가 엔진 준비 중입니다."
    }
