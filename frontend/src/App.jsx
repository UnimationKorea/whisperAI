import { useState, useEffect, useRef } from "react"
import "./App.css"

// API URL 설정 (프로덕션: 원격, 로컬: 로컬)
const IS_LOCAL = new URLSearchParams(window.location.search).get("wstest") === "1";
// const WS_URL = IS_LOCAL
//   ? "ws://localhost:8001/ws/evaluate"
//   : "wss://whisperai-backend-597168932357.asia-northeast3.run.app/ws/evaluate";
const API_URL = IS_LOCAL
  ? "http://localhost:8001"
  : "https://whisperai-backend-597168932357.asia-northeast3.run.app";

const LANG_DATA = {
  en: {
    words: ["dog", "cat", "cow", "rabbit", "tiger", "chicken", "horse", "sheep", "goat", "monkey", "duck", "lion", "fox", "deer"],
    sentences: [
      "I love my dog.",
      "The cat is sleeping.",
      "The rabbit jumps high.",
      "A tiger lives in the jungle.",
      "The chicken crossed the road."
    ]
  },
  zh: {
    words: ["작업 전", "단어", "평가", "불가능"],
    sentences: [
      "你吃饭了吗?",
      "我还没吃呢.",
      "你去图书馆了吗?",
      "我还没去呢.",
      "我们一起去吃饺子吧.",
      "好, 去那家饭馆吧.",
      "我们一起去喝茶吧.",
      "好, 去那家茶馆吧.",
      "请问，有什么菜?",
      "我给你拿菜单.",
      "请问，有什么茶?",
      "我给你看菜单.",
      "这里的炒饭很好吃.",
      "炒饭的价格也不贵.",
      "这里的菜很好吃.",
      "菜的价格也不贵."
    ]
  },
  ja: {
    words: ["犬", "猫", "牛", "うさぎ", "虎", "鶏", "馬", "羊", "山羊", "猿"],
    sentences: ["저는 개를 좋아합니다."]
  }
};

// 프론트엔드에서 관리하는 발음 후보군 및 피드백 데이터
const VARIANTS_FEEDBACK = {
  en: {
    dog: {
      candidates: ["dog", "dod", "dag", "dork", "dot", "dock", "dug", "bog", "tog", "log"],
      feedback: {
        "dod": "👉 끝소리 'g'가 'd'처럼 들려요. 목 안쪽에서 소리를 더 울려주세요.",
        "dag": "👉 모음 'o'가 'a'처럼 들려요. 입을 더 동그랗게 벌려보세요.",
        "dot": "👉 끝소리 'g'가 't'처럼 짧게 들려요. 목청을 조금 더 울려주세요.",
        "dock": "👉 끝소리 'g'가 'k'처럼 들려요. 공기를 밖으로 훅 내뱉지 마세요.",
        "log": "👉 첫 소리 'd'가 'l'처럼 들려요. 혀끝을 윗니 뒤쪽에 강하게 대보세요."
      }
    },
    cat: {
      candidates: ["cat", "cart", "cad", "ket", "kit", "cut", "cap", "gat", "bat", "sat"],
      feedback: {
        "cap": "👉 끝소리 't'가 'p'처럼 들려요. 혀끝을 윗니 뒤에 붙이며 멈춰보세요.",
        "cart": "👉 중간에 'r' 소리가 섞여 들려요. 혀를 굴리지 말고 짧게 끊어보세요.",
        "cad": "👉 끝소리가 'd'처럼 들려요. 좀 더 가볍고 짧게 't' 소리를 내보세요.",
        "ket": "👉 모음 'a'가 'e'처럼 들려요. 입을 더 위아래로 벌려보세요.",
        "sat": "👉 첫 소리 'c'가 's'처럼 들려요. 목 뒤쪽에서 '큭' 하는 느낌으로 시작하세요."
      }
    },
    rabbit: {
      candidates: ["rabbit", "rabbit-it", "rabbit-e", "rabid", "rob-it", "labbit", "habit", "babbit", "grab-it", "rabbit-o"],
      feedback: {
        "rabbit-it": "👉 'rabbit' 끝에 'it' 소리가 섞여 들려요. 조금 더 깔끔하게 끝내보세요.",
        "labbit": "👉 'r' 발음이 'l'처럼 들려요. 혀끝을 입천장에 대지 말고 살짝 말아보세요!",
        "habit": "👉 'r' 발음이 'h'처럼 들려요. 입술을 좀 더 동그랗게 모으고 시작해보세요."
      }
    }
  }
};

const SILENCE_THRESHOLD = 0.015; 
const SILENCE_DURATION = 2000; 

function App() {
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false); 
  const [practiceMode, setPracticeMode] = useState("word"); 
  const [targetWord, setTargetWord] = useState("");
  const [language, setLanguage] = useState("en"); 
  const [difficulty, setDifficulty] = useState(3); 
  const [result, setResult] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [transcripts, setTranscripts] = useState([]);

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
  }, [practiceMode, language]);

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
    setIsRecording(false);
    if (workletNodeRef.current) workletNodeRef.current.disconnect();
    if (sourceRef.current) sourceRef.current.disconnect();
    if (audioContextRef.current) audioContextRef.current.close();
    if (streamRef.current) streamRef.current.getTracks().forEach((track) => track.stop());
    
    if (audioChunksRef.current.length > 0) sendAudioFile();
  };

  const sendAudioFile = async () => {
    setIsLoading(true);
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
      formData.append("difficulty", difficulty);
      formData.append("mode", practiceMode);

      const langVariants = VARIANTS_FEEDBACK[language];
      if (langVariants && langVariants[targetWord]) {
        formData.append("candidates", JSON.stringify(langVariants[targetWord].candidates));
        formData.append("feedback_map", JSON.stringify(langVariants[targetWord].feedback));
      }

      const response = await fetch(`${API_URL}/evaluate`, { method: "POST", body: formData });
      const data = await response.json();

      const resultData = {
        type: "result",
        content: data.recognized_text,
        target: data.expected,
        score: data.score,
        feedback: data.feedback,
        word_details: data.word_details || []
      };

      setResult(resultData);
      setTranscripts(prev => [resultData, ...prev]);
    } catch (error) {
      console.error("❌ 파일 전송 실패:", error);
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

      <div className="difficulty-selector">
        <h3>난이도 설정</h3>
        <div className="difficulty-group">
          {[1, 2, 3, 4, 5].map((level) => (
            <button key={level} className={`difficulty-btn ${difficulty === level ? "active" : ""}`} onClick={() => setDifficulty(level)}>
              {level}단계
            </button>
          ))}
        </div>
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

      {result && (
        <div className="score-container">
          <div className="score-circle"><span className="score-value">{result.score}</span>점</div>
          <div className="evaluation-details">
            <div className="word-highlight-container">
              {result.word_details.map((detail, idx) => (
                <div key={idx} className={`word-detail-item ${detail.is_correct ? "correct" : "incorrect"}`}>
                  <span className="expected-word">{detail.expected}</span>
                  {!detail.is_correct && <span className="actual-word">{detail.actual || "(누락)"}</span>}
                </div>
              ))}
            </div>
          </div>
          {result.feedback && <p className="feedback-text">{result.feedback}</p>}
        </div>
      )}

      <div className="card">
        <button onClick={isRecording ? stopRecording : startRecording} className={isRecording ? "recording" : "primary"}>
          {isRecording ? "🛑 녹음 중지" : "🎤 녹음 시작"}
        </button>
      </div>

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
