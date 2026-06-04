import { useState, useEffect, useRef } from "react"
import "./App.css"

// API URL 설정 (프로덕션: 원격, 로컬: 로컬)
const IS_LOCAL = new URLSearchParams(window.location.search).get("wstest") === "1";
// const WS_URL = IS_LOCAL
//   ? "ws://localhost:8001/ws/evaluate"
//   : "wss://whisperai-backend-597168932357.asia-northeast3.run.app/ws/evaluate";
const API_URL = IS_LOCAL
  ? "http://localhost:8001"
  // : "https://whisperai-backend-597168932357.asia-northeast3.run.app";
  // : "http://35.216.18.79:8000"
  : "https://buried-make-translate-wiki.trycloudflare.com"

import { LANG_DATA, VARIANTS_FEEDBACK } from "./constants";

const SILENCE_THRESHOLD = 0.015;
const SILENCE_DURATION = 2000;

/**
 * 두 일본어 가나(Hiragana) 문자열 간의 Sequence Matcher 유사도를 구합니다.
 * Python의 difflib.SequenceMatcher(None, s1, s2).ratio() 와 유사하게 LCS 길이를 기반으로 산출합니다.
 */
const getSequenceSimilarity = (s1, s2) => {
  if (!s1 || !s2) return 0;
  const m = s1.length;
  const n = s2.length;
  const dp = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0));

  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (s1[i - 1] === s2[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  const lcs = dp[m][n];
  return (2 * lcs) / (m + n);
};

function App() {
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [practiceMode, setPracticeMode] = useState("word");
  const [targetWord, setTargetWord] = useState("");
  const [language, setLanguage] = useState("en");
  const [difficulty, setDifficulty] = useState(3);
  const [usePrompt, setUsePrompt] = useState(0); // 0: 없음, 1: initial_prompt, 2: hotwords, 3: 둘 다
  const [result, setResult] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [transcripts, setTranscripts] = useState([]);
  const [scoringLogs, setScoringLogs] = useState([]); // 채점 과정 로그
  const [serverData, setServerData] = useState(null); // 서버 응답 원본 보관용

  const audioContextRef = useRef(null);
  const workletNodeRef = useRef(null);
  const sourceRef = useRef(null);
  const streamRef = useRef(null);
  const audioChunksRef = useRef([]);
  const silenceTimerRef = useRef(null);
  const hasSpokenRef = useRef(false);

  useEffect(() => {
    const data = LANG_DATA[language] || LANG_DATA.en;
    const list = practiceMode === "word" ? data.words : data.sentences;
    setTargetWord(list[0]);
    setResult(null);
    setServerData(null); // 모드 변경 시 원본 데이터 초기화
    setScoringLogs([]);
  }, [practiceMode, language]);

  // 난이도 변경 시 즉시 재계산
  useEffect(() => {
    if (serverData) {
      if (serverData.error) {
        const resultData = {
          type: "result",
          content: serverData.recognized_text || "",
          target: serverData.expected || targetWord,
          score: 0,
          analysis_data: serverData.analysis_data || {},
          error: serverData.error
        };
        setResult(resultData);
        return;
      }

      const finalClientScore = calculateClientScore(serverData, difficulty, practiceMode, language);

      const resultData = {
        type: "result",
        content: serverData.recognized_text,
        target: serverData.expected,
        score: finalClientScore,
        analysis_data: serverData.analysis_data || {},
        error: serverData.error
      };

      setResult(resultData);

      // 최근 기록 업데이트 (동일한 데이터가 중복되지 않도록 처리 로직 필요할 수 있음)
      setTranscripts(prev => {
        const newTrans = [...prev];
        if (newTrans.length > 0 && newTrans[0].target === resultData.target && newTrans[0].content === resultData.content) {
          newTrans[0] = resultData; // 가장 최근 항목의 점수 업데이트
          return newTrans;
        }
        return [resultData, ...prev];
      });
    }
  }, [difficulty, serverData]);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true },
      });
      streamRef.current = stream;

      const audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
      audioContextRef.current = audioContext;

      if (audioContext.state === "suspended") await audioContext.resume();

      const workletUrl = new URL("./utils/audioProcessor.js", import.meta.url);
      await audioContext.audioWorklet.addModule(workletUrl);

      const source = audioContext.createMediaStreamSource(stream);
      sourceRef.current = source;

      const workletNode = new AudioWorkletNode(audioContext, "pcm-processor");
      workletNodeRef.current = workletNode;

      workletNode.port.onmessage = (event) => {
        const { pcm, volume } = event.data;
        audioChunksRef.current.push(new Int16Array(pcm));
        handleSilenceDetection(volume);
      };

      source.connect(workletNode);
      workletNode.connect(audioContext.destination);

      audioChunksRef.current = [];
      hasSpokenRef.current = false;
      setIsRecording(true);
      setResult(null);
    } catch (err) {
      console.error("Error accessing microphone:", err);
      alert("마이크 접근에 실패했습니다.");
    }
  };

  const handleSilenceDetection = (volume) => {
    if (volume > SILENCE_THRESHOLD) {
      setIsSpeaking(true);
      hasSpokenRef.current = true;
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    } else {
      setIsSpeaking(false);
      if (hasSpokenRef.current && !silenceTimerRef.current) {
        silenceTimerRef.current = setTimeout(() => stopRecording(), SILENCE_DURATION);
      }
    }
  };

  const stopRecording = () => {
    // 타이머가 남아있다면 제거
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }

    // 이미 중지되었는지 확인 (streamRef.current 존재 여부로 판단)
    if (!streamRef.current) return;

    // 상태 업데이트 (UI 반영용)
    setIsRecording(false);

    // 녹음 리소스 정리
    if (workletNodeRef.current) {
      workletNodeRef.current.disconnect();
      workletNodeRef.current = null;
    }
    if (sourceRef.current) {
      sourceRef.current.disconnect();
      sourceRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null; // 중복 실행 방지를 위해 null 처리
    }

    // 파일 전송 (청크가 있는 경우에만)
    if (audioChunksRef.current.length > 0) {
      sendAudioFile();
    }
  };

  const calculateClientScore = (data, diff, mode, lang) => {
    const logs = [];
    logs.push(`--- [${lang.toUpperCase()} ${mode === "word" ? "단어" : "문장"} 채점 시작 (난이도: ${diff}단계)] ---`);

    let finalScore = data.score; // 서버에서 온 기본 점수
    const analysis = data.analysis_data || {};

    if (lang === "en") {
      if (mode === "sentence") {
        const wordAnalysis = analysis.word_analysis || [];
        const totalWords = (data.expected || "").split(" ").length;

        if (wordAnalysis.length > 0) {
          const matchedWords = wordAnalysis.filter(w => w.word_score > 0);
          const matchRatio = matchedWords.length / totalWords;
          const avgClarity = matchedWords.reduce((acc, w) => acc + w.word_score, 0) / matchedWords.length;

          // 명확도는 word_score를 기반으로 계산합니다. (word_segments의 score와 같음. whisper에서 뽑아져 나온 값)

          // 난이도별 가중치 적용
          // 난이도별 가중치 적용
          let matchWeight, clarityWeight;
          if (diff <= 2) {
            matchWeight = 1.0;
            clarityWeight = 0.0;
            logs.push(`• 난이도 1~2단계: 명확도를 무시하고 일치율만으로 채점합니다.`);
          } else {
            matchWeight = 0.3 + (diff * 0.05);
            clarityWeight = 1.0 - matchWeight;
            logs.push(`• 난이도 3~5단계: 일치율과 명확도를 종합하여 채점합니다.`);
          }

          finalScore = Math.round((matchRatio * 100 * matchWeight) + (avgClarity * clarityWeight));

          logs.push(`• 인식된 단어: ${matchedWords.length} / ${totalWords} (일치율: ${Math.round(matchRatio * 100)}%)`);
          if (clarityWeight > 0) logs.push(`• 평균 명확도: ${Math.round(avgClarity)}점`);
          logs.push(`• 적용 가중치: 일치율 ${Math.round(matchWeight * 100)}% / 명확도 ${Math.round(clarityWeight * 100)}%`);
          logs.push(`• 산출 점수: (${Math.round(matchRatio * 100)} * ${matchWeight.toFixed(2)}) + (${Math.round(avgClarity)} * ${clarityWeight.toFixed(2)}) = ${finalScore}`);
        }
      } else {
        // 영어 단어 모드 채점
        const expectedPhonemes = analysis.expected || [];
        const recognizedPhonemes = analysis.selected || [];
        const charAnalysis = analysis.char_analysis || [];

        // 1. 음소 일치도 계산
        let matchCount = 0;
        expectedPhonemes.forEach(p => {
          if (recognizedPhonemes.includes(p)) matchCount++;
        });
        const phonemeScore = (matchCount / expectedPhonemes.length) * 100;

        // 2. 문자별 신뢰도 평균
        const avgCharScore = charAnalysis.length > 0
          ? (charAnalysis.reduce((acc, c) => acc + c.score, 0) / charAnalysis.length) * 100
          : 0;

        // 3. 최종 점수 산정
        let baseWordScore;
        if (diff <= 2) {
          baseWordScore = phonemeScore;
          logs.push(`• 난이도 1~2단계: 발음 명확도를 무시하고 음소 일치율만으로 채점합니다.`);
        } else {
          baseWordScore = (phonemeScore * 0.4) + (avgCharScore * 0.6);
          logs.push(`• 난이도 3~5단계: 음소 일치율(40%)과 명확도(60%)를 종합합니다.`);
        }

        // 4. 난이도 보정 (단어는 절대평가 성격이 강하므로 단계별 감점 적용)
        const difficultyPenalty = (diff - 1) * 2;
        finalScore = Math.round(Math.max(0, Math.min(100, baseWordScore - difficultyPenalty)));

        logs.push(`• 음소 일치율: ${Math.round(phonemeScore)}% (${matchCount}/${expectedPhonemes.length})`);
        if (diff >= 3) logs.push(`• 발음 명확도: ${Math.round(avgCharScore)}점`);
        logs.push(`• 난이도 보정: -${difficultyPenalty}점`);
        logs.push(`• 최종 점수: ${finalScore}점`);
      }
    } else if (lang === "zh" && analysis.word_details) {
      // 중국어 채점 로직 (백엔드 글자 단위 정렬 데이터 기반)
      const details = analysis.word_details;
      const total = details.length;

      let totalCharScore = 0;
      let toneWeight = 0;

      if (diff === 3) toneWeight = 0.3;
      else if (diff === 4) toneWeight = 0.4;
      else if (diff === 5) toneWeight = 0.5;

      logs.push(`• 난이도 ${diff}단계에 따라 글자 단위 채점을 진행합니다.`);

      details.forEach((d) => {
        const expected = d.expected;
        const recognized = d.recognized || "(누락)";
        const pinyinIsCorrect = !!d.pinyin_is_correct;
        const toneIsCorrect = !!d.tone_is_correct;
        const pinyinSim = typeof d.pinyin_similarity === "number" ? d.pinyin_similarity : (pinyinIsCorrect ? 1.0 : 0.0);

        let charScore = 0;

        if (diff === 1) {
          // 1단계: 병음만으로 채점, pinyin_similarity 기반 부분 점수(가산점) 부여
          charScore = Math.round(pinyinSim * 100);
          logs.push(`  - [${expected}] vs [${recognized}]: 병음 유사도 ${Math.round(pinyinSim * 100)}% 가산점 반영 -> ${charScore}점`);
        } else if (diff === 2) {
          // 2단계: 병음만으로 채점, 가산점 없음 (완벽 일치 시 100점)
          charScore = pinyinIsCorrect ? 100 : 0;
          logs.push(`  - [${expected}] vs [${recognized}]: 병음 일치 여부만 반영 -> ${charScore}점 (${pinyinIsCorrect ? "일치" : "불일치"})`);
        } else {
          // 3~5단계: 병음 + 성조로 채점, 가산점 없음, 단계가 높을수록 성조 반영 비율 증가
          if (!pinyinIsCorrect) {
            charScore = 0;
            logs.push(`  - [${expected}] vs [${recognized}]: 병음 불일치 -> 0점`);
          } else {
            if (toneIsCorrect) {
              charScore = 100;
              logs.push(`  - [${expected}] vs [${recognized}]: 병음 일치 + 성조 일치 -> 100점`);
            } else {
              charScore = Math.round(100 * (1 - toneWeight));
              logs.push(`  - [${expected}] vs [${recognized}]: 병음 일치 + 성조 불일치 (성조 반영 ${Math.round(toneWeight * 100)}% 감점) -> ${charScore}점`);
            }
          }
        }

        totalCharScore += charScore;
      });

      finalScore = total > 0 ? Math.round(totalCharScore / total) : 0;
      finalScore = Math.max(0, Math.min(100, finalScore));
      logs.push(`• 최종 결정 점수: ${finalScore}점 (각 글자 점수 평균)`);
    } else if (lang === "ja") {
      if (mode === "word") {
        // 일본어 단어 모드 채점
        const expected = analysis.expected || {};
        const selected = analysis.selected || {};

        const expectedKana = expected.kana || "";
        const selectedKana = selected.kana || "";
        const expectedMora = expected.mora || 0;
        const selectedMora = selected.mora || 0;

        // 1. Kana 문자 일치율 계산 (LCS 기반)
        const kanaSim = getSequenceSimilarity(expectedKana, selectedKana) * 100;

        // 2. Mora(박자) 차이에 따른 감점 계산
        const moraDiff = Math.abs(expectedMora - selectedMora);
        const moraPenalty = moraDiff * 15;

        // 3. 최종 점수 산정
        let baseWordScore;
        if (diff <= 2) {
          // 난이도 1~2단계: 발음 명확도 무시하고 Kana 일치도 및 Mora 감점만으로 평가
          baseWordScore = Math.max(0, kanaSim - moraPenalty);
          logs.push(`• 난이도 1~2단계: 발음 명확도를 무시하고 Kana 일치율 및 Mora 차이만으로 채점합니다.`);
        } else {
          // 난이도 3~5단계: aligned_result.word_segments의 각 히라가나 별 명확도를 반영
          const alignedResult = analysis.aligned_result || {};
          const wordSegments = alignedResult.word_segments || [];

          // 각 히라가나 별 score(명확도) 평균 계산
          const validScores = wordSegments
            .filter(s => typeof s.score === "number")
            .map(s => s.score * 100);

          const avgCharScore = validScores.length > 0
            ? validScores.reduce((acc, val) => acc + val, 0) / validScores.length
            : 0;

          // 단계별로 명확도 반영에 차등 가중치 부여
          let kanaWeight, clarityWeight;
          if (diff === 3) {
            kanaWeight = 0.60;
            clarityWeight = 0.40;
            logs.push(`• 난이도 3단계: 가나 일치도(60%)와 히라가나별 명확도(40%)를 종합합니다.`);
          } else if (diff === 4) {
            kanaWeight = 0.45;
            clarityWeight = 0.55;
            logs.push(`• 난이도 4단계: 가나 일치도(45%)와 히라가나별 명확도(55%)를 종합합니다.`);
          } else {
            // diff === 5
            kanaWeight = 0.30;
            clarityWeight = 0.70;
            logs.push(`• 난이도 5단계: 가나 일치도(30%)와 히라가나별 명확도(70%)를 종합합니다.`);
          }

          const matchScore = Math.max(0, kanaSim - moraPenalty);
          baseWordScore = (matchScore * kanaWeight) + (avgCharScore * clarityWeight);

          logs.push(`• 발음 명확도(히라가나 평균): ${Math.round(avgCharScore)}점`);
          logs.push(`• 적용 가중치: 가나 일치 ${Math.round(kanaWeight * 100)}% / 명확도 ${Math.round(clarityWeight * 100)}%`);
        }

        // 4. 난이도 단계별 보정 감점 적용 (영어 단어 모드와 동일)
        const difficultyPenalty = (diff - 1) * 2;
        finalScore = Math.round(Math.max(0, Math.min(100, baseWordScore - difficultyPenalty)));

        logs.push(`• 가나(Kana) 일치율: ${Math.round(kanaSim)}% (Target: ${expectedKana} / Recognized: ${selectedKana})`);
        logs.push(`• Mora(박자) 차이 감점: -${moraPenalty}점 (차이: ${moraDiff} Mora)`);
        logs.push(`• 난이도 보정: -${difficultyPenalty}점`);
        logs.push(`• 최종 점수: ${finalScore}점`);
      } else {
        logs.push(`• 일본어 문장 채점은 기본 분석 점수를 적용합니다: ${finalScore}점`);
      }
    } else {
      logs.push(`• 기본 분석 점수 적용: ${finalScore}점`);
    }

    logs.push(`✅ 최종 결정 점수: ${finalScore}점`);
    setScoringLogs(logs);
    return finalScore;
  };

  const sendAudioFile = async () => {
    setIsLoading(true);
    setScoringLogs([]);
    try {
      const totalLength = audioChunksRef.current.reduce((acc, chunk) => acc + chunk.length, 0);
      const combinedPcm = new Int16Array(totalLength);
      let offset = 0;
      for (const chunk of audioChunksRef.current) {
        combinedPcm.set(chunk, offset);
        offset += chunk.length;
      }

      const audioBlob = new Blob([combinedPcm.buffer], { type: "audio/raw" });
      const formData = new FormData();
      formData.append("file", audioBlob, "recording.raw");
      formData.append("expected", targetWord);
      formData.append("language", language);
      formData.append("mode", practiceMode);
      formData.append("usePrompt", usePrompt.toString());

      const langVariants = VARIANTS_FEEDBACK[language];
      if (langVariants && langVariants[targetWord]) {
        formData.append("candidates", JSON.stringify(langVariants[targetWord].candidates));
      }

      const response = await fetch(`${API_URL}/evaluate`, { method: "POST", body: formData });
      const data = await response.json();

      console.log("📋 서버 응답 데이터: ", data);

      if (data.error) {
        const errorMsg = typeof data.error === "object"
          ? `[${data.error.code}] ${data.error.msg}`
          : data.error;
        setScoringLogs([`❌ 오류 발생: ${errorMsg}`]);
      }

      // 서버 응답 저장 (useEffect를 통해 자동 채점 트리거)
      setServerData(data);
    } catch (error) {
      console.error("❌ 파일 전송 실패:", error);
      setScoringLogs([`❌ 시스템 오류: ${error.message}`]);
    } finally {
      setIsLoading(false);
      audioChunksRef.current = [];
    }
  };

  return (
    <div className="App">
      <h1>Whisper 발음 평가</h1>

      <div className="language-selector">
        {["en", "zh", "ja"].map(lang => (
          <label key={lang} className={`radio-label ${language === lang ? "active" : ""}`}>
            <input type="radio" name="language" value={lang} checked={language === lang} onChange={(e) => setLanguage(e.target.value)} />
            {lang === "en" ? "영어" : lang === "zh" ? "중국어" : "일본어"}
          </label>
        ))}
      </div>



      <div className="mode-tabs">
        <button className={`tab ${practiceMode === "word" ? "active" : ""}`} onClick={() => setPracticeMode("word")}>단어 연습</button>
        <button className={`tab ${practiceMode === "sentence" ? "active" : ""}`} onClick={() => setPracticeMode("sentence")}>문장 연습</button>
      </div>

      <div className="target-container">
        <div className={`word-grid ${practiceMode === "sentence" ? "sentence-list" : ""}`}>
          {(LANG_DATA[language] || LANG_DATA.en)[practiceMode === "word" ? "words" : "sentences"].map((text) => (
            <label key={text} className={`word-radio ${targetWord === text ? "active" : ""}`}>
              <input type="radio" name="targetWord" value={text} checked={targetWord === text} onChange={(e) => setTargetWord(e.target.value)} />
              {text}
            </label>
          ))}
        </div>
      </div>

      <div className="difficulty-selector" style={{ marginTop: "20px", paddingTop: "15px" }}>
        <h3>Prompt 모드</h3>
        <p style={{ fontSize: "0.85rem", color: "#666", marginBottom: "10px", whiteSpace: "pre-wrap", textAlign: "left" }}>
          {`
            Whisper에 정답 힌트를 제공하는 방식을 선택합니다.
            initial_prompt: 문맥(Context)을 알려줍니다. "The student is reading: {expected}"
            hotwords: 정답 단어를 강조합니다.
            둘 다: 문맥과 정답 단어를 모두 알려줍니다.
            
            initial_prompt: 이런 내용이 나올 가능성이 높다. 여러 후보 중 target 점수를 더 높게 줌. 문장 수준(Language Model Bias)에 영향을 줌. 시험 범위를 알려주는 것
            hotwords: 이 단어는 매우 중요하다. 특정 단어 수준(Vocabulary Bias)에 영향을 줌. 시험에 반드시 나온다고 표시하는 것
          `}
        </p>
        <div className="difficulty-group">
          {[
            { value: 0, label: "없음" },
            { value: 1, label: "initial_prompt" },
            { value: 2, label: "hotwords" },
            { value: 3, label: "둘 다" },
          ].map((opt) => (
            <button key={opt.value} className={`difficulty-btn ${usePrompt === opt.value ? "active" : ""}`} onClick={() => setUsePrompt(opt.value)}>
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {result && (
        <div className="score-container">
          <div className="score-circle"><span className="score-value">{result.score}</span>점</div>
          <div className="evaluation-details">
            <div className="word-highlight-container">
              {result.analysis_data?.word_details?.map((detail, idx) => {
                // 중국어: 난이도에 따라 병음만 또는 병음+성조로 정답 판정
                if (language === "zh") {
                  const isCorrect = difficulty <= 2
                    ? detail.pinyin_is_correct
                    : detail.pinyin_is_correct && detail.tone_is_correct;
                  // expected: { char, pinyin, tone } → "妈(ma1)" 형식
                  const expData = result.analysis_data?.expected?.[idx];
                  const expectedLabel = expData
                    ? `${expData.char}(${expData.pinyin}${expData.tone})`
                    : detail.expected;
                  // recognized: { char, pinyin, tone } → "ma1" 형식 (병음+성조만)
                  const recData = practiceMode === "word" ? result.analysis_data?.selected?.[idx] : result.analysis_data?.recognized?.[idx];
                  const tone = recData.pitch_confidence >= 0.5 ? recData.pitch_tone : recData.tone;
                  const recognizedLabel = recData
                    ? `${recData.pinyin}${tone}`
                    : "(누락)";

                  return (
                    <div key={idx} className={`word-detail-item ${isCorrect ? "correct" : "incorrect"}`}>
                      <span className="expected-word">{expectedLabel}</span>
                      {!isCorrect && <span className="actual-word">{recognizedLabel}</span>}
                    </div>
                  );
                }

                // 영어 & 일본어: 기존 로직 유지
                return (
                  <div key={idx} className={`word-detail-item ${detail.is_correct ? "correct" : "incorrect"}`}>
                    <span className="expected-word">{detail.expected}</span>
                    {!detail.is_correct && <span className="actual-word">{detail.recognized || "(누락)"}</span>}
                  </div>
                );
              })}
            </div>
          </div>
          {/* {result.feedback && <p className="feedback-text">{result.feedback}</p>} */}
        </div>
      )}

      <div className="card">
        <button onClick={isRecording ? stopRecording : startRecording} className={isRecording ? "recording" : "primary"}>
          {isRecording ? "🛑 녹음 중지" : "🎤 녹음 시작"}
        </button>
      </div>

      <div className="difficulty-selector" style={{ marginTop: "40px", borderTop: "1px solid #eee", paddingTop: "20px" }}>
        <h3>평가 난이도 설정</h3>
        <p style={{ fontSize: "0.85rem", color: "#666", marginBottom: "10px" }}>난이도가 높을수록 문장 전체의 완결성과 정확도를 엄격하게 채점합니다.</p>
        <div className="difficulty-group">
          {[1, 2, 3, 4, 5].map((level) => (
            <button key={level} className={`difficulty-btn ${difficulty === level ? "active" : ""}`} onClick={() => setDifficulty(level)}>
              {level}단계
            </button>
          ))}
        </div>
      </div>

      {scoringLogs.length > 0 && (
        <div className="scoring-log-container" style={{ margin: "20px 0", padding: "15px", backgroundColor: "#f8f9fa", borderRadius: "8px", textAlign: "left", fontSize: "0.9rem", fontFamily: "monospace" }}>
          <h4 style={{ margin: "0 0 10px 0", color: "#333" }}>📊 Scoring Log</h4>
          {scoringLogs.map((log, i) => (
            <div key={i} style={{ marginBottom: "4px", color: log.startsWith("✅") ? "#28a745" : log.startsWith("❌") ? "#dc3545" : "#555" }}>
              {log}
            </div>
          ))}
        </div>
      )}

      <div className="transcript-container">
        <h3>최근 기록</h3>
        {transcripts.map((t, i) => (
          <div key={i} className="transcript-item">
            [{new Date().toLocaleTimeString()}] {t.target} → {t.content} ({t.score}점)
          </div>
        ))}
      </div>
    </div>
  );
}

export default App;
