"use strict";

console.log("✅ JS 작동 중입니다");

let socket;
let recognition;
let recognizing = false;
let resumeHandled = false; // (예약) 상태 복원 응답 후 인식 시작 여부
let isStarting = false;
let pendingMicOn = false;
let micOnTimer = null;
let sttClosePromise = null;

// === TTS 중복 방지 & 상태 ===
let lastSpoken = { norm: "", at: 0 };
let lastQueued = { norm: "", at: 0 }; // 큐 적재 디듀프 기준
let isSpeaking = false;

function normalizeText(s) {
  return (s || "")
    .toLowerCase()
    .replace(/\s/g, "")
    .replace(/[^\p{L}\p{N}]/gu, ""); // 글자/숫자 외 제거
}

// 최근 2.5초 내 같은 멘트면 말하지 않기 (발화 기준)
function shouldSpeak(text, windowMs = 2500) {
  const norm = normalizeText(text);
  const now = Date.now();
  if (norm && norm === lastSpoken.norm && now - lastSpoken.at < windowMs) {
    console.log("🧯 디듀프: 같은 문장 최근에 재생됨 → 스킵");
    return false;
  }
  return true;
}

// 큐 적재 시점 디듀프 (대기열/최근발화 모두 고려)
function shouldQueue(text, windowMs = 2000) {
  const norm = normalizeText(text);
  const now = Date.now();
  // 직전 큐 적재와 동일 & 근접 시간 → 스킵
  if (norm && norm === lastQueued.norm && now - lastQueued.at < windowMs) return false;
  // 대기열에 이미 동일 멘트 있으면 스킵
  if (pendingTts.some(t => normalizeText(t) === norm)) return false;
  // 방금(최근 2.5초) 말한 것과도 같으면 스킵
  if (norm && norm === lastSpoken.norm && now - lastSpoken.at < 2500) return false;
  lastQueued = { norm, at: now };
  return true;
}

function stopRecognitionIfNeeded() {
  if (!recognition || !recognizing) return Promise.resolve();
  if (sttClosePromise) return sttClosePromise;

  sttClosePromise = new Promise((resolve) => {
    const prevOnend = recognition.onend;
    recognition.onend = (e) => {
      recognizing = false;
      sttClosePromise = null;
      if (typeof prevOnend === "function") prevOnend.call(recognition, e);
      resolve();
    };
    try { recognition.stop(); } catch {}
  });
  return sttClosePromise;
}

// === 명령 문자열(서버 제어용) ===
const COMMANDS = new Set([
  "popup_payment","mic_off","mic_on","goto_menu","go_to_pay",
  "go_to_order2","set_resume_flag","go_to_done","goto_start","set_disable_voice"
]);

// === Azure Speech SDK 동적 로더 & 폴백 ===
const SPEECH_SDK_PRIMARY = "https://aka.ms/csspeech/jsbrowserpackagestandard";
const SPEECH_SDK_FALLBACK = "https://cdn.jsdelivr.net/npm/microsoft-cognitiveservices-speech-sdk/distrib/browser/microsoft.cognitiveservices.speech.sdk.bundle-min.js";

function loadScriptOnce(src, id) {
  return new Promise((resolve, reject) => {
    let el = document.getElementById(id);
    if (!el) {
      el = document.createElement("script");
      el.src = src;
      el.id = id;
      el.async = true;
      el.onload = () => resolve();
      el.onerror = (e) => reject(e);
      document.head.appendChild(el);
    } else {
      el.addEventListener("load", () => resolve());
      el.addEventListener("error", (e) => reject(e));
    }
  });
}

function waitForSpeechSDK(timeoutMs = 15000, intervalMs = 100) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    (function check() {
      if (window.SpeechSDK) return resolve();
      if (Date.now() - start > timeoutMs) return reject(new Error("Speech SDK not loaded in time"));
      setTimeout(check, intervalMs);
    })();
  });
}

