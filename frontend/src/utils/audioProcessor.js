/**
 * AudioWorklet Processor — 실시간 PCM 오디오 캡처 + 노이즈 게이트
 * 
 * ScriptProcessorNode의 현대적 대체. 별도 오디오 스레드에서 실행되어
 * 메인 스레드 블로킹 없이 안정적인 연속 오디오 캡처가 가능.
 * 
 * 노이즈 게이트: RMS 볼륨이 임계값 이하이면 무음 버퍼 전송하여
 * 배경 노이즈/작은 소리가 AI에 전달되지 않도록 함.
 */
class PCMProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this._bufferSize = 4096;
        this._buffer = new Float32Array(this._bufferSize);
        this._bytesWritten = 0;

        // ── 노이즈 게이트 설정 ──
        // RMS 임계값: 0.01 ≈ 일반 대화 시작 수준, 배경 노이즈 차단
        this._noiseThreshold = 0.015;
        // 게이트 홀드: 음성이 끊기지 않도록 임계값 초과 후 일정 프레임 유지
        this._holdFrames = 10;  // ~10 * 4096/16000 ≈ 2.5초 홀드
        this._holdCounter = 0;
        this._gateOpen = false;
        // 연속 무음 프레임 카운터 (디버깅용)
        this._silentFrames = 0;
    }

    /**
     * Float32 배열의 RMS(Root Mean Square) 볼륨 계산
     */
    _calculateRMS(float32Array) {
        let sumSquares = 0;
        for (let i = 0; i < float32Array.length; i++) {
            sumSquares += float32Array[i] * float32Array[i];
        }
        return Math.sqrt(sumSquares / float32Array.length);
    }

    /**
     * Float32 → Int16 PCM 변환
     */
    _floatTo16BitPCM(float32Array) {
        const buffer = new ArrayBuffer(float32Array.length * 2);
        const view = new DataView(buffer);
        for (let i = 0; i < float32Array.length; i++) {
            const s = Math.max(-1, Math.min(1, float32Array[i]));
            view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
        }
        return buffer;
    }

    /**
     * 버퍼가 가득 차면 메인 스레드로 PCM 데이터 전송
     * 노이즈 게이트가 닫혀 있으면 무음(0) 버퍼 전송
     */
    _flush() {
        const data = this._buffer.slice(0, this._bytesWritten);
        const rms = this._calculateRMS(data);

        // 노이즈 게이트 로직
        if (rms >= this._noiseThreshold) {
            // 임계값 초과 → 게이트 열기
            this._gateOpen = true;
            this._holdCounter = this._holdFrames;
            this._silentFrames = 0;
        } else if (this._holdCounter > 0) {
            // 홀드 기간: 음성이 끊기지 않도록 유지
            this._holdCounter--;
        } else {
            // 게이트 닫기
            this._gateOpen = false;
            this._silentFrames++;
        }

        let pcm;
        if (this._gateOpen || this._holdCounter > 0) {
            // 게이트 열림: 실제 오디오 전송
            pcm = this._floatTo16BitPCM(data);
        } else {
            // 게이트 닫힘: 무음 전송
            pcm = new ArrayBuffer(this._bytesWritten * 2);
        }

        this.port.postMessage(pcm, [pcm]);
        this._bytesWritten = 0;
    }

    process(inputs) {
        const input = inputs[0];
        if (!input || !input[0]) return true;

        const channelData = input[0]; // mono 채널

        for (let i = 0; i < channelData.length; i++) {
            this._buffer[this._bytesWritten] = channelData[i];
            this._bytesWritten++;

            if (this._bytesWritten >= this._bufferSize) {
                this._flush();
            }
        }

        return true; // true를 반환해야 프로세서가 계속 동작
    }
}

registerProcessor('pcm-processor', PCMProcessor);
