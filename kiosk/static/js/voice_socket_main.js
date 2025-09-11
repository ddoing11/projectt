"use strict";

console.log("✅ 개선된 음성 키오스크 클라이언트 시작");

let socket;
let recognition;
let recognizing = false;
let speechSynthesizer = null;
let isSpeaking = false;
let pendingMicOn = false;
let micOnTimer = null;
let recognitionRetryCount = 0;
const MAX_RETRY_COUNT = 3;

// TTS 중복 방지
let lastSpoken = { norm: "", at: 0 };
let pendingTts = [];
let drainingTts = false;

// TTS 초기화 상태
let ttsInitialized = false;
let useFallbackTTS = false;
let audioContextUnlocked = false;
let ttsPreWarmed = false;

function normalizeText(s) {
    return (s || "").toLowerCase().replace(/\s/g, "").replace(/[^\p{L}\p{N}]/gu, "");
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

// 오디오 컨텍스트 잠금 해제
async function unlockAudioContext() {
    if (audioContextUnlocked) return;
    
    try {
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        
        if (audioContext.state === 'suspended') {
            console.log("🔓 오디오 컨텍스트 잠금 해제 시도");
            await audioContext.resume();
        }
        
        // 무음 재생으로 오디오 정책 우회
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
        
        setTimeout(() => {
            audioContext.close();
        }, 1000);
        
    } catch (e) {
        console.warn("⚠️ 오디오 컨텍스트 잠금 해제 실패:", e);
    }
}

// 브라우저 내장 TTS 사용 (즉시 재생)
function speakWithBrowserTTS(text, activateMic = true) {
    return new Promise((resolve) => {
        if (!('speechSynthesis' in window)) {
            console.error("❌ 브라우저가 speechSynthesis를 지원하지 않음");
            resolve();
            return;
        }

        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'ko-KR';
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
                setTimeout(() => {
                    startRecognition();
                }, 300);
            }
            resolve();
        };

        utterance.onerror = (event) => {
            console.error("❌ 브라우저 TTS 오류:", event);
            isSpeaking = false;
            resolve();
        };

        speechSynthesis.cancel();
        speechSynthesis.speak(utterance);
    });
}

