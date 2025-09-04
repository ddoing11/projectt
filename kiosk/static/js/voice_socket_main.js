"use strict";

console.log("✅ JS 작동 중입니다");

let socket;
let recognition;
let recognizing = false;
let resumeHandled = false;  // ✅ 상태 복원 응답 후 인식 시작 여부
let isStarting = false; // 🔹 새로 추가




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
  if (socket && socket.readyState === WebSocket.OPEN) {
    console.warn("⚠️ 이미 연결된 WebSocket 있음. 생략.");
    return;
  }
  // 로컬 테스트 시에는 127.0.0.1의 8002 포트를 사용
  // 배포 시에는 wss://mykiosk8002.jp.ngrok.io 등 실제 서버 주소로 교체
  const wsUrl =
    window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost"
      ? "ws://127.0.0.1:8002"
      : "wss://mykiosk8002.jp.ngrok.io";

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
    // 💬 cart_summary JSON 처리 먼저 시도

    console.log("📥 WebSocket 메시지 수신:", event.data);  // ✅ 추가
    try {
      const parsed = JSON.parse(event.data);  // 🔧 이 한 줄이 반드시 있어야 함!

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
          }, 300);  // 약간의 여유를 줘도 좋음
        }
        return;
      }
    } catch (e) {
      console.warn("⚠️ JSON 파싱 실패. 일반 메시지 처리 시도:", event.data);
    }
    
    const text = event.data.trim();
    console.log('📩 서버 응답:', text);

    if (text === "popup_payment") {
      console.log("💳 결제 팝업 띄우기");

      const popup = document.getElementById("popup-overlay");
      if (popup) {
        popup.style.display = "block";

        // 8초 후 자동 닫기
        setTimeout(() => {
          popup.style.display = "none";
        }, 8000);
      } else {
        console.warn("❗ 팝업 요소를 찾을 수 없음: popup-overlay");
      }
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
      const currentPath = window.location.pathname;

      const disableVoice = localStorage.getItem("disableVoice") === "true";
        if (currentPath === "/order" && disableVoice) {
          console.log("🚫 /order에서 disableVoice=true → mic_on 무시");
          return;
        }

      console.log("🔊 서버 지시: 마이크 ON");

      if (recognizing || isStarting) {
        console.log("⏭️ 이미 마이크 켜는 중이거나 켜짐 상태 → 무시");
        return;
      }



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
      const clientId = localStorage.getItem("client_id");
      if (clientId) {
        console.log("📢 서버 지시: /pay_all 페이지로 이동");
        location.assign(`/pay_all?client_id=${clientId}`);
      } else {
        console.warn("❌ client_id가 없습니다. 이동 취소");
      }
      return;
    }

    if (text === "go_to_order2") {
      console.log("📢 서버 지시: /order2 페이지로 이동");
      localStorage.setItem("continueRecognition", "false");  // ❌ 음성인식 비활성화
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

  };

  socket.onclose = (event) => {
    console.warn("🔌 WebSocket 연결 종료됨. 재연결 시도...");
    console.log("🔌 WebSocket 종료 상세:", event.code, event.reason);

  // 🔻 아래 줄을 주석처리해서 자동 새로고침 중단!
  // setTimeout(() => {
  //   window.location.reload();  // 또는 reconnectSocket()
  // }, 100);  // ⏱ 1초 후 재시도
  };


  socket.onerror = (error) => {
    console.error("❌ W ebSocket 오류:", error);
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
  if (recognizing || isStarting) {
    console.log("⏭️ 마이크 켜는 중이거나 이미 켜짐 → 무시");
    return;

  }
  isStarting = true;  // 🔐 여기서만 설정
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
  isStarting = false;  // ✅ 마이크 시작 완료
  console.log("🎤 음성 인식 시작");
}

document.addEventListener("DOMContentLoaded", () => {

  // 고유 client_id 생성 및 유지
  const clientId = localStorage.getItem("client_id") || crypto.randomUUID();
  localStorage.setItem("client_id", clientId);

  // 기존 WebSocket이 있다면 닫고
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    console.warn("🔁 기존 WebSocket을 닫습니다.");
    socket.onclose = null;  // 💡 자동 재연결 방지
    socket.onmessage = null;      // ✅ 메시지 리스너 제거 (여기!)
    socket.close();
    socket = null;  // ✅ 명시적으로 null로 초기화
  }

  // 새로 연결
  createWebSocket();


  

  // ✅ 👉 /order 페이지 진입 시 음성 인식 여부 결정
  // ✅ 👉 /order 페이지 진입 시 음성 인식 여부 결정
  if (window.location.pathname === "/order") {
      const disableVoice = localStorage.getItem("disableVoice") === "true";
      if (disableVoice) {
          console.log("🔇 disableVoice=true → 플래그 제거하고 음성 인식 활성화");
          localStorage.removeItem("disableVoice");  // 플래그 제거
      }
      
      // 항상 음성 인식 시작
      console.log("🎤 음성 인식 요청");
      setTimeout(() => {
          if (socket && socket.readyState === WebSocket.OPEN) {
              socket.send("resume_from_menu");
          }
      }, 300);  // 약간 지연 후 전송
  }
  const payButton = document.querySelector(".pay-button");
  if (payButton) {
    payButton.addEventListener("click", () => {
      const clientId = localStorage.getItem("client_id");
      if (!clientId) {
        alert("client_id가 없습니다. 음성 인식이 초기화되지 않았을 수 있습니다.");
        return;
      }

      const path = window.location.pathname;
      console.log("📄 현재 경로:", path);

      if (path.startsWith("/order2/")) {
        window.location.href = `/pay_all2?client_id=${clientId}`;
      } else if (path.startsWith("/order")) {
        window.location.href = `/pay_all?client_id=${clientId}`;
      } else {
        alert("현재 페이지가 주문 페이지가 아닙니다.");
      }
    });
  }


});    


// start 페이지에서 클릭 이벤트 등록 (영구적)
document.addEventListener('DOMContentLoaded', function() {
    console.log("🎯 start 페이지 클릭 이벤트 등록 중...");
    
    // 전체 document에 클릭 이벤트 등록
    document.addEventListener('click', function(event) {
        console.log("🖱️ 클릭 감지! 현재 경로:", window.location.pathname);
        
        // start 페이지에서만 작동
        if (window.location.pathname === "/" || 
            window.location.pathname.includes("start") || 
            window.location.pathname === "/start/") {
            
            console.log("✅ start 페이지에서 클릭됨 → 음성 주문 시작");
            
            if (socket && socket.readyState === WebSocket.OPEN) {
                // start_order 메시지 전송
                socket.send("start_order");
                console.log("📤 start_order 전송됨");
                
                // TTS 요청 전송
                /*
                const ttsMessage = {
                    type: 'text_to_speech',
                    text: '음성으로 주문하시겠습니까?'
                };
                socket.send(JSON.stringify(ttsMessage));
                console.log("🎤 TTS 메시지 전송:", ttsMessage);
                */
            } else {
                console.warn("❌ WebSocket 연결 안됨:", socket?.readyState);
            }
        }
    });
    
    console.log("🎯 start 페이지 클릭 이벤트 등록 완료!");
});
