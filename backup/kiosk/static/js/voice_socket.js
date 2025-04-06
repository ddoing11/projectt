"use strict";

const socket = new WebSocket('ws://localhost:8000/ws/audio/');
const audioContext = new (window.AudioContext || window.webkitAudioContext)();
let mediaStream = null;
let processor = null;
let input = null;

socket.onopen = () => {
  console.log('✅ WebSocket 연결됨');
  checkMicrophonePermission();  // ✅ 권한 확인 후 실행
};

function checkMicrophonePermission() {
  navigator.permissions.query({ name: 'microphone' }).then(result => {
    if (result.state === 'granted') {
      console.log('🎤 마이크 권한 있음');
      startRecording();
    } else if (result.state === 'prompt') {
      console.log('🎤 마이크 권한 요청 중');
      requestMicrophoneAccess();
    } else {
      console.warn('🚫 마이크 권한 없음');
    }
  });
}

function requestMicrophoneAccess() {
  navigator.mediaDevices.getUserMedia({ audio: true })
    .then(stream => {
      mediaStream = stream;
      startRecording();
    })
    .catch(err => {
      console.error('❌ 마이크 접근 실패:', err);
    });
}

function startRecording() {
  input = audioContext.createMediaStreamSource(mediaStream);
  processor = audioContext.createScriptProcessor(4096, 1, 1);

  input.connect(processor);
  processor.connect(audioContext.destination);

  processor.onaudioprocess = e => {
    const audioData = e.inputBuffer.getChannelData(0);
    socket.send(audioData.buffer);
  };
}

socket.onmessage = event => {
  const data = JSON.parse(event.data);
  if (data.text) {
    console.log('🗣 받은 텍스트:', data.text);
    document.getElementById("output").innerText = data.text;
  }
};

socket.onclose = () => {
  console.log('🔌 WebSocket 연결 종료');
  if (mediaStream) mediaStream.getTracks().forEach(track => track.stop());
};
