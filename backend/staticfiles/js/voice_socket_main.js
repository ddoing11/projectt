"use strict";

/**
 * 개선된 음성 키오스크 클라이언트 (최종본)
 * - 서버 MP3(base64) TTS: 큐로 직렬 재생 (겹침 방지)
 * - play_ding: JSON/문자열 모두 처리 (클라이언트에서만 소리 재생)
 * - 브라우저 STT: **최종 결과만 서버 전송**(interim off) → 중간 발화로 인한 중복 TTS/오작동 차단
 * - mic_on 후 STT 자동 재시작 윈도우
 * - Azure Speech SDK 사전 로드/토큰 프리페치 (실패 시 브라우저 TTS 폴백)
 */

console.log("✅ 개선된 음성 키오스크 클라이언트 시작");

let socket;
let recognition;
let recognizing = false;
let speechSynthesizer = null;
let isSpeaking = false;

let recognitionRetryCount = 0;
const MAX_RETRY_COUNT = 3;

// mic_on 이후 STT 자동 재시작을 허용할 시간창 (ms 단위 시각)
let sttRetryWindowUntil = 0;

// TTS 텍스트 중복 방지
let lastSpoken = { norm: "", at: 0 };

// 텍스트 TTS 큐(브라우저/Azure용)
let pendingTts = [];
let drainingTts = false;

// 서버에서 내려오는 MP3(base64) 오디오 큐 (겹침 방지)
let ttsAudioQueue = [];
let ttsAudioPlaying = false;

// TTS 초기화 상태
let ttsInitialized = false;
let useFallbackTTS = false;
let audioContextUnlocked = false;
let ttsPreWarmed = false;

// mic_on 스팸 방지 쿨다운
let lastMicRequestAt = 0;
const MIC_REQUEST_COOLDOWN_MS = 500;

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

async function playBase64Audio(b64) {
  const audioCtx =
    window._audioCtx || new (window.AudioContext || window.webkitAudioContext)();
  window._audioCtx = audioCtx;
  if (audioCtx.state === "suspended") await audioCtx.resume();

  const binary = atob(b64);
  const len = binary.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
  const buffer = await audioCtx.decodeAudioData(bytes.buffer);
  const src = audioCtx.createBufferSource();
  src.buffer = buffer;
  src.connect(audioCtx.destination);
  return new Promise((resolve) => {
    src.onended = resolve;
    src.start(0);
  });
}

function requestMicOn() {
  const now = Date.now();
  if (now - lastMicRequestAt < MIC_REQUEST_COOLDOWN_MS) {
    console.log("⏱️ mic_on 요청 쿨다운");
    return;
  }
  lastMicRequestAt = now;

  const s = window.voiceWS;
  if (s && s.readyState === WebSocket.OPEN) {
    s.send("request_mic_on");
  } else {
    console.warn("WebSocket not ready. mic_on 요청 보류");
  }
}

/* ------------------ 오디오 컨텍스트 ------------------ */
async function unlockAudioContext() {
  if (audioContextUnlocked) return;
  try {
    const audioContext =
      new (window.AudioContext || window.webkitAudioContext)();
    if (audioContext.state === "suspended") {
      console.log("🔓 오디오 컨텍스트 잠금 해제 시도");
      await audioContext.resume();
    }
    // 짧은 무음 재생으로 사용자 제스쳐 정책 우회
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.connect(gain);
    gain.connect(audioContext.destination);
    gain.gain.setValueAtTime(0, audioContext.currentTime);
    oscillator.start(audioContext.currentTime);
    oscillator.stop(audioContext.currentTime + 0.05);
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
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = "ko-KR";
    utter.rate = 0.9;
    utter.pitch = 1.0;
    utter.volume = 1.0;

    utter.onstart = () => {
      console.log("🔊 브라우저 TTS 시작:", text);
      isSpeaking = true;
    };
    utter.onend = () => {
      console.log("🔊 브라우저 TTS 종료:", text);
      isSpeaking = false;
      if (activateMic && !recognizing) {
        setTimeout(() => startRecognition(), 300);
      }
      resolve();
    };
    utter.onerror = (e) => {
      console.error("❌ 브라우저 TTS 오류:", e);
      isSpeaking = false;
      resolve();
    };

    try {
      speechSynthesis.cancel();
      speechSynthesis.speak(utter);
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
    const s = document.createElement("script");
    s.src = src;
    s.async = true;
    s.onload = resolve;
    s.onerror = reject;
    document.head.appendChild(s);
  });
}

