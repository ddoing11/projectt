"use strict";

let socket;
let recognition;
let recognizing = false;
let resumeHandled = false;  // ✅ 상태 복원 응답 후 인식 시작 여부

function createWebSocket() {
  socket = new WebSocket('ws://localhost:8002');

  socket.onopen = () => {
    console.log('✅ WebSocket 연결됨');

    if (localStorage.getItem("continueRecognition") === "true") {
      localStorage.removeItem("continueRecognition");
      console.log("🔁 페이지 전환 후 자동 음성 인식 재시작");
      socket.send("resume_from_menu"); // ✅ 서버에 상태 복원 요청만 먼저 전송

    }
  };

  socket.onmessage = (event) => {
    const text = event.data.trim();
    console.log('📩 서버 응답:', text);

    // ✅ 마이크 제어 명령
    if (text === "mic_off") {
      console.log("🔇 서버 지시: 마이크 OFF");
      if (recognition) {
        try {
          recognizing = false;  // ✅ 마이크 상태 먼저 false로 명확히
          recognition.stop();   // ✅ try-catch로 감싸서 안정성 보장
        } catch (error) {
          console.error("❌ recognition.stop() 오류:", error);
        }
      }
      return;
    }


    if (text === "mic_on") {
      console.log("🔊 서버 지시: 마이크 ON");

      // 마이크 완전히 종료 후 재시작
      if (recognition && recognizing) {
        try {
          recognition.abort();
        } catch (e) {
          console.warn("⚠️ abort 중 오류:", e);
        }
        recognizing = false;
      }

      setTimeout(() => {
        startRecognition();  // 약간의 텀 두고 시작
      }, 100);  // 필요 시 50~150ms 사이로 조절 가능

      return;
    }





    // 🎯 페이지 이동 명령 처리
    if (text === "goto_menu") {
      console.log("📢 서버 지시: /order 페이지로 이동");
      localStorage.setItem("continueRecognition", "true");
      window.location.href = "/order";
      return;
    }


    if (text === "goto_start") {
      console.log("📢 서버 지시: /start 페이지로 이동");
    
      // ✅ 음성 인식 중지
      if (recognizing && recognition) {
        recognizing = false;
        recognition.stop();
        console.log("🛑 음성 인식 중단 후 페이지 이동");
      }
    
      window.location.href = "/start";
      return;
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

    let cleanText = result.replace(/\s/g, '').toLowerCase();

    // 📛 시스템 음성 문장 무시
    const phrasesToIgnore = [
      "음성으로주문하시겠습니까",
      "음성주문을시작합니다",
      "어떤메뉴를원하세요",
      "옵션선택을진행할까요",
      "아메리카노2000원입니다옵션선택을진행할까요"
    ];

    const shouldIgnore = phrasesToIgnore.some(p =>
      cleanText.startsWith(p)
    );

    if (shouldIgnore) {
      console.log("⏭️ 안내 문장은 전송 생략됨");
      return;
    }

    // 🟢 긍정 응답일 경우 바로 전송
    const positives = ["네", "응", "예", "그래", "좋아", "오케이", "웅", "ㅇㅇ"];
    if (positives.includes(cleanText)) {
      console.log("✅ 긍정 응답 → 서버로 전송");
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(result);
      }
      return;
    }

    // 🛰 서버로 텍스트 전송
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
  console.log("🎤 음성 인식 시작");
}


document.addEventListener("DOMContentLoaded", () => {
  window.speechSynthesis.cancel();
  createWebSocket();

  document.body.addEventListener("click", () => {
    console.log("🖱️ 화면 터치 → start_order 전송");
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send("start_order");
    }
  });
});
