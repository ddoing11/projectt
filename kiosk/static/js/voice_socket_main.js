"use strict";

/**
 * 개선된 음성 키오스크 클라이언트 (최종본)
 * - Azure Speech SDK 사전 로드 + 토큰 프리페치 (실패 시 브라우저 TTS로 폴백)
 * - 서버 TTS 바이너리(mp3) 수신 → 클라이언트 재생 (겹침 방지를 위한 큐)
 * - 문자열/JSON 모두의 play_ding 신호 처리
 * - 마이크 자동 on/off 제어 및 에코 억제
 */

console.log("✅ 개선된 음성 키오스크 클라이언트 시작");

let socket;
let recognition;
let recognizing = false;
let speechSynthesizer = null;
let isSpeaking = false;
let recognitionRetryCount = 0;
const MAX_RETRY_COUNT = 3;

// TTS 중복 방지
let lastSpoken = { norm: "", at: 0 };
let pendingTts = [];        // 텍스트 합성 큐(브라우저/azure 텍스트용)
let drainingTts = false;

// Azure TTS 초기화 상태
let ttsInitialized = false;
let useFallbackTTS = false; // Azure SDK 실패 시 브라우저 TTS 사용
let audioContextUnlocked = false;
let ttsPreWarmed = false;

// 서버에서 내려오는 mp3(base64) 오디오 큐 (겹침 방지)
const pendingAudio = [];
let playingAudio = false;

function normalizeText(s) {
  return (s || "")
    .toLowerCase()
    .replace(/\s/g, "")
    .replace(/[^\p{L}\p{N}]/gu, "");
}

function shouldSpeak(text, windowMs = 2500) {
  const norm = normalizeText(text);
  const now = Date.now();
  if (norm && norm === lastSpoken.norm && now - lastSpoken.at < windowMs) {
    console.log("🧯 중복 TTS 스킵");
    return false;
  }
  return true;
}

/* ------------------ 오디오 컨텍스트 ------------------ */
async function unlockAudioContext() {
  if (audioContextUnlocked) return;

  try {
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();

    if (audioContext.state === "suspended") {
      console.log("🔓 오디오 컨텍스트 잠금 해제 시도");
      await audioContext.resume();
    }

    // 무음 짧게 재생해 정책 우회
    const oscillator = audioContext.createOscillator();
    const gainNode = audioContext.createGain();
    oscillator.connect(gainNode);
    gainNode.connect(audioContext.destination);
    gainNode.gain.setValueAtTime(0, audioContext.currentTime);
    oscillator.frequency.setValueAtTime(440, audioContext.currentTime);
    oscillator.start(audioContext.currentTime);
    oscillator.stop(audioContext.currentTime + 0.1);

    audioContextUnlocked = true;
    console.log("✅ 오디오 컨텍스트 잠금 해제 완료");

    setTimeout(() => audioContext.close(), 1000);
  } catch (e) {
    console.warn("⚠️ 오디오 컨텍스트 잠금 해제 실패:", e);
  }
}

/* ------------------ 브라우저 TTS ------------------ */
function speakWithBrowserTTS(text, activateMic = true) {
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window)) {
      console.error("❌ 브라우저가 speechSynthesis를 지원하지 않음");
      resolve();
      return;
    }

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "ko-KR";
    utterance.rate = 0.9;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;

    utterance.onstart = () => {
      console.log("🔊 브라우저 TTS 시작:", text);
      isSpeaking = true;
    };

    utterance.onend = () => {
      console.log("🔊 브라우저 TTS 종료:", text);
      isSpeaking = false;
      if (activateMic && !recognizing) {
        setTimeout(() => startRecognition(), 300);
      }
      resolve();
    };

    utterance.onerror = (event) => {
      console.error("❌ 브라우저 TTS 오류:", event);
      isSpeaking = false;
      resolve();
    };

    try {
      speechSynthesis.cancel();
      speechSynthesis.speak(utterance);
    } catch (err) {
      console.error("❌ 브라우저 TTS 호출 실패:", err);
      resolve();
    }
  });
}

