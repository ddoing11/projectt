"use strict";
// @charset "UTF-8";

const socket = new WebSocket('ws://localhost:8000/ws/audio/');

const audioContext = new (window.AudioContext || window.webkitAudioContext)();
let mediaStream = null;
let processor = null;
let input = null;

socket.onopen = () => {
  console.log('WebSocket 연결됨');
  startRecording();
};

function startRecording() {
  navigator.mediaDevices.getUserMedia({ audio: true })
    .then(stream => {
      mediaStream = stream;
      input = audioContext.createMediaStreamSource(stream);
      processor = audioContext.createScriptProcessor(4096, 1, 1);

      input.connect(processor);
      processor.connect(audioContext.destination);

      processor.onaudioprocess = e => {
        const audioData = e.inputBuffer.getChannelData(0);
        socket.send(audioData.buffer);
      };
    })
    .catch(err => console.error('마이크 접근 실패:', err));
}

socket.onmessage = event => {
  const data = JSON.parse(event.data);
  if (data.text) {
    console.log('받은 텍스트:', data.text);
    document.getElementById("output").innerText = data.text;
  }
};

socket.onclose = () => {
  console.log('WebSocket 연결 종료');
  if (mediaStream) mediaStream.getTracks().forEach(track => track.stop());
};
