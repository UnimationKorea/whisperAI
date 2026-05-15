from .evaluators.en_evaluator import EnglishEvaluator
from .evaluators.zh_evaluator import ChineseEvaluator
from .evaluators.ja_evaluator import JapaneseEvaluator

# 평가 엔진 매핑
EVALUATORS = {
  "en": EnglishEvaluator(),
  "zh": ChineseEvaluator(),
  "ja": JapaneseEvaluator(),
}

def evaluate_pronunciation(expected: str, candidates: list, raw_text: str = "", language: str = "en", mode: str = "word", candidate_results: dict = None):
  """
  Dispatcher: 언어별 평가 엔진을 호출하여 최종 단어 선택 및 점수를 산출합니다.
  """
  # 1. 언어에 맞는 평가기 선택 (기본값: 영어)
  evaluator = EVALUATORS.get(language, EVALUATORS["en"])
  
  # 2. 평가 실행
  # 후보군 리스트와 각 정렬 결과, 그리고 Whisper가 직접 들은 raw_text를 모두 넘깁니다.
  result = evaluator.evaluate(
    expected=expected, 
    candidates=candidates, 
    raw_text=raw_text,
    candidate_results=candidate_results, 
    mode=mode
  )
  
  # 공통 응답 구조 보장
  return {
    "score": result.get("score", 0),
    "recognized_text": result.get("recognized_text", expected), # 선택된 최종 단어
    "word_details": result.get("word_details", []), # 누락된 상세 분석 데이터 추가
    "aligned_result": result.get("aligned_result"), # 선택된 단어의 정렬 상세 데이터
    "analysis_data": result.get("analysis_data", {}), # 분석 데이터 포함
    "error": result.get("error")
  }