/* ------------------ Azure Speech SDK 로드 ------------------ */
function waitForSpeechSDK(timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    (function poll() {
      if (window.SpeechSDK) return resolve();
      if (Date.now() - start >= timeoutMs) {
        return reject(new Error("SpeechSDK 로드 대기 타임아웃"));
      }
      setTimeout(poll, 100);
    })();
  });
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = resolve;
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

async function loadAzureSpeechSDK() {
  if (window.SpeechSDK) {
    console.log("✅ Azure Speech SDK 이미 로드됨");
    return;
  }

  const existingScript = document.querySelector(
    'script[src*="microsoft.cognitiveservices.speech.sdk.bundle-min.js"]'
  );
  if (existingScript) {
    console.log("🔍 기존 Speech SDK 스크립트 발견, 대기 중...");
    await waitForSpeechSDK(8000);
    console.log("✅ 기존 스크립트로부터 Speech SDK 로드 완료");
    return;
  }

  const cdnUrls = [
    "https://cdn.jsdelivr.net/npm/microsoft-cognitiveservices-speech-sdk@latest/distrib/browser/microsoft.cognitiveservices.speech.sdk.bundle-min.js",
  ];

  for (const url of cdnUrls) {
    try {
      console.log(`🔄 Speech SDK 로드 시도: ${url}`);
      await loadScript(url);
      await waitForSpeechSDK(5000);
      console.log("✅ Speech SDK 로드 성공");
      return;
    } catch (e) {
      console.warn(`❌ ${url} 로드 실패:`, e);
    }
  }

  throw new Error("모든 Speech SDK URL 로드 실패");
}

/* ------------------ TTS 사전 초기화 ------------------ */
async function preWarmTTS() {
  if (ttsPreWarmed) return;

  console.log("🔥 TTS 사전 초기화 시작...");

  try {
    // SDK 로드 (타임아웃 보호)
    const loadPromise = loadAzureSpeechSDK();
    const timeoutPromise = new Promise((_, reject) =>
      setTimeout(() => reject(new Error("SDK 로드 타임아웃")), 5000)
    );
    await Promise.race([loadPromise, timeoutPromise]);

    // 토큰 프리페치
    console.log("🔄 TTS 토큰 사전 요청...");
    const tokenPromise = fetch("/api/tts-token/");
    const tokenTimeout = new Promise((_, reject) =>
      setTimeout(() => reject(new Error("토큰 요청 타임아웃")), 3000)
    );
    const res = await Promise.race([tokenPromise, tokenTimeout]);
    if (!res.ok) throw new Error(`TTS token fetch failed: ${res.status}`);
    const { token, region, error } = await res.json();
    if (error) throw new Error(`TTS token error: ${error}`);

    // SpeechSynthesizer 생성 (스피커 출력)
    console.log("🔄 Azure TTS 사전 설정...");
    const speechConfig = window.SpeechSDK.SpeechConfig.fromAuthorizationToken(
      token,
      region
    );
    speechConfig.speechSynthesisVoiceName = "ko-KR-SunHiNeural";
    const audioConfig = window.SpeechSDK.AudioConfig.fromDefaultSpeakerOutput();
    speechSynthesizer = new window.SpeechSDK.SpeechSynthesizer(
      speechConfig,
      audioConfig
    );

    ttsInitialized = true;
    ttsPreWarmed = true;
    useFallbackTTS = false;

    console.log("🔥 TTS 사전 초기화 완료 - 즉시 사용 가능");
  } catch (e) {
    console.warn("⚠️ TTS 사전 초기화 실패, 브라우저 TTS 사용:", e);
    useFallbackTTS = true;
    ttsPreWarmed = true; // 실패해도 이후 대기 방지
  }
}