async function loadAzureSpeechSDK() {
  if (window.SpeechSDK) {
    console.log("✅ Azure Speech SDK 이미 로드됨");
    return;
  }
  const existing = document.querySelector(
    'script[src*="microsoft.cognitiveservices.speech.sdk.bundle-min.js"]'
  );
  if (existing) {
    console.log("🔍 기존 Speech SDK 스크립트 발견, 대기 중...");
    await waitForSpeechSDK(8000);
    console.log("✅ 기존 스크립트로부터 Speech SDK 로드 완료");
    return;
  }
  const cdn = [
    "https://cdn.jsdelivr.net/npm/microsoft-cognitiveservices-speech-sdk@latest/distrib/browser/microsoft.cognitiveservices.speech.sdk.bundle-min.js",
  ];
  for (const url of cdn) {
    try {
      console.log("🔄 Speech SDK 로드 시도:", url);
      await loadScript(url);
      await waitForSpeechSDK(5000);
      console.log("✅ Speech SDK 로드 성공");
      return;
    } catch (e) {
      console.warn("❌ Speech SDK 로드 실패:", e);
    }
  }
  throw new Error("모든 Speech SDK URL 로드 실패");
}

/* ------------------ TTS 사전 초기화 ------------------ */
async function preWarmTTS() {
  if (ttsPreWarmed) return;
  console.log("🔥 TTS 사전 초기화 시작...");
  try {
    const loadPromise = loadAzureSpeechSDK();
    const timeoutPromise = new Promise((_, reject) =>
      setTimeout(() => reject(new Error("SDK 로드 타임아웃")), 5000)
    );
    await Promise.race([loadPromise, timeoutPromise]);

    console.log("🔄 TTS 토큰 사전 요청...");
    const tokenPromise = fetch("/api/tts-token/");
    const tokenTimeout = new Promise((_, reject) =>
      setTimeout(() => reject(new Error("토큰 요청 타임아웃")), 3000)
    );
    const res = await Promise.race([tokenPromise, tokenTimeout]);
    if (!res.ok) throw new Error(`TTS token fetch failed: ${res.status}`);
    const { token, region, error } = await res.json();
    if (error) throw new Error(`TTS token error: ${error}`);

    console.log("🔄 Azure TTS 사전 설정...");
    const speechConfig =
      window.SpeechSDK.SpeechConfig.fromAuthorizationToken(token, region);
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
    ttsPreWarmed = true;
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
      await new Promise((r) => setTimeout(r, 80));
    }
  } catch (e) {
    console.error("❌ TTS 큐 처리 오류:", e);
  } finally {
    drainingTts = false;
    isSpeaking = false;
    console.log("✅ TTS 큐 처리 완료 - isSpeaking: false");
  }
}

/* ------------------ 서버 MP3(base64) 재생 큐 ------------------ */
function enqueueTtsAudio(base64, activateMic = true) {
  ttsAudioQueue.push({ base64, activateMic });
  if (!ttsAudioPlaying) playNextTtsAudio();
}

function playNextTtsAudio() {
  if (ttsAudioPlaying) return;
  const item = ttsAudioQueue.shift();
  if (!item) return;

  ttsAudioPlaying = true;
  (async () => {
    if (!audioContextUnlocked) await unlockAudioContext();
    try {
      await playBase64Audio(item.base64);
    } catch (e) {
      console.warn("decodeAudio 실패, <audio> 대체 경로:", e);
      const audio = new Audio("data:audio/mpeg;base64," + item.base64);
      await audio.play().catch((err) =>
        console.error("fallback audio play() 실패:", err)
      );
      await new Promise((r) => (audio.onended = r));
    }

    ttsAudioPlaying = false;
    playNextTtsAudio();
  })();
}

/* ------------------ 딩 소리 ------------------ */
async function playDingAsync() {
  try {
    await new Audio("/static/sounds/ding.wav").play();
    console.log("🔔 딩 소리 재생");
  } catch (e) {
    console.log("❌ 딩 소리 재생 실패(무시 가능):", e);
  }
}

function playDing() {
  playDingAsync();
}

/* ------------------ STT ------------------ */
function startRecognition() {
  if (recognizing || isSpeaking) {
    console.log("⏭️ 이미 음성 인식 중이거나 TTS 중");
    return;
  }
  try {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      console.error("❌ 이 브라우저는 SpeechRecognition을 지원하지 않습니다.");
      return;
    }
    recognition = new SR();
    recognition.lang = "ko-KR";
    recognition.interimResults = false; // 최종만
    recognition.continuous = false;     // 한 발화 단위
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      console.log("🎙️ 음성 인식 시작");
      recognizing = true;
      recognitionRetryCount = 0;
    };

    recognition.onspeechstart = () => {
      console.log("🔉 사용자 발화 감지됨");
    };

    recognition.onresult = (event) => {
      const idx = event.results.length - 1;
      const res = event.results[idx];
      const transcript = ((res && res[0] && res[0].transcript) || "").trim();
      const isFinal = !!(res && res.isFinal);
      if (!transcript) return;

      console.log("🎤 인식된 텍스트:", transcript, "final:", isFinal);

      if (isFinal && socket?.readyState === WebSocket.OPEN) {
        socket.send(transcript);
      }
    };

    recognition.onerror = (event) => {
      console.error("❌ 음성 인식 오류:", event.error);
      recognizing = false;
      if (
        ["no-speech", "aborted", "network", "audio-capture"].includes(
          event.error
        ) &&
        recognitionRetryCount < MAX_RETRY_COUNT
      ) {
        recognitionRetryCount++;
        console.log(
          `🔄 음성 인식 재시도 (${recognitionRetryCount}/${MAX_RETRY_COUNT})`
        );
        setTimeout(() => {
          if (!isSpeaking) startRecognition();
        }, 1200);
      } else {
        console.log("❌ 음성 인식 최대 재시도 초과 또는 심각한 오류");
        recognitionRetryCount = 0;
      }
    };

    recognition.onend = () => {
      console.log("🛑 음성 인식 종료");
      recognizing = false;
      if (!isSpeaking && Date.now() < sttRetryWindowUntil) {
        console.log("🔄 onend → 자동 재시작");
        setTimeout(() => startRecognition(), 250);
      }
    };

    recognition.start();
  } catch (error) {
    console.error("❌ 음성 인식 시작 실패:", error);
    recognizing = false;
  }
}

