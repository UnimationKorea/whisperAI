from .base import BaseEvaluator

class JapaneseEvaluator(BaseEvaluator):
  def evaluate(self, expected: str, candidates: list, raw_text: str = "", candidate_results: dict = None, difficulty: int = 3) -> dict:
    # 1. 가장 점수가 높은 후보 선택 (기본 동작)
    best_candidate = expected
    best_score = -1
    best_aligned_result = None

    if candidate_results:
      for cand, res in candidate_results.items():
        if res.get("avg_score", 0) > best_score:
          best_score = res.get("avg_score", 0)
          best_candidate = cand
          best_aligned_result = res.get("result")

    # TODO: 박자(Mora) 및 리듬 기반 평가 로직 구현 예정
    import difflib
    matcher = difflib.SequenceMatcher(None, expected, best_candidate)
    score = int(matcher.ratio() * 100)
    
    return {
      "score": score,
      "feedback": "일본어 평가 엔진 준비 중입니다. (박자 평가 예정)",
      "recognized_text": best_candidate,
      "aligned_result": best_aligned_result
    }
