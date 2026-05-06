from .evaluators.en_evaluator import EnglishEvaluator
from .evaluators.zh_evaluator import ChineseEvaluator
from .evaluators.ja_evaluator import JapaneseEvaluator

# 평가 엔진 매핑
EVALUATORS = {
  "en": EnglishEvaluator(),
  "zh": ChineseEvaluator(),
  "ja": JapaneseEvaluator(),
}

def evaluate_pronunciation(expected: str, actual: str, word_list: list = None, language: str = "en", aligned_segments: list = None):
  """
  Dispatcher: 언어별 평가 엔진을 호출합니다.
  """
  # 1. 언어에 맞는 평가기 선택 (기본값: 영어)
  evaluator = EVALUATORS.get(language, EVALUATORS["en"])
  
  # 2. 평가 실행
  result = evaluator.evaluate(expected, actual, word_list, aligned_segments)
  
  # 공통 응답 구조 보장
  return {
    "score": result.get("score", 0),
    "feedback": result.get("feedback", "평가 결과가 없습니다."),
    "error": result.get("error")
  }