async function loadAzureSpeechSDK() {
  if (window.SpeechSDK) return;

  // head에 SDK 스크립트가 없다면 우선 기본 CDN 로드
  const hasAnySdkTag = Array.from(document.scripts).some(s =>
    (s.src || "").includes("csspeech") || (s.src || "").includes("microsoft.cognitiveservices.speech.sdk")
  );

  try {
    if (!hasAnySdkTag) {
      await loadScriptOnce(SPEECH_SDK_PRIMARY, "speech-sdk");
    }
    await waitForSpeechSDK(7000, 100);
  } catch (e) {
    console.warn("Primary SDK load failed or timed out. Falling back…", e);
    try {
      await loadScriptOnce(SPEECH_SDK_FALLBACK, "speech-sdk-fallback");
      await waitForSpeechSDK(7000, 100);
    } catch (e2) {
      console.error("Fallback SDK load failed:", e2);
      throw e2;
    }
  }
}

// === TTS 준비 & 큐 ===
let speechSynthesizer = null;
let pendingTts = [];
let drainingTts = false;

async function ensureSynthReady() {
  if (speechSynthesizer) return true;
  try {
    await loadAzureSpeechSDK();
    const res = await fetch("/api/tts-token/");
    const data = await res.json();
    if (!res.ok || data.error) {
      console.error("TTS token error:", res.status, data?.error);
      return false;
    }
    const { token, region } = data;
    const speechConfig = window.SpeechSDK.SpeechConfig.fromAuthorizationToken(token, region);
    speechConfig.speechSynthesisVoiceName = "ko-KR-SunHiNeural";
    const audioConfig = window.SpeechSDK.AudioConfig.fromDefaultSpeakerOutput();
    speechSynthesizer = new window.SpeechSDK.SpeechSynthesizer(speechConfig, audioConfig);
    console.log("🔊 Speech synthesizer ready");
    return true;
  } catch (e) {
    console.error("❌ ensureSynthReady failed:", e);
    return false;
  }
}

async function speakTextAsync(text) {
  try {
    isSpeaking = true;

    // STT 완전 종료 대기 + 잠깐 쉬기
    await stopRecognitionIfNeeded();
    await new Promise(r => setTimeout(r, 140));

    // ✅ "정말 말하기 직전"에만 디듀프 기준 기록
    lastSpoken = { norm: normalizeText(text), at: Date.now() };

    let triedRetry = false;

    return new Promise((resolve) => {
      const finish = () => {
        isSpeaking = false;
        if (micOnTimer) { clearTimeout(micOnTimer); micOnTimer = null; }
        if (pendingMicOn && !recognizing && !isStarting) {
          pendingMicOn = false;
          micOnTimer = setTimeout(() => {
            micOnTimer = null;
            if (!isSpeaking) startRecognition();
          }, 120);
        }
      };

      speechSynthesizer.speakTextAsync(
        text,
        () => { finish(); resolve(); },
        async (err) => {
          console.error("❌ Speech synthesis error:", err);

          // ⛑️ 출력 취소(무음) 등일 때 1회 재시도
          if (!triedRetry) {
            triedRetry = true;
            await new Promise(r => setTimeout(r, 200));
            speechSynthesizer.speakTextAsync(
              text,
              () => { finish(); resolve(); },
              (err2) => { console.error("❌ 재시도도 실패:", err2); finish(); resolve(); }
            );
            return;
          }

          finish();
          resolve();
        }
      );
    });
  } catch (err) {
    console.error("❌ Speech synthesis threw:", err);
    isSpeaking = false;
  }
}

function say(text) {
  if (!text) return;
  console.log("🗂️ TTS 큐잉:", text);
  pendingTts.push(text);
  drainTts();
}

async function drainTts() {
  if (drainingTts) return;
  drainingTts = true;

  if (!(await ensureSynthReady())) { setTimeout(() => { drainingTts = false; drainTts(); }, 1000); return; }

  while (pendingTts.length) {
    const t = pendingTts.shift();
    if (!shouldSpeak(t)) continue; // 발화 직전 안전 디듀프
    console.log("▶️ TTS 시작:", t);
    await speakTextAsync(t);
    console.log("⏹️ TTS 종료:", t);
    await new Promise(r => setTimeout(r, 120));
  }
  drainingTts = false;
}

// showPopupWithRetry unchanged
function showPopupWithRetry(retryCount = 10) {
  const popup = document.getElementById("popup-overlay");
  if (popup) {
    popup.style.display = "flex";
    console.log("✅ popup-overlay 표시 완료");
    setTimeout(() => {
      window.location.href = "/done";
    }, 5000);
  } else if (retryCount > 0) {
    console.warn(`❌ popup-overlay 없음 → 재시도 (${11 - retryCount})`);
    setTimeout(() => showPopupWithRetry(retryCount - 1), 100);
  } else {
    console.error("❌ popup-overlay 끝내 찾을 수 없음. 팝업 표시 실패");
  }
}

