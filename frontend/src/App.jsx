import { useState, useEffect, useRef } from "react"
import "./App.css"

// WebSocket URL 설정 (프로덕션: 원격, 로컬: 로컬)
const WS_URL = new URLSearchParams(window.location.search).get("wstest") === "1"
  ? "ws://localhost:8001/ws/stt"
  : "wss://gemini-backend-937559353581.asia-northeast3.run.app/ws/stt";

function App() {
  const [isRecording, setIsRecording] = useState(false);
  const [status, setStatus] = useState("Disconnected");
  const [transcripts, setTranscripts] = useState([]);
  const socketRef = useRef(null);
  const audioContextRef = useRef(null);
  const workletNodeRef = useRef(null);
  const sourceRef = useRef(null);
  const streamRef = useRef(null);

  // WebSocket 연결
  const connectWebSocket = () => {
    const socket = new WebSocket(WS_URL);
    
    socket.onopen = () => {
      setStatus("Connected");
      console.log("WebSocket Connected");
    };

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "transcript") {
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

      // AudioWorklet 모듈 로드
      try {
        await audioContext.audioWorklet.addModule(new URL("./utils/audioProcessor.js", import.meta.url));
        console.log("✅ AudioWorklet 로드 성공");
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

      // Worklet에서 PCM 데이터 수신 → WebSocket 전송
      workletNode.port.onmessage = (event) => {
        const pcmData = event.data;
        if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
          socketRef.current.send(pcmData);
        }
      };

      // 오디오 파이프라인 연결
      source.connect(workletNode);
      workletNode.connect(audioContext.destination);

      setIsRecording(true);
      console.log("🎤 AudioWorklet 녹음 시작 (16kHz PCM)");
    } catch (err) {
      console.error("Error accessing microphone:", err);
      alert("마이크 접근에 실패했습니다.");
    }
  };

  // 녹음 중지
  const stopRecording = () => {
    // WorkletNode 해제
    if (workletNodeRef.current) {
      workletNodeRef.current.disconnect();
      if (workletNodeRef.current.port) {
        workletNodeRef.current.port.onmessage = null;
      }
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

    setIsRecording(false);
    console.log("⏹ 녹음 중지");
  };

  return (
    <div className="App">
      <h1>Whisper STT Test</h1>
      <div className="status-badge" style={{ color: status === "Connected" ? "#4CAF50" : "#f44336" }}>
        Status: {status}
      </div>

      <div className="card">
        {!isRecording ? (
          <button onClick={startRecording} disabled={status !== "Connected"}>
            🎤 Start Recording
          </button>
        ) : (
          <button onClick={stopRecording} className="recording">
            🛑 Stop Recording
          </button>
        )}
      </div>

      <div className="transcript-container">
        <h3>Transcripts:</h3>
        {transcripts.length === 0 && <p style={{ color: "#666" }}>말을 하면 여기에 텍스트가 표시됩니다...</p>}
        {transcripts.map((t, i) => (
          <div key={i} className="transcript-item">
            <span className="time">[{new Date().toLocaleTimeString()}]</span>
            <span className="text"> {t.content}</span>
            <div className="info">
              <small>Lang: {t.language} ({Math.round(t.probability * 100)}%)</small>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default App
