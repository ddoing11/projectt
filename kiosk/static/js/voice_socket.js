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
      startRecognition();
    }
  };

  socket.onmessage = (event) => {
    const text = event.data.trim();
    console.log('📩 서버 응답:', text);

    // ✅ resume_from_menu 이후의 첫 응답에서 음성인식 시작
    if (!resumeHandled && (
      text.includes("다시 메뉴를 말씀해주세요") ||
      text.includes("옵션 선택을 진행할까요") ||
      text.includes("장바구니에 담았습니다")
    )) {
      resumeHandled = true;
      console.log("🎤 서버 응답 후 음성 인식 시작");
      startRecognition();
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
    


    // 🎯 음성 안내 멘트 이후 마이크 계속 켜기
    if (
      /음성.*주문.*시겠습니까/.test(text) ||
      /음성 주문.*시작합니다/.test(text) ||
      /더 추가할 메뉴/.test(text) ||
      /메뉴.*말씀/.test(text)
    ) {
      console.log("🎤 음성인식 시작 조건 충족됨 → startRecognition 호출");
      startRecognition();
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

    ["음성으로주문하시겠습니까", "음성주문을시작합니다", "어떤메뉴를원하세요"].forEach(phrase => {
      if (cleanText.startsWith(phrase)) {
        cleanText = cleanText.slice(phrase.length);
      }
    });

    const positives = ["네", "응", "예", "그래", "좋아", "오케이", "웅", "ㅇㅇ"];
    if (positives.includes(cleanText)) {
      console.log("✅ 긍정 응답 → 서버로 전송");
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(result);
      }
      return;
    }

    const phrasesToIgnore = [
      "음성으로 주문하시겠습니까",
      "음성 주문을 시작합니다",
      "어떤 메뉴를 원하세요"
    ];
    const shouldIgnore = phrasesToIgnore.some(p =>
      cleanText.includes(p.replace(/\s/g, '').toLowerCase())
    );
    if (shouldIgnore) {
      console.log("⏭️ 안내 문장은 전송 생략됨");
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
    console.warn("🛑 음성 인식 종료됨 → 재시작 시도");
    if (recognizing) {
      recognition.start();
    }
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
  }, { once: true });
});