function createWebSocket() {
  const wsUrl =
    (window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost")
      ? "ws://127.0.0.1:8003"    // 메시지 라우터 포트
      : "wss://mykiosk8002.jp.ngrok.io"; // 배포 주소에 맞춰 포트도 수정
  socket = new WebSocket(wsUrl);

  socket.onopen = () => {
    console.log("✅ WebSocket 연결됨");
    console.log("📡 새 WebSocket 연결됨 (path:", window.location.pathname, ")");

    const pagePath = window.location.pathname;
    const clientId = localStorage.getItem("client_id");

    socket.send(JSON.stringify({
      type: "page_info",
      path: window.location.pathname,
      client_id: clientId
    }));

    if (pagePath === "/pay_all") {
      // 연결 안정화 후 관련 메시지 전송
      setTimeout(() => {
        if (socket.readyState === WebSocket.OPEN) {
          console.log("🧾 /pay_all 페이지에서 초기 메시지 전송");
          socket.send("pay_all_ready");
          socket.send("read_cart");

          // 💡 질문 TTS 끝날 즈음에만 요청 (0.5~1초 후)
          setTimeout(() => {
            socket.send("request_mic_on");
          }, 1000);
        }
      }, 200);
    }
  };

  socket.onmessage = (event) => {
    console.log("📥 WebSocket 메시지 수신:", event.data);

    // cart_items JSON 먼저 시도
    try {
      const parsed = JSON.parse(event.data);
      if (parsed.type === "cart_items") {
        const items = parsed.items || [];
        const tableContent = document.getElementById("cart-items");
        if (tableContent) {
          tableContent.innerHTML = items.map(item => `
            <div style="display: flex; justify-content: space-around; padding: 30px 80px; font-size: 42px;">
              <div style="width: 33%; text-align: center;">${item.name}</div>
              <div style="width: 33%; text-align: center;">${item.count}</div>
              <div style="width: 33%; text-align: center;">${Number(item.price).toLocaleString()}원</div>
            </div>
          `).join('');
          console.log("🧾 장바구니 항목 렌더링 완료:", items);

          // ✅ 렌더링 끝난 후 서버에 TTS 요청
          setTimeout(() => {
            if (socket?.readyState === WebSocket.OPEN) {
              socket.send("request_cart_summary");
            }
          }, 300);
        }
        return;
      }
    } catch (e) {
      console.warn("⚠️ JSON 파싱 실패. 일반 메시지 처리 시도:", event.data);
    }

    const text = (event.data || "").trim();
    console.log('📩 서버 응답:', text);

    // === 명령 처리 ===
    if (text === "popup_payment") {
      console.log("💳 결제 팝업 띄우기");
      const popup = document.getElementById("popup-overlay");
      if (popup) {
        popup.style.display = "block";
        setTimeout(() => { popup.style.display = "none"; }, 8000);
      } else {
        console.warn("❗ 팝업 요소를 찾을 수 없음: popup-overlay");
      }
      return;
    }

    if (text === "mic_off") {
      console.log("🔇 서버 지시: 마이크 OFF");
      if (recognition) {
        try {
          recognizing = false;
          recognition.stop();
        } catch (error) {
          console.error("❌ recognition.stop() 오류:", error);
        }
      }
      return;
    }

    if (text === "mic_on") {
      const isOrderPage = /^\/order\/?$/.test(window.location.pathname);
      const disableVoice = localStorage.getItem("disableVoice") === "true";
      if (isOrderPage && disableVoice) {
        console.log("🚫 /order에서 disableVoice=true → mic_on 무시");
        return;
      }

      // 이전 예약 정리
      if (micOnTimer) { clearTimeout(micOnTimer); micOnTimer = null; }

      // 🔸 말하는 중이거나(STT 끄는 중도 포함) → 나중에 켬
      if (isSpeaking || sttClosePromise) {
        console.log("⏸️ TTS/STT 정리 중 → mic_on 대기");
        pendingMicOn = true;
        return;
      }

      console.log("🔊 서버 지시: 마이크 ON");

      if (recognizing || isStarting) {
        console.log("⏭️ 이미 마이크 켜는 중이거나 켜짐 상태 → 무시");
        return;
      }

      if (recognition && recognizing) {
        try { recognition.abort(); } catch (e) { console.warn("⚠️ abort 중 오류:", e); }
        recognizing = false;
      }

      micOnTimer = setTimeout(() => {
        micOnTimer = null;
        if (isSpeaking || sttClosePromise) { // 마지막 안전장치
          pendingMicOn = true;
          return;
        }
        startRecognition();
      }, 200);
      return;
    }

    if (text === "goto_menu") {
      console.log("📢 서버 지시: /order 페이지로 이동");
      localStorage.setItem("continueRecognition", "true");
      window.location.href = "/order";
      return;
    }

    if (text === "go_to_pay") {
      const clientId2 = localStorage.getItem("client_id");
      if (clientId2) {
        console.log("📢 서버 지시: /pay_all 페이지로 이동");
        location.assign(`/pay_all?client_id=${clientId2}`);
      } else {
        console.warn("❌ client_id가 없습니다. 이동 취소");
      }
      return;
    }

    if (text === "go_to_order2") {
      console.log("📢 서버 지시: /order2 페이지로 이동");
      localStorage.setItem("continueRecognition", "false");
      window.location.href = "/order2/";
      return;
    }

    if (text === "set_resume_flag") {
      console.log("🧭 resume 플래그 설정");
      localStorage.setItem("continueRecognition", "true");
      return;
    }

    console.log("🧭 현재 받은 메시지:", text);

    if (text === "go_to_done") {
      console.log("✅ done 페이지로 이동 시도");
      window.location.href = "/done";
      return;
    }

    if (text === "goto_start") {
      console.log("📢 서버 지시: /start 페이지로 이동");
      if (recognizing && recognition) {
        recognizing = false;
        recognition.stop();
        console.log("🛑 음성 인식 중단 후 페이지 이동");
      }
      window.location.href = "/start";
      return;
    }

    if (text === "set_disable_voice") {
      console.log("🚫 음성 비활성화 플래그 설정");
      localStorage.setItem("disableVoice", "true");
      return;
    }

    // === 안내 문구 처리 (단 한 곳에서만 큐잉) ===
    if (!COMMANDS.has(text)) {
      const isQuestion =
        /[?？]\s*$/.test(text) ||
        /있으신가요|선택해주세요|대답해\s*주세요|원하세요/.test(text.replace(/\s/g, ""));
      if (shouldQueue(text)) {
        if (isQuestion) pendingMicOn = true; // 질문이면 TTS 뒤 자동 STT 재개
        say(text);
      }
    }
  };

  socket.onclose = (event) => {
    console.warn("🔌 WebSocket 연결 종료됨. 재연결 시도...");
    console.log("🔌 WebSocket 종료 상세:", event.code, event.reason);
  };

  socket.onerror = (error) => {
    console.error("❌ WebSocket 오류:", error);
  };
}

// 🔼 다른 함수들과 함께, startRecognition() 함수 정의 전에!
function stripSystemPrompts(text) {
  const patterns = [
    "결제를진행할까요",
    "옵션선택을진행할까요",
    "음성주문을시작합니다",
    "어떤메뉴를원하세요",
    "음성으로주문하시겠습니까",
    "아메리카노2000원입니다옵션선택을진행할까요"
  ];
  for (const pattern of patterns) {
    if (text.startsWith(pattern)) {
      text = text.replace(pattern, "");
    }
  }
  return text.trim();
}

function startRecognition() {
  console.log("📣 startRecognition() 호출됨");

  if (isSpeaking) {
    console.log("⏸️ TTS 중 → startRecognition 연기");
    pendingMicOn = true;
    return;
  }

  if (recognizing || isStarting) {
    console.log("⏭️ 마이크 켜는 중이거나 이미 켜짐 → 무시");
    return;
  }
  isStarting = true;
  recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
  recognition.lang = 'ko-KR';
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  recognition.continuous = true;

  recognition.onstart = () => {
    console.log("🎙️ 마이크 켜짐 (onstart)");
  };

  recognition.onspeechstart = () => {
    console.log("🔉 사용자 발화 감지됨");
  };

  recognition.onresult = (event) => {
    const result = event.results[event.results.length - 1][0].transcript.trim();
    console.log('🎤 인식된 텍스트:', result);

    // 🪄 TTS 에코 필터 (정규화 후 완전/부분 일치 차단)
    const normRes = normalizeText(result);
    if (lastSpoken.norm) {
      const ls = lastSpoken.norm;
      const isEcho =
        normRes === ls ||
        (ls.length >= 8 && (normRes.includes(ls) || ls.includes(normRes)));
      if (isEcho) {
        console.log("🪄 TTS 에코로 판단 → 무시");
        return;
      }
    }

    let cleanText = result.replace(/\s/g, '').toLowerCase();
    cleanText = stripSystemPrompts(cleanText);

    const phrasesToIgnore = [
      "음성으로주문하시겠습니까",
      "음성주문을시작합니다",
      "어떤메뉴를원하세요",
      "옵션선택을진행할까요",
      "아메리카노2000원입니다옵션선택을진행할까요"
    ];
    const shouldIgnore = phrasesToIgnore.some(p => cleanText.startsWith(p));
    if (shouldIgnore) {
      console.log("⏭️ 안내 문장은 전송 생략됨");
      return;
    }

    const positives = ["네", "응", "예", "그래", "좋아", "오케이", "웅", "ㅇㅇ"];
    if (positives.includes(cleanText)) {
      console.log("✅ 긍정 응답 → 서버로 전송");
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(result);
      }
      return;
    }

    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(result);
    }
  };

  recognition.onerror = (event) => {
    console.error('❌ 음성 인식 에러:', event.error);
  };

  recognition.onend = () => {
    console.warn("🛑 음성 인식 종료됨");
    recognizing = false;
    console.log("🔇 마이크 꺼진 상태, 재시작 안함");
  };

  recognition.start();
  recognizing = true;
  isStarting = false;
  console.log("🎤 음성 인식 시작");
}

