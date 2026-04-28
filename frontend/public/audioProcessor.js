class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.bufferSize = 4096;
    this.buffer = new Float32Array(this.bufferSize);
    this.bufferPtr = 0;
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (input.length > 0) {
      const channelData = input[0];
      
      for (let i = 0; i < channelData.length; i++) {
        this.buffer[this.bufferPtr++] = channelData[i];
        
        if (this.bufferPtr >= this.bufferSize) {
          // 1. PCM 변환 (Float32 -> Int16)
          const int16Buffer = new Int16Array(this.bufferSize);
          let sumSquares = 0;
          
          for (let j = 0; j < this.bufferSize; j++) {
            const s = Math.max(-1, Math.min(1, this.buffer[j]));
            int16Buffer[j] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            
            // 볼륨 계산을 위한 제곱합
            sumSquares += s * s;
          }
          
          // 2. RMS(실효값) 볼륨 계산
          const rms = Math.sqrt(sumSquares / this.bufferSize);
          
          // 3. 데이터 및 볼륨 전송
          this.port.postMessage({
            pcm: int16Buffer.buffer,
            volume: rms
          }, [int16Buffer.buffer]);
          
          this.bufferPtr = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("pcm-processor", PCMProcessor);
