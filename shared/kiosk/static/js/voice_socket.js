// 모듈로 인식시키기 위해 필요
export {};

"use strict";

let socket;
let recognition;
let recognizing = false;

function createWebSocket() {
  socket = new WebSocket('ws://127.0.0.1:8002');

  socket.onopen = () => {
    console.log('✅ WebSocket 연결됨');
  };

  socket.onmessage = async (event) => {
    const text = event.data.trim();
    console.log('📩 서버 응답:', text);

    const u = new SpeechSynthesisUtterance(text);
    speechSynthesis.speak(u);

    // '음성으로 주문하시겠습니까?' 나오면 음성 인식 시작
    if (text.includes("음성으로 주문하시겠습니까")) {
      u.onend = () => {
        console.log("🔊 안내 멘트 끝남, 음성 인식 시작");
        startRecognition();
      };
    }
  };

  socket.onclose = () => {
    console.warn("⚠️ WebSocket 연결 종료");
  };

  socket.onerror = (error) => {
    console.error("❌ WebSocket 오류:", error);
  };
}

function startRecognition() {
  if (recognizing) return;
  
  recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
  recognition.lang = 'ko-KR';
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  recognition.start();
  recognizing = true;
  console.log("🎤 음성 인식 시작");

  recognition.onresult = (event) => {
    const result = event.results[0][0].transcript.trim();
    console.log('🎤 인식된 텍스트:', result);

    if (result.includes("네")) {
      socket.send("네");
    } else if (result.includes("아니")) {
      socket.send("아니");
    } else {
      socket.send(result);
    }
    recognizing = false;
    recognition.stop();
  };

  recognition.onerror = (event) => {
    console.error('❌ 음성 인식 에러:', event.error);
    recognizing = false;
  };

  recognition.onend = () => {
    console.log("🛑 음성 인식 종료");
    recognizing = false;
  };
}

// 페이지 로드시 WebSocket 연결
createWebSocket();

// 클릭하면 'start_order' 보내기
document.addEventListener("click", () => {
  socket.send("start_order");
});