async function ensureSynthReady() {
  if (ttsPreWarmed && speechSynthesizer) {
    console.log("⚡ TTS 이미 준비됨 (사전 초기화)");
    return true;
  }
  return await preWarmTTS();
}

/* ------------------ 텍스트 TTS (브라우저/Azure) ------------------ */
async function speakText(text, activateMic = true) {
  if (!shouldSpeak(text)) return;

  console.log(
    `🔊 TTS 실행: "${text}" (사전초기화: ${ttsPreWarmed}, fallback: ${useFallbackTTS})`
  );

  try {
    isSpeaking = true;
    if (recognition && recognizing) {
      recognition.stop();
      recognizing = false;
    }

    lastSpoken = { norm: normalizeText(text), at: Date.now() };

    if (!ttsPreWarmed && !useFallbackTTS) {
      console.log("⏳ Azure TTS 초기화 대기 중...");
      let waitCount = 0;
      while (!ttsPreWarmed && !useFallbackTTS && waitCount < 30) {
        await new Promise((r) => setTimeout(r, 100));
        waitCount++;
      }
      console.log(
        `⏳ 대기 완료: ttsPreWarmed=${ttsPreWarmed}, waitCount=${waitCount}`
      );
    }

    if (useFallbackTTS || !ttsPreWarmed) {
      console.log("🔄 브라우저 TTS 사용");
      await speakWithBrowserTTS(text, activateMic);
      return;
    }

    // Azure SDK 사용
    await new Promise(async (resolve) => {
      const finish = () => {
        console.log("🔊 Azure TTS 완료");
        isSpeaking = false;
        if (activateMic && !recognizing) {
          setTimeout(() => startRecognition(), 300);
        }
        resolve();
      };

      if (!speechSynthesizer) {
        console.warn("❌ speechSynthesizer 없음, 브라우저 TTS로 대체");
        await speakWithBrowserTTS(text, activateMic);
        resolve();
        return;
      }

      if (!audioContextUnlocked) await unlockAudioContext();

      console.log("⚡ Azure TTS 즉시 실행");
      try {
        speechSynthesizer.speakTextAsync(
          text,
          () => {
            console.log("✅ Azure TTS 성공");
            finish();
          },
          (err) => {
            console.error("❌ Azure TTS 오류:", err);
            finish();
          }
        );
      } catch (synthError) {
        console.error("❌ speakTextAsync 호출 오류:", synthError);
        finish();
      }
    });
  } catch (err) {
    console.error("❌ TTS 처리 오류:", err);
    isSpeaking = false;
  }
}

function queueTts(text, activateMic = true) {
  console.log("🗂️ TTS 큐잉:", text);
  pendingTts.push({ text, activateMic });
  drainTts();
}

async function drainTts() {
  if (drainingTts) {
    console.log("⏭️ 이미 TTS 처리 중, 스킵");
    return;
  }

  console.log("🔄 TTS 큐 처리 시작");
  drainingTts = true;

  try {
    while (pendingTts.length) {
      const { text, activateMic } = pendingTts.shift();
      console.log("▶️ TTS 시작:", text);
      await speakText(text, activateMic);
      console.log("⏹️ TTS 종료:", text);
      await new Promise((r) => setTimeout(r, 100));
    }
  } catch (error) {
    console.error("❌ TTS 큐 처리 오류:", error);
  } finally {
    drainingTts = false;
    isSpeaking = false;
    console.log("✅ TTS 큐 처리 완료 - isSpeaking: false");
  }
}

/* ------------------ 서버 mp3(base64) 재생 큐 ------------------ */
function enqueueAudioB64(b64, activateMic = true) {
  pendingAudio.push({ b64, activateMic });
  drainAudioQueue();
}

