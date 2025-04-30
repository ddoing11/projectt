// 모듈로 인식시키기 위해 필요
export {};

"use strict";

let socket;
let state = "waiting"; // 초기 상태
let selectedMenu = "";
let selectedCategory = "";
let tempOrder = {}; // 임시 주문 저장용
let optionStep = 0; // 옵션 질문 단계 (0: 사이즈, 1: 온도, 2: 샷추가)

function createWebSocket() {
  socket = new WebSocket('ws://127.0.0.1:8002');

  socket.onopen = () => {
    console.log('✅ WebSocket 연결됨');
  };

  socket.onmessage = async (event) => {
    const text = event.data.trim();
    console.log('📩 받은 텍스트:', text);

    if (text === "음성으로 주문하시겠습니까?") {
      speakText(text);
      state = "waiting";
    } else if (text.includes("음성 주문을 시작합니다")) {
      state = "ordering";
      speakText(text);
    } else if (text.includes("음성 인식을 종료합니다")) {
      state = "waiting";
      speakText(text);
    } else {
      // 나머지는 상태 기반으로 처리
      if (state === "ordering") {
        await handleMenuSelection(text);
      } else if (state === "optioning") {
        await handleOptionSelection(text);
      }
    }
  };

  socket.onclose = () => {
    console.warn("⚠️ WebSocket 연결 종료");
  };

  socket.onerror = (error) => {
    console.error("❌ WebSocket 오류:", error);
  };
}

async function handleMenuSelection(text) {
  const res = await fetch("http://127.0.0.1:8000/check-menu/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text })
  });

  const data = await res.json();
  console.log("🔍 menu check 결과:", data);

  if (data.match === true) {
    selectedMenu = data.menu;
    selectedCategory = data.category;
    tempOrder = { menu: selectedMenu, category: selectedCategory, price: data.price };
    optionStep = 0;
    state = "optioning";
    speakText("사이즈를 선택해 주세요. 보통 또는 크게 중에서 골라주세요.");
  } else {
    const gptRes = await fetch("http://127.0.0.1:8000/gpt-assist/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });
    const gptData = await gptRes.json();
    speakText(gptData.response);
    state = "ordering";
  }
}

async function handleOptionSelection(text) {
  if (optionStep === 0) {
    if (text.includes("보통") || text.includes("기본")) {
      tempOrder.size = "보통";
    } else if (text.includes("크게")) {
      tempOrder.size = "크게";
      tempOrder.price += 500;
    } else {
      speakText("다시 말씀해 주세요. 보통 또는 크게 중에서 선택해 주세요.");
      return;
    }
    optionStep++;
    speakText("핫 또는 아이스를 선택해 주세요.");
  } else if (optionStep === 1) {
    if (text.includes("핫")) {
      tempOrder.temperature = "핫";
    } else if (text.includes("아이스")) {
      tempOrder.temperature = "아이스";
    } else {
      speakText("다시 말씀해 주세요. 핫 또는 아이스 중에서 선택해 주세요.");
      return;
    }
    if (tempOrder.category === "coffee" || tempOrder.category === "drink") {
      optionStep++;
      speakText("샷 추가를 원하시나요? 1샷 추가, 2샷 추가, 추가 안함 중에서 선택해 주세요.");
    } else {
      finalizeOrder();
    }
  } else if (optionStep === 2) {
    if (text.includes("1샷") || text.includes("한 샷")) {
      tempOrder.shot = 1;
      tempOrder.price += 300;
    } else if (text.includes("2샷") || text.includes("두 샷")) {
      tempOrder.shot = 2;
      tempOrder.price += 600;
    } else if (text.includes("안함") || text.includes("추가 안함")) {
      tempOrder.shot = 0;
    } else {
      speakText("다시 말씀해 주세요. 1샷 추가, 2샷 추가, 추가 안함 중에서 선택해 주세요.");
      return;
    }
    finalizeOrder();
  }
}

function finalizeOrder() {
  console.log("🧾 최종 주문:", tempOrder);
  speakText(`주문 완료: ${tempOrder.menu}, ${tempOrder.size} 사이즈, ${tempOrder.temperature}, 총 ${tempOrder.price}원입니다.`);

  fetch("http://127.0.0.1:8000/add-to-cart/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(tempOrder)
  });

  tempOrder = {};
  selectedMenu = "";
  selectedCategory = "";
  optionStep = 0;
  state = "waiting";
}

// 🔊 안정적으로 speak 처리
function speakText(text, onEnd = null) {
  window.speechSynthesis.cancel();  // 기존 출력 중단
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "ko-KR";
  if (onEnd) utterance.onend = onEnd;
  speechSynthesis.speak(utterance);
}

// 🔌 WebSocket 연결
createWebSocket();

// 👆 화면 클릭 시 음성 주문 안내
document.addEventListener("click", () => {
  if (state === "waiting") {
    socket.send("start_order");

    // TTS가 잘 들리도록 약간의 delay 줌
    setTimeout(() => {
      speakText("음성으로 주문하시겠습니까?");
    }, 100);
  }
});
