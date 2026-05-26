# ⚠️ 모듈 레벨에서 각 Evaluator 클래스 및 무거운 인스턴스 전역 초기화를 방지합니다.
# 서버 구동 시점에 G2p, pykakasi 등이 동기 로드되어 포트 바인딩 지연(타임아웃)을 방지하기 위함입니다.
# -> get_evaluator(language) 함수를 통해 실제 사용 시점 또는 백그라운드 warm-up 스레드에서 지연 초기화합니다.

_evaluators_cache = {}

def get_evaluator(language: str):
  """
  지정된 언어에 해당하는 평가기(Evaluator) 인스턴스를 지연 로딩(Lazy Loading) 방식으로 반환합니다.
  """
  if language not in _evaluators_cache:
    if language == "en":
      from .evaluators.en_evaluator import EnglishEvaluator
      _evaluators_cache["en"] = EnglishEvaluator()
    elif language == "zh":
      from .evaluators.zh_evaluator import ChineseEvaluator
      _evaluators_cache["zh"] = ChineseEvaluator()
    elif language == "ja":
      from .evaluators.ja_evaluator import JapaneseEvaluator
      _evaluators_cache["ja"] = JapaneseEvaluator()
    else:
      # 기본값은 영어 평가기를 사용합니다.
      if "en" not in _evaluators_cache:
        from .evaluators.en_evaluator import EnglishEvaluator
        _evaluators_cache["en"] = EnglishEvaluator()
      return _evaluators_cache["en"]
  return _evaluators_cache.get(language, _evaluators_cache.get("en"))

def evaluate_pronunciation(expected: str, candidates: list, raw_text: str = "", language: str = "en", mode: str = "word", candidate_results: dict = None, audio_np=None):
  """
  Dispatcher: 언어별 평가 엔진을 호출하여 최종 단어 선택 및 점수를 산출합니다.
  """
  # 1. 언어에 맞는 평가기를 지연 로딩 방식으로 선택합니다.
  evaluator = get_evaluator(language)
  
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