function stopRecognition() {
  try {
    recognition?.stop?.();
  } catch {}
}

/* ------------------ WebSocket ------------------ */
function createWebSocket() {
  const WS_HOST = window.location.hostname || "127.0.0.1";
  const wsUrl = `ws://${WS_HOST}:8002`;

  socket = new WebSocket(wsUrl);
  window.voiceWS = socket;

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
          // 표 행 업데이트
          socket.send("read_cart");
          // 서버에 결제안내 TTS 요청
          socket.send("pay_all_ready");
          // 이어서 자동 응답 받을 수 있게 마이크 요청
          setTimeout(() => socket.send("request_mic_on"), 1000);
        }
      }, 200);
    }
  };

  socket.onmessage = async (event) => {
    console.log("📥 WebSocket 메시지:", event.data);

    if (typeof event.data === "string" && event.data.trim() === "play_ding") {
      playDing();
      return;
    }

    try {
      const data = JSON.parse(event.data);

      if (data.type === "tts_audio") {
        const { data: b64, activate_mic, play_ding } = data;
        stopRecognition();
        isSpeaking = true;

        await playBase64Audio(b64).catch((e) =>
          console.error("tts_audio 재생 실패:", e)
        );

        if (play_ding) await playDingAsync();

        isSpeaking = false;
        if (activate_mic) requestMicOn();
        return;
      }

      if (data.type === "text_to_speech") {
        const activateMic = data.activate_mic !== false;
        queueTts(data.text, activateMic);
        return;
      }

      if (data.type === "play_ding") {
        playDing();
        return;
      }

      if (data.type === "cart_items") {
        updateCartDisplay(data.items, data.total);
        return;
      }

      if (data.type === "cart_summary") {
        console.log("📋 장바구니 요약:", data.text);
        return;
      }
    } catch {
      // JSON 아닐 때 아래 switch
    }

    const text = (event.data || "").trim();

    switch (text) {
      case "mic_on":
        sttRetryWindowUntil = Date.now() + 8000;
        if (!isSpeaking) setTimeout(startRecognition, 150);
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
function updateCartDisplay(items, totalFromServer) {
  const tableContent = document.getElementById("cart-items");
  if (tableContent) {
    tableContent.innerHTML = items
      .map(
        (item) => `
      <div style="display: flex; justify-content: space-around; padding: 30px 80px; font-size: 42px;">
        <div style="width: 33%; text-align: center;">${item.name}</div>
        <div style="width: 33%; text-align: center;">${item.count}</div>
        <div style="width: 33%; text-align: center;">${Number(item.price).toLocaleString()}원</div>
      </div>`
      )
      .join("");
    console.log("🧾 장바구니 표시 업데이트");
  }

  // 총액 표시 갱신
  let total = Number(totalFromServer || 0);
  if (!total) {
    total = (items || []).reduce((s, it) => s + Number(it.price || 0) * Number(it.count || 1), 0);
  }
  const fmt = `${Number(total).toLocaleString()}원`;

  // 우선순위: #total-price → .total-price → [data-role="total"] → 텍스트 노드 추정
  const el =
    document.getElementById("total-price") ||
    document.querySelector(".total-price") ||
    document.querySelector('[data-role="total"]');

  if (el) {
    el.textContent = fmt;
  } else {
    // fallback: “총 0원” 처럼 표시된 요소를 찾고 교체 (간단 탐색)
    const candidates = Array.from(document.querySelectorAll("div,span,strong,b"));
    const target = candidates.find((n) => /총\s*[0-9,]*\s*원/.test(n.textContent || ""));
    if (target) target.textContent = `총 ${fmt}`;
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

  preWarmTTS();
  createWebSocket();

  if (/^\/order\/?$/.test(window.location.pathname)) {
    const disableVoice = localStorage.getItem("disableVoice") === "true";
    if (disableVoice) localStorage.removeItem("disableVoice");

    setTimeout(() => {
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send("resume_from_menu");
      }
    }, 300);
  }

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

  document.addEventListener("click", async () => {
    if (
      window.location.pathname === "/" ||
      window.location.pathname.includes("start")
    ) {
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
    pendingAudioCount: ttsAudioQueue.length,
    audioContextUnlocked,
    sttRetryWindowUntil,
  }),
  initTTS: () => ensureSynthReady(),
};