async function drainAudioQueue() {
  if (playingAudio) return;
  playingAudio = true;

  try {
    while (pendingAudio.length > 0) {
      const { b64, activateMic } = pendingAudio.shift();
      if (!audioContextUnlocked) await unlockAudioContext();
      await new Promise((resolve) => {
        const audio = new Audio("data:audio/mpeg;base64," + b64);
        audio.onended = resolve;
        audio.onerror = (e) => {
          console.error("❌ 오디오 재생 오류:", e);
          resolve();
        };
        audio.play().catch((err) => {
          console.error("❌ 오디오 play() 실패:", err);
          resolve();
        });
      });

      // 각 오디오 종료 후 마이크 온 (서버가 activate_mic=false로 보내면 off 유지)
      if (activateMic && socket?.readyState === WebSocket.OPEN) {
        socket.send("mic_on");
      }
    }
  } finally {
    playingAudio = false;
  }
}

/* ------------------ 딩 소리 ------------------ */
function playDing() {
  try {
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = audioContext.createOscillator();
    const gainNode = audioContext.createGain();

    oscillator.connect(gainNode);
    gainNode.connect(audioContext.destination);

    oscillator.frequency.value = 800;
    oscillator.type = "sine";
    gainNode.gain.setValueAtTime(0.15, audioContext.currentTime);
    gainNode.gain.exponentialRampToValueAtTime(
      0.01,
      audioContext.currentTime + 0.25
    );

    oscillator.start(audioContext.currentTime);
    oscillator.stop(audioContext.currentTime + 0.25);

    console.log("🔔 딩 소리 재생");
    setTimeout(() => audioContext.close(), 800);
  } catch (e) {
    console.log("❌ 딩 소리 재생 실패:", e);
  }
}

/* ------------------ STT ------------------ */
function startRecognition() {
  if (recognizing || isSpeaking) {
    console.log("⏭️ 이미 음성 인식 중이거나 TTS 중");
    return;
  }

  try {
    recognition = new (window.SpeechRecognition ||
      window.webkitSpeechRecognition)();
    recognition.lang = "ko-KR";
    recognition.interimResults = false;
    recognition.maxAlternatives = 3;
    recognition.continuous = false;

    recognition.onstart = () => {
      console.log("🎙️ 음성 인식 시작");
      recognizing = true;
      recognitionRetryCount = 0;
    };

    recognition.onspeechstart = () => {
      console.log("🔉 사용자 발화 감지됨");
    };

    recognition.onresult = (event) => {
      const results = event.results[event.results.length - 1];
      const result = results[0].transcript.trim();
      const confidence = results[0].confidence;

      console.log("🎤 인식된 텍스트:", result, "신뢰도:", confidence);

      if (confidence < 0.5 && recognitionRetryCount < MAX_RETRY_COUNT) {
        console.log("⚠️ 신뢰도 낮음, 다시 시도");
        recognitionRetryCount++;
        setTimeout(() => {
          if (!isSpeaking) startRecognition();
        }, 1000);
        return;
      }

      const normRes = normalizeText(result);
      if (lastSpoken.norm && normRes === lastSpoken.norm) {
        console.log("🪄 TTS 에코로 판단 → 무시");
        setTimeout(() => {
          if (!isSpeaking) startRecognition();
        }, 1000);
        return;
      }

      if (!result.trim()) {
        console.log("⚠️ 빈 결과, 다시 시도");
        setTimeout(() => {
          if (!isSpeaking) startRecognition();
        }, 1000);
        return;
      }

      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(result);
        recognitionRetryCount = 0;
      }
    };

    recognition.onerror = (event) => {
      console.error("❌ 음성 인식 오류:", event.error);
      recognizing = false;

      if (
        ["no-speech", "aborted", "network"].includes(event.error) &&
        recognitionRetryCount < MAX_RETRY_COUNT
      ) {
        recognitionRetryCount++;
        console.log(
          `🔄 음성 인식 재시도 (${recognitionRetryCount}/${MAX_RETRY_COUNT})`
        );
        setTimeout(() => {
          if (!isSpeaking) startRecognition();
        }, 2000);
      } else {
        console.log("❌ 음성 인식 최대 재시도 초과 또는 심각한 오류");
        recognitionRetryCount = 0;
      }
    };

    recognition.onend = () => {
      console.log("🛑 음성 인식 종료");
      recognizing = false;
    };

    recognition.start();
  } catch (error) {
    console.error("❌ 음성 인식 시작 실패:", error);
    recognizing = false;
  }
}

