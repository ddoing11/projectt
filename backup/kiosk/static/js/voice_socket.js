// 모듈로 인식시키기 위해 필요
export {};

"use strict";

let socket;
let recognition;
let recognizing = false;

function createWebSocket() {
  socket = new WebSocket('ws://localhost:8002');

  socket.onopen = () => {
    console.log('✅ WebSocket 연결됨');
  };

  socket.onmessage = (event) => {
    const text = event.data.trim();
    console.log('📩 서버 응답:', text);

    // 🎯 음성 안내 멘트 이후 마이크 계속 켜기
    if (
      text.includes("음성으로 주문하시겠습니까") ||
      text.includes("음성 주문을 시작합니다") ||
      text.includes("더 추가할 메뉴")
    ) {
      startRecognition(); // 🔁 음성 안내 중에도 인식 유지
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
  recognition.continuous = true;  // 🎯 계속 듣기 설정

  recognition.onstart = () => {
    console.log("🎙️ 마이크 켜짐 (onstart)");
  };

  recognition.onspeechstart = () => {
    console.log("🔉 사용자 발화 감지됨");
  };

  recognition.onresult = (event) => {
    const result = event.results[event.results.length - 1][0].transcript.trim();
    console.log('🎤 인식된 텍스트:', result);
    socket.send(result);  // 서버로 전송
  };

  recognition.onerror = (event) => {
    console.error('❌ 음성 인식 에러:', event.error);
  };

  recognition.onend = () => {
    console.warn("🛑 음성 인식 종료됨 → 재시작 시도");
    if (recognizing) {
      recognition.start();  // 끊기면 자동 재시작
    }
  };

  recognition.start();
  recognizing = true;
  console.log("🎤 음성 인식 시작");
}

// 페이지 로드시 WebSocket 연결
document.addEventListener("DOMContentLoaded", () => {
  window.speechSynthesis.cancel(); // 🔇 혹시 브라우저 TTS 재생 중이면 중지
  createWebSocket();
});

// 첫 클릭 시 'start_order' 메시지 전송
document.addEventListener("click", () => {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send("start_order");
    console.log("🟢 화면 터치됨 → 서버에 start_order 전송");
  }
});
