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
    words: ["妈妈", "爸爸", "你好", "苹果", "老师", "学生", "朋友", "再见", "谢谢", "学校"],
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
  },
  zh: {
    "妈妈": {
      "candidates": ["妈妈", "骂骂", "马马", "麻麻", "摸摸", "忙忙", "买买", "毛毛", "满满", "吗吗"],
      "feedback": {
        "骂骂": "👉 성조가 너무 강해요. 1성(높고 평평하게)으로 발음해보세요.",
        "马马": "👉 성조가 내려갔다 올라가네요. 1성으로 길게 유지해주세요.",
        "麻麻": "👉 성조가 올라가고 있어요. 처음부터 높은 음을 유지하세요.",
        "摸摸": "👉 모음 'a' 발음이 'o'처럼 들려요. 입을 더 크게 벌려주세요.",
        "忙忙": "👉 비음 'ng' 소리가 너무 강해요. 가볍게 '마' 하고 끝내보세요.",
        "买买": "👉 이중모음 'ai'처럼 들려요. 단순하게 '아' 소리만 내보세요.",
        "毛毛": "👉 'ao' 발음처럼 들려요. 입술을 너무 오므리지 마세요.",
        "满满": "👉 받침 'n' 소리가 섞여 들려요. 혀를 떼고 발음해보세요.",
        "吗吗": "👉 뒤 단어는 힘을 빼고 짧게 '경성'으로 발음해야 해요.",
        "妈妈": "👉 아주 훌륭한 1성 발음입니다!"
      }
    },
    "爸爸": {
      "candidates": ["爸爸", "巴巴", "把把", "罢罢", "怕怕", "抱抱", "班班", "奔奔", "贝贝", "叭叭"],
      "feedback": {
        "巴巴": "👉 성조가 너무 높고 평평해요. 4성으로 강하게 내려찍어보세요.",
        "把把": "👉 성조가 낮게 깔려요. 위에서 아래로 뚝 떨어뜨려 주세요.",
        "罢罢": "👉 4성은 맞지만 힘이 너무 들어갔거나 짧을 수 있어요. 자연스럽게 끊어주세요.",
        "怕怕": "👉 유기음 'p'처럼 들려요. 공기를 너무 세게 내뱉지 마세요.",
        "抱抱": "👉 'ao' 소리가 섞여 들려요. '아' 발음에 더 집중해 보세요.",
        "班班": "👉 받침 'n' 소리가 들려요. 입을 닫지 말고 열어둔 채로 발음하세요.",
        "奔奔": "👉 모음이 'e'처럼 들려요. '아' 소리가 나도록 입을 더 벌리세요.",
        "贝贝": "👉 'ei' 소리가 들려요. 단순한 '아' 발음이 필요합니다.",
        "叭叭": "👉 뒤 단어는 경성입니다. 힘을 빼고 가볍게 툭 던지듯 발음하세요.",
        "爸爸": "👉 완벽한 4성 발음입니다!"
      }
    },
    "你好": {
      "candidates": ["你好", "泥好", "你号", "您好", "尼蒿", "拟好", "逆好", "内好", "呐好", "匿浩"],
      "feedback": {
        "泥好": "👉 '你'의 성조가 2성처럼 들려요. 3성 성조 변화에 주의하세요.",
        "你号": "👉 '好'를 4성으로 너무 짧게 발음했어요. 3성으로 깊게 내려갔다 올라오세요.",
        "您好": "👉 받침 'n' 소리가 섞여 '닌하오'처럼 들려요. 혀끝을 떼보세요.",
        "尼蒿": "👉 '好'의 성조가 1성처럼 높게 유지되네요. 아래로 깊게 눌러주세요.",
        "拟好": "👉 '你'가 너무 낮게만 들려요. 2성으로 자연스럽게 연결하세요.",
        "逆好": "👉 '你'를 4성으로 너무 짧게 끊었어요. 부드럽게 올려주세요.",
        "内好": "👉 'n' 발음 뒤에 'ei' 소리가 섞여요. '이' 소리에 집중하세요.",
        "呐好": "👉 '니'가 아닌 '나'처럼 들려요. 입 모양을 옆으로 더 찢어보세요.",
        "匿浩": "👉 전체적으로 성조가 너무 짧고 강합니다. 더 부드럽게 연결해 보세요.",
        "你好": "👉 성조 변화가 아주 자연스러워요!"
      }
    },
    "苹果": {
      "candidates": ["苹果", "病果", "平果", "屏过", "拼过", "苹锅", "苹括", "瓶果", "苹各", "评过"],
      "feedback": {
        "病果": "👉 '苹'의 성조가 4성으로 너무 강해요. 2성으로 부드럽게 올려주세요.",
        "屏过": "👉 '果'의 성조가 4성처럼 들려요. 3성으로 깊게 내려주세요.",
        "拼过": "👉 '苹'은 1성이 아니라 2성입니다. 아래에서 위로 올려보세요.",
        "苹锅": "👉 '果'를 1성으로 너무 높게 발음했어요. 낮게 눌러주는 느낌이 필요해요.",
        "苹括": "👉 'g' 발음이 'k'처럼 공기가 많이 섞여 들려요. 목 뒤를 가볍게 눌러주세요.",
        "瓶果": "👉 '苹' 발음을 너무 길게 끄는 느낌이에요. 좀 더 간결하게 올려보세요.",
        "苹各": "👉 '果'의 모음이 'uo'가 아닌 'e'처럼 들려요. 입술을 동그랗게 해주세요.",
        "评过": "👉 성조가 둘 다 올라가거나 내려가네요. 2성-3성 리듬에 주의하세요.",
        "平果": "👉 거의 완벽합니다! 조금만 더 3성을 깊게 발음해 보세요.",
        "苹果": "👉 아주 좋은 발음입니다!"
      }
    },
    "老师": {
      "candidates": ["老师", "老是", "老实", "捞师", "唠师", "老稀", "老四", "脑师", "老湿", "老石"],
      "feedback": {
        "老是": "👉 '师'의 성조가 4성처럼 들려요. 1성으로 높고 길게 발음하세요.",
        "老实": "👉 '师'를 경성처럼 짧게 발음했어요. 1성으로 끝까지 음을 유지하세요.",
        "捞师": "👉 '老'의 성조가 2성처럼 들려요. 3성으로 확실히 낮춰주세요.",
        "唠师": "👉 '老'를 4성으로 너무 짧게 끊었어요. 부드럽게 내려갔다 오세요.",
        "老四": "👉 'sh' 발음이 's'처럼 들려요. 혀를 입천장 가까이 대고 권설음을 내보세요.",
        "脑师": "👉 'l' 발음이 'n'처럼 코소리가 섞여 들려요. 혀끝을 윗니 뒤에 대보세요.",
        "老稀": "👉 'sh' 발음이 'x'처럼 들려요. 혀를 너무 앞으로 빼지 마세요.",
        "老湿": "👉 권설음이 조금 과합니다. 좀 더 자연스럽게 발음해 보세요.",
        "老石": "👉 '师'의 성조가 올라가고 있어요. 높게 평평하게 유지하세요.",
        "老师": "👉 훌륭합니다! 권설음과 성조가 모두 완벽해요."
      }
    },
    "学生": {
      "candidates": ["学生", "学神", "削生", "学声", "雪生", "学圣", "学僧", "学身", "穴生", "选生"],
      "feedback": {
        "学神": "👉 '生'의 발음이 'en'이 아닌 'eng'에 가까워요. 혀 위치에 주의하세요.",
        "削生": "👉 '学'의 발음이 1성처럼 들려요. 2성으로 부드럽게 올려주세요.",
        "学声": "👉 '生'을 1성으로 너무 길게 발음했어요. 경성으로 가볍게 툭 던지세요.",
        "雪生": "👉 '学'의 성조가 3성처럼 들려요. 아래에서 위로 확실히 올려주세요.",
        "学圣": "👉 '生'을 4성으로 너무 강하게 발음했어요. 힘을 빼주세요.",
        "学僧": "👉 'sh' 발음이 's'처럼 들려요. 혀를 살짝 말아 올려보세요.",
        "选生": "👉 '学'의 모음이 'uan'처럼 들려요. 'ue' 발음에 집중하세요.",
        "学身": "👉 'sh' 발음이 너무 약해요. 좀 더 마찰음을 내주세요.",
        "穴生": "👉 '学'의 성조를 4성으로 내리꽂지 말고 위로 올려보세요.",
        "学生": "👉 좋습니다! 경성 처리와 성조가 아주 자연스러워요."
      }
    },
    "朋友": {
      "candidates": ["朋友", "蓬友", "盆友", "胖友", "朋又", "喷友", "碰友", "朋腰", "烹友", "盆右"],
      "feedback": {
        "盆友": "👉 '朋'의 발음이 'en'처럼 들려요. 'eng' 발음으로 입을 더 벌려보세요.",
        "胖友": "👉 '朋'의 발음이 4성처럼 들려요. 2성으로 가볍게 올려주세요.",
        "朋又": "👉 '友'를 4성으로 너무 짧게 발음했어요. 가벼운 경성으로 처리하세요.",
        "喷友": "👉 '朋'의 성조가 1성처럼 들려요. 2성으로 올려주는 느낌이 부족해요.",
        "朋腰": "👉 '友'의 모음이 'ao'처럼 들려요. 'ou' 발음으로 입을 모아주세요.",
        "烹友": "👉 '朋' 발음 시 입술을 더 강하게 떼며 소리를 울려주세요.",
        "碰友": "👉 성조가 너무 강하고 짧습니다. 2성으로 부드럽게 올려 보세요.",
        "盆右": "👉 발음과 성조가 모두 조금씩 어긋나 있습니다. 다시 들어보세요.",
        "蓬友": "👉 아주 좋습니다! 거의 완벽한 발음입니다.",
        "朋友": "👉 완벽한 발음입니다!"
      }
    },
    "再见": {
      "candidates": ["再见", "在简", "摘见", "在尖", "载见", "在建", "在减", "在兼", "窄见", "在箭"],
      "feedback": {
        "在简": "👉 '见'의 성조가 3성처럼 들려요. 4성으로 짧고 강하게 발음하세요.",
        "在尖": "👉 '见'의 성조가 1성처럼 들려요. 끝을 뚝 떨어뜨려 주세요.",
        "摘见": "👉 'z' 발음이 'zh'처럼 혀가 말린 소리가 나요. 혀를 이 뒤에 가볍게 대세요.",
        "载见": "👉 '再'의 성조가 3성처럼 들려요. 4성으로 확실히 내리꽂으세요.",
        "在建": "👉 4성 기운이 조금 부족해요. 좀 더 힘있게 '찌앤' 하고 끊어보세요.",
        "窄见": "👉 첫 음절에서 혀를 너무 말지 않도록 주의하세요.",
        "在箭": "👉 4성-4성 리듬은 좋지만, 발음이 조금 뭉개지는 느낌이에요.",
        "在减": "👉 '见'의 성조가 올라가고 있어요. 위에서 아래로 뚝 떨어뜨리세요.",
        "在兼": "👉 '见'을 너무 높고 길게 발음했어요. 짧고 강하게 내리세요.",
        "再见": "👉 훌륭합니다! 4성-4성 리듬이 아주 좋습니다."
      }
    },
    "谢谢": {
      "candidates": ["谢谢", "写写", "鞋鞋", "些些", "歇歇", "下下", "屑屑", "席席", "细细", "写鞋"],
      "feedback": {
        "写写": "👉 성조가 3성처럼 들려요. 4성으로 강하게 '쎼' 하고 발음해보세요.",
        "些些": "👉 성조가 1성처럼 들려요. 뒤로 갈수록 힘을 빼며 짧게 발음하세요.",
        "歇歇": "👉 첫 번째 음을 너무 높게만 유지했어요. 아래로 툭 떨어뜨려야 해요.",
        "下下": "👉 모음이 'ia'가 아닌 'a'에 가까워요. '이' 소리를 살짝 섞어주세요.",
        "席席": "👉 성조가 2성처럼 올라가네요. 위에서 아래로 툭 떨어뜨리세요.",
        "细细": "👉 'x' 발음 뒤의 모음이 너무 얇게 들려요. 'ie' 발음을 명확히 하세요.",
        "屑屑": "👉 4성 기운이 너무 강해 부자연스러워요. 뒤는 경성으로 힘을 빼세요.",
        "写鞋": "👉 성조가 내려갔다 올라가고 있어요. 4성으로 뚝 떨어뜨려 보세요.",
        "谢谢": "👉 완벽해요! 아주 자연스러운 경성 처리입니다."
      }
    },
    "学校": {
      "candidates": ["学校", "学小", "学销", "削校", "雪校", "学晓", "学效", "学削", "穴校", "选校"],
      "feedback": {
        "学小": "👉 '校'의 성조가 3성처럼 들려요. 4성으로 확실하게 내려주세요.",
        "学销": "👉 '校'의 성조가 1성처럼 들려요. 강하게 내리꽂는 느낌으로 발음하세요.",
        "削校": "👉 '学'의 성조가 1성처럼 너무 높아요. 2성으로 올려주세요.",
        "雪校": "👉 '学'을 3성으로 너무 낮게 발음했어요. 부드럽게 상승시켜 보세요.",
        "学晓": "👉 성조가 너무 낮게 깔립니다. 마지막을 강하게 끊어주세요.",
        "选校": "👉 '学' 발음 시 입술 모양을 더 동그랗게 유지하며 '위' 소리를 내보세요.",
        "学效": "👉 거의 맞았어요! 조금만 더 부드럽게 2성에서 4성으로 넘어가 보세요.",
        "穴校": "👉 '学' 발음이 너무 짧고 강합니다. 좀 더 위로 밀어올리듯 발음하세요.",
        "学削": "👉 성조가 위아래로 너무 흔들립니다. 리듬을 다시 잡아보세요.",
        "学校": "👉 훌륭한 발음입니다! 성조 대비가 뚜렷해요."
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
      const finalClientScore = calculateClientScore(serverData, difficulty, practiceMode, language);
      
      const resultData = {
        type: "result",
        content: serverData.recognized_text,
        target: serverData.expected,
        score: finalClientScore,
        char_segments: serverData.char_segments || [],
        word_segments: serverData.word_segments || [],
        word_details: serverData.word_details || [],
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
        const expectedPhonemes = analysis.expected_phonemes || [];
        const recognizedPhonemes = analysis.recognized_phonemes || [];
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
    } else if (lang === "zh" && data.word_details) {
      // 중국어 채점 로직 (백엔드 정렬 데이터 기반)
      const details = data.word_details;
      const total = details.length;
      
      let pinyinMatchCount = 0;
      let toneMatchCount = 0;
      let charMatchCount = 0;
      
      details.forEach(d => {
        // d.is_correct: 병음 + 성조 모두 일치
        // d.tone_error: 병음은 일치하나 성조가 틀림
        if (d.is_correct || d.tone_error) {
          pinyinMatchCount++;
        }
        if (d.is_correct) {
          toneMatchCount++;
        }
        if (d.expected === d.actual) {
          charMatchCount++;
        }
      });

      const pMatchRatio = pinyinMatchCount / total;
      const tMatchRatio = toneMatchCount / total;
      const cMatchRatio = charMatchCount / total;
      
      if (diff <= 2) {
        // 1~2단계: 병음만 확인
        finalScore = Math.round(pMatchRatio * 100);
        logs.push(`• 난이도 1~2단계: 성조를 무시하고 병음 일치율로만 채점합니다.`);
        logs.push(`• 병음 일치: ${pinyinMatchCount} / ${total} (${Math.round(pMatchRatio * 100)}%)`);
      } else if (diff <= 4) {
        // 3~4단계: 병음 + 성조 확인 (50:50)
        finalScore = Math.round((pMatchRatio * 50) + (tMatchRatio * 50));
        logs.push(`• 난이도 3~4단계: 병음과 성조를 함께 확인합니다.`);
        logs.push(`• 병음 일치: ${pinyinMatchCount} / ${total}`);
        logs.push(`• 성조 일치: ${toneMatchCount} / ${total}`);
      } else {
        // 5단계: 병음 + 성조 + 한자 표기까지 확인 (40:30:30)
        finalScore = Math.round((pMatchRatio * 40) + (tMatchRatio * 30) + (cMatchRatio * 30));
        logs.push(`• 난이도 5단계: 병음, 성조, 한자 표기 일치 여부를 모두 확인합니다.`);
        logs.push(`• 병음 일치: ${pinyinMatchCount} / ${total}`);
        logs.push(`• 성조 일치: ${toneMatchCount} / ${total}`);
        logs.push(`• 한자 일치: ${charMatchCount} / ${total}`);
      }
      
      finalScore = Math.max(0, Math.min(100, finalScore));
      logs.push(`• 최종 점수: ${finalScore}점`);
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

      const langVariants = VARIANTS_FEEDBACK[language];
      if (langVariants && langVariants[targetWord]) {
        formData.append("candidates", JSON.stringify(langVariants[targetWord].candidates));
      }

      const response = await fetch(`${API_URL}/evaluate`, { method: "POST", body: formData });
      const data = await response.json();

      console.log("📋 서버 응답 데이터: ", data);

      if (data.error) {
        setScoringLogs([`❌ 오류 발생: ${data.error}`]);
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
