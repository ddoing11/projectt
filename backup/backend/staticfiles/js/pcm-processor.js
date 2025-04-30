//  AudioWorklet 모듈로 인식되도록 export 문 추가
export {};

class PCMProcessor extends AudioWorkletProcessor {
  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (input.length > 0) {
      const channelData = input[0];
      const buffer = new ArrayBuffer(channelData.length * 2);
      const view = new DataView(buffer);

      for (let i = 0; i < channelData.length; i++) {
        let s = Math.max(-1, Math.min(1, channelData[i]));
        view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
      }

      this.port.postMessage({ pcm: buffer });
    }
    return true;
  }
}

registerProcessor('pcm-processor', PCMProcessor);