function stopRecognition() {
  if (recognition && recognizing) {
    recognition.stop();
    recognizing = false;
    recognitionRetryCount = 0;
  }
}

/* ------------------ WebSocket ------------------ */
function createWebSocket() {
  // 같은 호스트면 로컬 포트 사용, 외부면 ngrok 주소(필요 시 수정)
  const sameHost =
    window.location.hostname === "127.0.0.1" ||
    window.location.hostname === "localhost";
  const WS_HOST = sameHost ? "127.0.0.1" : window.location.hostname;
  const wsUrl = sameHost
    ? `ws://${WS_HOST}:8002`
    : `ws://${WS_HOST}:8002`; // wss를 쓰려면 서버에서도 TLS 필요

  socket = new WebSocket(wsUrl);

  socket.onopen = () => {
    console.log("✅ WebSocket 연결됨");

    const clientId = localStorage.getItem("client_id") || crypto.randomUUID();
    localStorage.setItem("client_id", clientId);

    socket.send(
      JSON.stringify({
        type: "page_info",
        path: window.location.pathname,
        client_id: clientId,
      })
    );

    if (window.location.pathname === "/pay_all") {
      setTimeout(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send("read_cart");
          setTimeout(() => socket.send("request_mic_on"), 1000);
        }
      }, 200);
    }
  };

  socket.onmessage = (event) => {
    console.log("📥 WebSocket 메시지:", event.data);

    // 문자열로 오는 play_ding 호환
    if (typeof event.data === "string" && event.data.trim() === "play_ding") {
      playDing();
      return;
    }

    try {
      const data = JSON.parse(event.data);

      // 서버 mp3(base64) → 재생 큐
      if (data.type === "tts_audio") {
        const activateMic = data.activate_mic !== false;
        enqueueAudioB64(data.data, activateMic);
        return;
      }

      // 텍스트 TTS(브라우저/Azure 텍스트 합성 경로)
      if (data.type === "text_to_speech") {
        const activateMic = data.activate_mic !== false;
        queueTts(data.text, activateMic);
        return;
      }

      // JSON play_ding
      if (data.type === "play_ding") {
        playDing();
        return;
      }

      if (data.type === "cart_items") {
        updateCartDisplay(data.items);
        return;
      }

      if (data.type === "cart_summary") {
        console.log("📋 장바구니 요약:", data.text);
        return;
      }
    } catch {
      // JSON이 아니면 아래 텍스트 스위치로 처리
    }

    const text = (event.data || "").trim();

    switch (text) {
      case "mic_on":
        if (!isSpeaking) setTimeout(startRecognition, 300);
        break;

      case "mic_off":
        stopRecognition();
        break;

      case "goto_menu":
        localStorage.setItem("continueRecognition", "true");
        window.location.href = "/order";
        break;

      case "go_to_pay": {
        const clientId = localStorage.getItem("client_id");
        if (clientId) location.assign(`/pay_all?client_id=${clientId}`);
        break;
      }

      case "go_to_order2":
        localStorage.setItem("continueRecognition", "false");
        window.location.href = "/order2/";
        break;

      case "go_to_done":
        window.location.href = "/done";
        break;

      case "goto_start":
        window.location.href = "/start";
        break;

      case "set_disable_voice":
        localStorage.setItem("disableVoice", "true");
        break;

      case "popup_payment":
        showPaymentPopup();
        break;

      default:
        console.log("📝 기타 메시지:", text);
        break;
    }
  };

  socket.onclose = () => {
    console.warn("🔌 WebSocket 연결 종료됨");
    setTimeout(() => {
      if (!socket || socket.readyState === WebSocket.CLOSED) {
        console.log("🔄 WebSocket 재연결 시도");
        createWebSocket();
      }
    }, 3000);
  };

  socket.onerror = (error) => {
    console.error("❌ WebSocket 오류:", error);
  };
}

