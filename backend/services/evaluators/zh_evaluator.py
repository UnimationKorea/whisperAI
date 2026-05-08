from .base import BaseEvaluator

class ChineseEvaluator(BaseEvaluator):
  def evaluate(self, expected: str, candidates: list, raw_text: str = "", candidate_results: dict = None, difficulty: int = 3, mode: str = "word") -> dict:
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

    # TODO: 성조(Tone) 기반 평가 로직 구현 예정
    import difflib
    matcher = difflib.SequenceMatcher(None, expected, best_candidate)
    score = int(matcher.ratio() * 100)
    
    return {
      "score": int(best_score * 100),
      "feedback": f"중국어 발음 평가 결과입니다. (인식: {best_candidate})",
      "recognized_text": best_candidate,
      "word_details": [{
        "idx": 0,
        "expected": expected,
        "actual": best_candidate,
        "is_correct": (best_candidate == expected)
      }],
      "aligned_result": best_aligned_result
    }
