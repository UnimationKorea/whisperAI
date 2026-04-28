import { useState, useEffect, useRef } from "react"
import "./App.css"

// WebSocket URL 설정 (프로덕션: 원격, 로컬: 로컬)
const IS_LOCAL = new URLSearchParams(window.location.search).get("wstest") === "1";
// const WS_URL = IS_LOCAL
//   ? "ws://localhost:8001/ws/evaluate"
//   : "wss://whisperai-backend-597168932357.asia-northeast3.run.app/ws/evaluate";
const API_URL = IS_LOCAL
  ? "http://localhost:8001"
  : "https://whisperai-backend-597168932357.asia-northeast3.run.app";

const WORDS = ["dog", "cat", "caw", "rabbit", "tiger"];
const SILENCE_THRESHOLD = 0.015; // 침묵으로 간주할 볼륨 임계값. 작을 수록 더 민감 (소리가 잘 안 잡히면 0.005까지 낮춤)
const SILENCE_DURATION = 2000; // 2초간 침묵 시 종료

function App() {
  const [isRecording, setIsRecording] = useState(false);
  // const [status, setStatus] = useState("Disconnected");
  const [isSpeaking, setIsSpeaking] = useState(false); // 음성 감지 상태 표시용
  const [evaluateMode, setEvaluateMode] = useState("post"); // "websocket" | "post"
  const [targetWord, setTargetWord] = useState("");
  const [result, setResult] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [transcripts, setTranscripts] = useState([]);
  const socketRef = useRef(null);
  const audioContextRef = useRef(null);
  const workletNodeRef = useRef(null);
  const sourceRef = useRef(null);
  const streamRef = useRef(null);
  const audioChunksRef = useRef([]); // POST 방식을 위한 버퍼
  const silenceTimerRef = useRef(null); // 침묵 감지 타이머
  const hasSpokenRef = useRef(false);   // 음성 감지 시작 여부

  /* 
  // WebSocket 연결
  const connectWebSocket = () => {
    const socket = new WebSocket(WS_URL);
    
    socket.onopen = () => {
      setStatus("Connected");
      console.log("WebSocket Connected");
      // 처음 연결 시 단어 초기화
      if (!targetWord) selectRandomWord();
    };

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      // if (data.type === "transcript") {
      if (data.type === "result") {
        setResult(data);
        setTranscripts(prev => [data, ...prev]);
      }
    };

    socket.onclose = () => {
      setStatus("Disconnected");
      console.log("WebSocket Disconnected");
      // 자동 재연결 시도 (3초 후)
      setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = (error) => {
      console.error("WebSocket Error:", error);
    };

    socketRef.current = socket;
  };

  useEffect(() => {
    connectWebSocket();
    return () => {
      if (socketRef.current) socketRef.current.close();
    };
  }, []);
  */

  useEffect(() => {
    // connectWebSocket(); // <--- 이 부분이 주석 처리되어 있는지 반드시 확인하세요!
    
    // 처음 로딩 시 단어 초기화
    if (!targetWord) selectRandomWord();
  }, []);

  const selectRandomWord = () => {
    const randomWord = WORDS[Math.floor(Math.random() * WORDS.length)];
    setTargetWord(randomWord);
    setResult(null); // 새로운 단어 선택 시 이전 결과 초기화

    // WebSocket이 연결되어 있다면 서버에 알림
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({
        type: "config",
        targetWord: randomWord
      }));
    }
  };

  // 마이크 녹음 시작
  const startRecording = async () => {
    try {
      // 마이크 접근
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;

      // AudioContext 생성 (16kHz)
      const audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000,
      });
      audioContextRef.current = audioContext;

      // AudioContext가 suspended 상태면 resume
      if (audioContext.state === "suspended") {
        await audioContext.resume();
      }

      // AudioWorklet 모듈 로드 (Vite 호환 방식)
      try {
        const workletUrl = new URL("./utils/audioProcessor.js", import.meta.url);
        await audioContext.audioWorklet.addModule(workletUrl);
        console.log("✅ AudioWorklet 로드 성공:", workletUrl.href);
      } catch (workletError) {
        console.error("❌ AudioWorklet 로드 실패:", workletError);
        alert("오디오 프로세서 로드에 실패했습니다.");
        return;
      }

      // 마이크 소스 노드
      const source = audioContext.createMediaStreamSource(stream);
      sourceRef.current = source;

      // AudioWorkletNode 생성
      const workletNode = new AudioWorkletNode(audioContext, "pcm-processor");
      workletNodeRef.current = workletNode;

      // Worklet에서 PCM 데이터 및 볼륨 수신
      workletNode.port.onmessage = (event) => {
        const { pcm, volume } = event.data;
        
        // 1. 오디오 데이터 처리
        if (evaluateMode === "websocket") {
          // 실시간 모드: 바로 전송
          if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
            socketRef.current.send(pcm);
          }
        } else {
          // POST 모드: 버퍼에 저장
          audioChunksRef.current.push(new Int16Array(pcm));
        }

        // 2. 침묵 감지 (VAD)
        handleSilenceDetection(volume);
      };

      /* 
      // 서버에 현재 제시어 전송 (WebSocket 모드일 때만 필요하지만 일단 전송)
      if (evaluateMode === "websocket" && socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
        socketRef.current.send(JSON.stringify({
          type: "config",
          targetWord: targetWord
        }));
      }
      */

      // 오디오 파이프라인 연결
      source.connect(workletNode);
      workletNode.connect(audioContext.destination);

      audioChunksRef.current = []; // 버퍼 초기화
      hasSpokenRef.current = false; // 음성 감지 초기화
      clearTimeout(silenceTimerRef.current);
      
      setIsRecording(true);
      setResult(null);
      console.log(`🎤 AudioWorklet 녹음 시작 (16kHz PCM) (모드: ${evaluateMode})`);
    } catch (err) {
      console.error("Error accessing microphone:", err);
      alert("마이크 접근에 실패했습니다.");
    }
  };

  // 침묵 감지 처리 함수
  const handleSilenceDetection = (volume) => {
    if (volume > SILENCE_THRESHOLD) {
      // 소리가 들리면 타이머 초기화 및 음성 감지 시작
      setIsSpeaking(true);
      hasSpokenRef.current = true;
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    } else {
      setIsSpeaking(false);
      if (hasSpokenRef.current) {
        if (!silenceTimerRef.current) {
          silenceTimerRef.current = setTimeout(() => {
            console.log("🤫 침묵 감지: 자동 녹음 중지");
            stopRecording();
          }, SILENCE_DURATION);
        }
      }
    }
  };

  // 녹음 중지
  const stopRecording = async () => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }

    setIsRecording(false);
    
    // 노드 및 스트림 해제 로직
    if (workletNodeRef.current) {
      workletNodeRef.current.disconnect();
      workletNodeRef.current = null;
    }

    // 소스 노드 해제
    if (sourceRef.current) {
      sourceRef.current.disconnect();
      sourceRef.current = null;
    }

    // AudioContext 종료
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    // 미디어 스트림 트랙 정지
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }

    console.log("⏹ 녹음 중지");

    // POST 모드인 경우 파일 전송
    if (evaluateMode === "post" && audioChunksRef.current.length > 0) {
      await sendAudioFile();
    }
  };

  // POST 방식 파일 전송
  const sendAudioFile = async () => {
    setIsLoading(true);
    try {
      // 1. PCM 데이터 합치기
      const totalLength = audioChunksRef.current.reduce((acc, chunk) => acc + chunk.length, 0);
      const combinedPcm = new Int16Array(totalLength);
      let offset = 0;
      for (const chunk of audioChunksRef.current) {
        combinedPcm.set(chunk, offset);
        offset += chunk.length;
      }

      // 2. Blob 생성 (WAV 헤더 없이 Raw PCM으로 보내거나 가짜 헤더 추가)
      // 여기서는 백엔드가 파일 형식을 식별할 수 있도록 단순 Blob 생성
      const audioBlob = new Blob([combinedPcm.buffer], { type: "audio/raw" });
      
      const formData = new FormData();
      formData.append("file", audioBlob, "recording.raw");
      formData.append("expected", targetWord);

      console.log("📤 파일 업로드 중...");
      const response = await fetch(`${API_URL}/evaluate`, {
        method: "POST",
        body: formData,
      });

      const data = await response.json();
      console.log("✅ 평가 결과 수신:", data);

      const resultData = {
        type: "result",
        content: data.recognized_text,
        target: data.expected,
        score: data.score,
        feedback: data.feedback
      };

      setResult(resultData);
      setTranscripts(prev => [resultData, ...prev]);
    } catch (error) {
      console.error("❌ 파일 전송 실패:", error);
      alert("평가 전송 중 오류가 발생했습니다.");
    } finally {
      setIsLoading(false);
      audioChunksRef.current = [];
    }
  };

  return (
    <div className="App">
      <h1>Whisper 발음 평가</h1>
      
      {/* 
      <div className="mode-selector">
        <button 
          className={evaluateMode === "websocket" ? "active" : ""} 
          onClick={() => setEvaluateMode("websocket")}
          disabled={isRecording}
        >
          실시간 (WebSocket)
        </button>
        <button 
          className={evaluateMode === "post" ? "active" : ""} 
          onClick={() => setEvaluateMode("post")}
          disabled={isRecording}
        >
          녹음 후 평가 (POST)
        </button>
      </div>
      */}

      {isRecording && (
        <div className="recording-indicator">
          <span className={`dot ${isSpeaking ? "active" : ""}`}></span>
          {isSpeaking ? "음성 감지 중..." : "침묵 대기 중... 2초 대기 후 자동으로 녹음 종료."}
        </div>
      )}

      <div className="target-container">
        <h2>제시어를 읽어보세요:</h2>
        <div className="target-word">{targetWord}</div>
        <button onClick={selectRandomWord} className="secondary">단어 바꾸기</button>
      </div>

      {result && (
        <div className="score-container">
          <div className="score-circle">
            <span className="score-value">{result.score}</span>
            <span className="score-label">점</span>
          </div>
          <p className="recognition-text">인식된 발음: <strong>{result.content}</strong></p>
          {result.feedback && <p className="feedback-text">{result.feedback}</p>}
        </div>
      )}

      {isLoading && <div className="loader">분석 중...</div>}

      <div className="card">
        {!isRecording ? (
          <button onClick={startRecording} className="primary">
            🎤 녹음 시작
          </button>
        ) : (
          <button onClick={stopRecording} className="recording">
            🛑 녹음 중지
          </button>
        )}
      </div>

      <div className="transcript-container">
        <h3>최근 기록:</h3>
        {transcripts.length === 0 && <p style={{ color: "#666" }}>말을 하면 여기에 결과가 표시됩니다...</p>}
        {transcripts.map((t, i) => (
          <div key={i} className="transcript-item">
            <span className="time">[{new Date().toLocaleTimeString()}]</span>
            <span className="text"> {t.target} → {t.content} ({t.score}점)</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default App