/* ------------------ UI 보조 ------------------ */
function updateCartDisplay(items) {
  const tableContent = document.getElementById("cart-items");
  if (tableContent) {
    tableContent.innerHTML = items
      .map(
        (item) => `
      <div style="display: flex; justify-content: space-around; padding: 30px 80px; font-size: 42px;">
        <div style="width: 33%; text-align: center;">${item.name}</div>
        <div style="width: 33%; text-align: center;">${item.count}</div>
        <div style="width: 33%; text-align: center;">${Number(
          item.price
        ).toLocaleString()}원</div>
      </div>`
      )
      .join("");
    console.log("🧾 장바구니 표시 업데이트");
  }
}

function showPaymentPopup() {
  const popup = document.getElementById("popup-overlay");
  if (popup) {
    popup.style.display = "flex";
    setTimeout(() => (popup.style.display = "none"), 8000);
  }
}

/* ------------------ 부트스트랩 ------------------ */
document.addEventListener("DOMContentLoaded", () => {
  console.log("📄 페이지 로드됨:", window.location.pathname);

  // TTS 사전 초기화 즉시 시작
  preWarmTTS();

  // WebSocket 연결
  createWebSocket();

  // order 페이지 복구 시나리오
  if (/^\/order\/?$/.test(window.location.pathname)) {
    const disableVoice = localStorage.getItem("disableVoice") === "true";
    if (disableVoice) localStorage.removeItem("disableVoice");

    setTimeout(() => {
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send("resume_from_menu");
      }
    }, 300);
  }

  // 결제 버튼 이벤트
  const payButton = document.querySelector(".pay-button");
  if (payButton) {
    payButton.addEventListener("click", () => {
      const clientId = localStorage.getItem("client_id");
      if (!clientId) {
        alert("client_id가 없습니다.");
        return;
      }
      const path = window.location.pathname;
      if (path.startsWith("/order2/")) {
        window.location.href = `/pay_all2?client_id=${clientId}`;
      } else if (path.startsWith("/order")) {
        window.location.href = `/pay_all?client_id=${clientId}`;
      }
    });
  }

  // start 페이지 클릭 → 오디오 컨텍스트 해제 + 서버에 시작 알림
  document.addEventListener("click", async () => {
    if (window.location.pathname === "/" || window.location.pathname.includes("start")) {
      console.log("✅ start 페이지에서 클릭됨");
      await unlockAudioContext();
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send("start_order");
      }
    }
  });
});

/* ------------------ 전역 디버그 도우미 ------------------ */
window.debugVoice = {
  startSTT: () => startRecognition(),
  stopSTT: () => stopRecognition(),
  testTTS: (text) => queueTts(text || "테스트 음성입니다"),
  testBrowserTTS: (text) => speakWithBrowserTTS(text || "브라우저 TTS 테스트"),
  unlockAudio: () => unlockAudioContext(),
  preWarmTTS: () => preWarmTTS(),
  checkTTSToken: async () => {
    try {
      const res = await fetch("/api/tts-token/");
      const data = await res.json();
      console.log("TTS 토큰:", data);
      return data;
    } catch (e) {
      console.error("TTS 토큰 오류:", e);
      return null;
    }
  },
  getState: () => ({
    recognizing,
    isSpeaking,
    socketState: socket?.readyState,
    lastSpoken,
    ttsInitialized,
    ttsPreWarmed,
    useFallbackTTS,
    speechSynthesizer: !!speechSynthesizer,
    pendingTtsCount: pendingTts.length,
    pendingAudioCount: pendingAudio.length,
    audioContextUnlocked,
  }),
  initTTS: () => ensureSynthReady(),
};