// Azure Speech SDK 로드
async function loadAzureSpeechSDK() {
    if (window.SpeechSDK) {
        console.log("✅ Azure Speech SDK 이미 로드됨");
        return;
    }

    const existingScript = document.querySelector('script[src*="csspeech"]');
    if (existingScript) {
        console.log("🔍 기존 Speech SDK 스크립트 발견, 대기 중...");
        try {
            await waitForSpeechSDK(8000);
            console.log("✅ 기존 스크립트로부터 Speech SDK 로드 완료");
            return;
        } catch (e) {
            console.warn("⚠️ 기존 스크립트 로드 실패, 새로 로드 시도");
        }
    }

    const cdnUrls = [
        "https://cdn.jsdelivr.net/npm/microsoft-cognitiveservices-speech-sdk@latest/distrib/browser/microsoft.cognitiveservices.speech.sdk.bundle-min.js"
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

function waitForSpeechSDK(timeoutMs = 10000) {
    return new Promise((resolve, reject) => {
        const start = Date.now();
        function check() {
            if (window.SpeechSDK) {
                console.log("✅ Speech SDK 준비됨");
                return resolve();
            }
            if (Date.now() - start > timeoutMs) {
                return reject(new Error("Speech SDK 로드 타임아웃"));
            }
            setTimeout(check, 200);
        }
        check();
    });
}

// TTS 사전 초기화 (페이지 로드 시 실행)
async function preWarmTTS() {
    if (ttsPreWarmed) return;
    
    console.log("🔥 TTS 사전 초기화 시작...");
    
    try {
        // Azure Speech SDK 로드
        await loadAzureSpeechSDK();
        
        // TTS 토큰 미리 가져오기
        console.log("🔄 TTS 토큰 사전 요청...");
        const res = await fetch("/api/tts-token/");
        
        if (!res.ok) {
            throw new Error(`TTS token fetch failed: ${res.status}`);
        }
        
        const data = await res.json();
        if (data.error) {
            throw new Error(`TTS token error: ${data.error}`);
        }
        
        const { token, region } = data;
        
        // Azure TTS 설정 미리 완료
        console.log("🔄 Azure TTS 사전 설정...");
        const speechConfig = window.SpeechSDK.SpeechConfig.fromAuthorizationToken(token, region);
        speechConfig.speechSynthesisVoiceName = "ko-KR-SunHiNeural";
        const audioConfig = window.SpeechSDK.AudioConfig.fromDefaultSpeakerOutput();
        speechSynthesizer = new window.SpeechSDK.SpeechSynthesizer(speechConfig, audioConfig);
        
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

// TTS 초기화 (빠른 버전)
async function ensureSynthReady() {
    if (ttsPreWarmed && speechSynthesizer) {
        console.log("⚡ TTS 이미 준비됨 (사전 초기화)");
        return true;
    }
    
    // 사전 초기화가 안된 경우 빠른 초기화
    return await preWarmTTS();
}

async function speakText(text, activateMic = true) {
    if (!shouldSpeak(text)) return;
    
    console.log(`🔊 TTS 실행: "${text}" (사전초기화: ${ttsPreWarmed}, fallback: ${useFallbackTTS})`);
    
    try {
        isSpeaking = true;
        
        if (recognition && recognizing) {
            recognition.stop();
            recognizing = false;
        }
        
        lastSpoken = { norm: normalizeText(text), at: Date.now() };
        
        if (useFallbackTTS || !ttsPreWarmed) {
            // 브라우저 내장 TTS 사용 (즉시 재생)
            await speakWithBrowserTTS(text, activateMic);
            return;
        }
        
        // Azure TTS 사용 (사전 초기화됨)
        return new Promise(async (resolve) => {
            const finish = () => {
                console.log("🔊 Azure TTS 완료");
                isSpeaking = false;
                if (activateMic && !recognizing) {
                    setTimeout(() => {
                        startRecognition();
                    }, 300);
                }
                resolve();
            };

            if (!speechSynthesizer) {
                console.warn("❌ speechSynthesizer 없음, 브라우저 TTS로 대체");
                await speakWithBrowserTTS(text, activateMic);
                resolve();
                return;
            }

            if (!audioContextUnlocked) {
                await unlockAudioContext();
            }

            console.log("⚡ Azure TTS 즉시 실행");
            try {
                speechSynthesizer.speakTextAsync(
                    text,
                    (result) => {
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
        // 사전 초기화된 TTS 사용으로 즉시 처리 가능
        while (pendingTts.length) {
            const { text, activateMic } = pendingTts.shift();
            console.log("▶️ TTS 시작:", text);
            await speakText(text, activateMic);
            console.log("⏹️ TTS 종료:", text);
            await new Promise(r => setTimeout(r, 100)); // 최소 지연만
        }
    } catch (error) {
        console.error("❌ TTS 큐 처리 오류:", error);
    } finally {
        drainingTts = false;
        console.log("✅ TTS 큐 처리 완료");
    }
}

function playDing() {
    try {
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = audioContext.createOscillator();
        const gainNode = audioContext.createGain();
        
        oscillator.connect(gainNode);
        gainNode.connect(audioContext.destination);
        
        oscillator.frequency.value = 800;
        oscillator.type = 'sine';
        gainNode.gain.setValueAtTime(0.1, audioContext.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.3);
        
        oscillator.start(audioContext.currentTime);
        oscillator.stop(audioContext.currentTime + 0.3);
        
        console.log("🔔 딩 소리 재생");
    } catch (e) {
        console.log("❌ 딩 소리 재생 실패:", e);
    }
}

// STT 처리
function startRecognition() {
    if (recognizing || isSpeaking) {
        console.log("⏭️ 이미 음성 인식 중이거나 TTS 중");
        return;
    }

    try {
        recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
        recognition.lang = 'ko-KR';
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
            
            console.log('🎤 인식된 텍스트:', result, '신뢰도:', confidence);

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
            console.error('❌ 음성 인식 오류:', event.error);
            recognizing = false;
            
            if (['no-speech', 'aborted', 'network'].includes(event.error) && recognitionRetryCount < MAX_RETRY_COUNT) {
                recognitionRetryCount++;
                console.log(`🔄 음성 인식 재시도 (${recognitionRetryCount}/${MAX_RETRY_COUNT})`);
                setTimeout(() => {
                    if (!isSpeaking) {
                        startRecognition();
                    }
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

// WebSocket 연결
function createWebSocket() {
    const wsUrl = window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost"
        ? "ws://127.0.0.1:8002"
        : "wss://mykiosk8002.jp.ngrok.io";
    
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log("✅ WebSocket 연결됨");
        
        const clientId = localStorage.getItem("client_id") || crypto.randomUUID();
        localStorage.setItem("client_id", clientId);

        socket.send(JSON.stringify({
            type: "page_info",
            path: window.location.pathname,
            client_id: clientId
        }));

        if (window.location.pathname === "/pay_all") {
            setTimeout(() => {
                if (socket.readyState === WebSocket.OPEN) {
                    socket.send("read_cart");
                    setTimeout(() => {
                        socket.send("request_mic_on");
                    }, 1000);
                }
            }, 200);
        }
    };

    socket.onmessage = (event) => {
        console.log("📥 WebSocket 메시지:", event.data);

        try {
            const data = JSON.parse(event.data);
            
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
                updateCartDisplay(data.items);
                return;
            }
            
            if (data.type === "cart_summary") {
                console.log("📋 장바구니 요약:", data.text);
                return;
            }
        } catch (e) {
            // 일반 텍스트 메시지로 처리
        }

        const text = event.data.trim();

        switch (text) {
            case "mic_on":
                if (!isSpeaking) {
                    setTimeout(startRecognition, 300);
                }
                break;
                
            case "mic_off":
                stopRecognition();
                break;
                
            case "goto_menu":
                localStorage.setItem("continueRecognition", "true");
                window.location.href = "/order";
                break;
                
            case "go_to_pay":
                const clientId = localStorage.getItem("client_id");
                if (clientId) {
                    location.assign(`/pay_all?client_id=${clientId}`);
                }
                break;
                
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

function updateCartDisplay(items) {
    const tableContent = document.getElementById("cart-items");
    if (tableContent) {
        tableContent.innerHTML = items.map(item => `
            <div style="display: flex; justify-content: space-around; padding: 30px 80px; font-size: 42px;">
                <div style="width: 33%; text-align: center;">${item.name}</div>
                <div style="width: 33%; text-align: center;">${item.count}</div>
                <div style="width: 33%; text-align: center;">${Number(item.price).toLocaleString()}원</div>
            </div>
        `).join('');
        console.log("🧾 장바구니 표시 업데이트");
    }
}

function showPaymentPopup() {
    const popup = document.getElementById("popup-overlay");
    if (popup) {
        popup.style.display = "flex";
        setTimeout(() => {
            popup.style.display = "none";
        }, 8000);
    }
}

// 페이지 로드 시 초기화
document.addEventListener("DOMContentLoaded", () => {
    console.log("📄 페이지 로드됨:", window.location.pathname);
    
    // 🔥 TTS 사전 초기화 (즉시 시작)
    setTimeout(() => {
        preWarmTTS();
    }, 100); // 페이지 로드 후 0.1초 뒤 즉시 시작
    
    // WebSocket 연결
    createWebSocket();

    // 음성 인식 상태 복구 (order 페이지)
    if (/^\/order\/?$/.test(window.location.pathname)) {
        const disableVoice = localStorage.getItem("disableVoice") === "true";
        if (disableVoice) {
            localStorage.removeItem("disableVoice");
        }

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

    // start 페이지 클릭 이벤트
    document.addEventListener('click', async function(event) {
        if (window.location.pathname === "/" || 
            window.location.pathname.includes("start")) {
            
            console.log("✅ start 페이지에서 클릭됨");
            
            // 클릭 시 즉시 오디오 컨텍스트 잠금 해제
            await unlockAudioContext();
            
            if (socket?.readyState === WebSocket.OPEN) {
                socket.send("start_order");
            }
        }
    });
});

// 전역 디버깅 함수들
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
        audioContextUnlocked
    }),
    initTTS: () => ensureSynthReady()
};