document.addEventListener("DOMContentLoaded", () => {
  // 초기 미리 준비(실패해도 상관 없음, 이후 say()가 재시도/버퍼링)
  ensureSynthReady();

  // 고유 client_id 생성 및 유지
  const clientId = localStorage.getItem("client_id") || crypto.randomUUID();
  localStorage.setItem("client_id", clientId);

  // 기존 WebSocket 정리
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    console.warn("🔁 기존 WebSocket을 닫습니다.");
    socket.onclose = null;
    socket.onmessage = null;
    socket.close();
    socket = null;
  }

  // 새로 연결
  createWebSocket();

  // ✅ 👉 /order 페이지 진입 시 음성 인식 여부 결정
  const isOrderPage = /^\/order\/?$/.test(window.location.pathname);
  if (isOrderPage) {
    const disableVoice = localStorage.getItem("disableVoice") === "true";
    if (disableVoice) localStorage.removeItem("disableVoice");

    setTimeout(() => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send("resume_from_menu");
      }
    }, 300);
  }

  const payButton = document.querySelector(".pay-button");
  if (payButton) {
    payButton.addEventListener("click", () => {
      const clientIdLocal = localStorage.getItem("client_id");
      if (!clientIdLocal) {
        alert("client_id가 없습니다. 음성 인식이 초기화되지 않았을 수 있습니다.");
        return;
      }

      const path = window.location.pathname;
      console.log("📄 현재 경로:", path);

      if (path.startsWith("/order2/")) {
        window.location.href = `/pay_all2?client_id=${clientIdLocal}`;
      } else if (path.startsWith("/order")) {
        window.location.href = `/pay_all?client_id=${clientIdLocal}`;
      } else {
        alert("현재 페이지가 주문 페이지가 아닙니다.");
      }
    });
  }

  // start 페이지에서 클릭 이벤트 등록 (영구적)
  document.addEventListener('click', function() {
    console.log("🖱️ 클릭 감지! 현재 경로:", window.location.pathname);

    if (window.location.pathname === "/" ||
        window.location.pathname.includes("start") ||
        window.location.pathname === "/start/") {

      console.log("✅ start 페이지에서 클릭됨 → 음성 주문 시작");

      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send("start_order");
        console.log("📤 start_order 전송됨");
      } else {
        console.warn("❌ WebSocket 연결 안됨:", socket?.readyState);
      }
    }
  });
});
