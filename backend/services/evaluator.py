from .evaluators.en_evaluator import EnglishEvaluator
from .evaluators.zh_evaluator import ChineseEvaluator
from .evaluators.ja_evaluator import JapaneseEvaluator

# 평가 엔진 매핑
EVALUATORS = {
  "en": EnglishEvaluator(),
  "zh": ChineseEvaluator(),
  "ja": JapaneseEvaluator(),
}

def evaluate_pronunciation(expected: str, candidates: list, raw_text: str = "", language: str = "en", mode: str = "word", candidate_results: dict = None, audio_np=None):
  """
  Dispatcher: 언어별 평가 엔진을 호출하여 최종 단어 선택 및 점수를 산출합니다.
  """
  # 1. 언어에 맞는 평가기 선택 (기본값: 영어)
  evaluator = EVALUATORS.get(language, EVALUATORS["en"])
  
  # 2. 평가 실행
  # 후보군 리스트와 각 정렬 결과, 그리고 Whisper가 직접 들은 raw_text를 모두 넘깁니다.
  # audio_np는 중국어 pitch contour 분석에만 사용되며, 다른 언어 평가기는 무시합니다.
  result = evaluator.evaluate(
    expected=expected, 
    candidates=candidates, 
    raw_text=raw_text,
    candidate_results=candidate_results, 
    mode=mode,
    audio_np=audio_np,
  )
  
  # 공통 응답 구조 보장
  return {
    "score": result.get("score", 0),
    "recognized_text": result.get("recognized_text", expected), # 선택된 최종 단어
    # 각 언어별 evaluator의 analysis_data에 word_details와 aligned_result가 이미 포함되어 있으므로, analysis_data만 그대로 통과시킵니다.
    "analysis_data": result.get("analysis_data", {}), # 분석 데이터 포함
    "error": result.get("error")
  }
