"use strict";

console.log("✅ JS 작동 중입니다");

let socket;
let recognition;
let recognizing = false;
let resumeHandled = false;  // ✅ 상태 복원 응답 후 인식 시작 여부

function createWebSocket() {
  socket = new WebSocket('ws://localhost:8002');

  socket.onopen = () => {
    console.log('✅ WebSocket 연결됨');

    if (window.location.pathname === "/pay_all") {
      // pay_all_ready 먼저 전송
      if (socket.readyState === WebSocket.OPEN) {
        console.log("📨 pay_all_ready 전송");
        socket.send("pay_all_ready");

        // ✅ 장바구니 내역 읽기 요청
        console.log("📨 read_cart 전송");
        socket.send("read_cart");
      }
    }
  };

  socket.onmessage = (event) => {
    const text = event.data.trim();
    console.log('📩 서버 응답:', text);

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
      console.log("🔊 서버 지시: 마이크 ON");
      if (recognition && recognizing) {
        try {
          recognition.abort();
        } catch (e) {
          console.warn("⚠️ abort 중 오류:", e);
        }
        recognizing = false;
      }

      setTimeout(() => {
        startRecognition();
      }, 100);
      return;
    }

    if (text === "goto_menu") {
      console.log("📢 서버 지시: /order 페이지로 이동");
      localStorage.setItem("continueRecognition", "true");
      window.location.href = "/order";
      return;
    }

    if (text === "go_to_pay") {
      console.log("📢 서버 지시: /pay_all 페이지로 이동");
      window.location.href = "/pay_all";
      return;
    }

    // 💳 결제 팝업 띄우기
    if (text === "popup_payment") {
      console.log("💳 결제 팝업 띄우기");

      const popup = document.getElementById("popup-overlay");
      if (popup) {
        popup.style.display = "flex";
        console.log("✅ popup-overlay 표시 완료");
      } else {
        console.warn("❌ popup-overlay 요소를 찾을 수 없음");
      }

      // ✅ 5초 후 결제 완료 페이지로 이동
      setTimeout(() => {
        window.location.href = "/done";
      }, 5000);
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
  console.log("🎤 음성 인식 시작");
}

document.addEventListener("DOMContentLoaded", () => {
  console.log("✅ DOMContentLoaded 실행됨");

  window.speechSynthesis.cancel();
  createWebSocket();

  if (window.location.pathname.includes("start")) {
    document.addEventListener("click", () => {
      console.log("🖱️ 화면 클릭됨 → start_order 전송");
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send("start_order");
      }
    });
  }

  // /pay_all 처리 이미 onopen에서 하므로 여긴 비워도 됨
});
