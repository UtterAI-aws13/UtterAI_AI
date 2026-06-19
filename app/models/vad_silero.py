# Silero VAD 모델 래퍼
# onnx-community/silero-vad를 ONNX Runtime으로 실행한다 (CPU 처리 가능)
# 음성 파일에서 말소리 구간(SpeechSegment)을 추출한다
from app.models.base import BaseModelWrapper
from app.schemas import SpeechSegment


class SileroVADWrapper(BaseModelWrapper):
    """Silero VAD ONNX 모델 래퍼.

    threshold: 음성으로 판단할 최소 확률 (기본 0.5)
    min_speech_duration_ms: 이보다 짧은 발화는 무시 (노이즈 제거)
    min_silence_duration_ms: 이보다 짧은 침묵은 발화로 연결 (연속 발화 처리)
    speech_pad_ms: 발화 앞뒤에 붙이는 여유 시간 (timestamp 정합성 확보)
    """
    def __init__(self, model_name: str, threshold: float = 0.5,
                 min_speech_duration_ms: int = 250,
                 min_silence_duration_ms: int = 500,
                 speech_pad_ms: int = 100):
        self.model_name = model_name
        self.threshold = threshold
        self.min_speech_duration_ms = min_speech_duration_ms
        self.min_silence_duration_ms = min_silence_duration_ms
        self.speech_pad_ms = speech_pad_ms
        self.model = None

    CHUNK_SIZE = 512  # 16kHz 기준 32ms

    def load(self) -> None:
        import numpy as np
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download

        model_path = hf_hub_download(repo_id=self.model_name, filename="onnx/model.onnx")
        self.model = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self._np = np

    def _reset_state(self):
        np = self._np
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._sr = np.array(16000, dtype=np.int64)

    def _speech_prob(self, chunk) -> float:
        x = chunk.reshape(1, -1).astype(self._np.float32)
        out = self.model.run(None, {"input": x, "sr": self._sr, "state": self._state})
        prob, self._state = out
        return float(prob.squeeze())

    def predict(self, audio_path: str) -> list[SpeechSegment]:
        """16kHz mono WAV 파일을 입력받아 말소리 구간 목록을 반환한다."""
        import soundfile as sf

        audio, sr = sf.read(audio_path, dtype="float32")
        if sr != 16000:
            raise ValueError(f"16kHz WAV가 필요합니다. 현재 sr={sr}")
        if audio.ndim > 1:
            audio = audio[:, 0]

        self._reset_state()

        np = self._np
        min_silence = int(self.min_silence_duration_ms * 16000 / 1000)
        min_speech = int(self.min_speech_duration_ms * 16000 / 1000)
        pad = int(self.speech_pad_ms * 16000 / 1000)

        segments: list[SpeechSegment] = []
        in_speech = False
        speech_start = 0
        silence_buf = 0
        seg_idx = 0

        for i in range(0, len(audio), self.CHUNK_SIZE):
            chunk = audio[i:i + self.CHUNK_SIZE]
            if len(chunk) < self.CHUNK_SIZE:
                chunk = np.pad(chunk, (0, self.CHUNK_SIZE - len(chunk)))

            prob = self._speech_prob(chunk)

            if prob >= self.threshold:
                if not in_speech:
                    speech_start = max(0, i - pad)
                    in_speech = True
                silence_buf = 0
            else:
                if in_speech:
                    silence_buf += self.CHUNK_SIZE
                    if silence_buf >= min_silence:
                        speech_end = min(len(audio), i + pad)
                        if (speech_end - speech_start) >= min_speech:
                            s = speech_start / 16000
                            e = speech_end / 16000
                            segments.append(SpeechSegment(
                                segment_id=f"vad_{seg_idx:03d}",
                                start_time=round(s, 3),
                                end_time=round(e, 3),
                                duration_sec=round(e - s, 3),
                                confidence=round(prob, 4),
                            ))
                            seg_idx += 1
                        in_speech = False
                        silence_buf = 0

        if in_speech:
            s = speech_start / 16000
            e = len(audio) / 16000
            if (len(audio) - speech_start) >= min_speech:
                segments.append(SpeechSegment(
                    segment_id=f"vad_{seg_idx:03d}",
                    start_time=round(s, 3),
                    end_time=round(e, 3),
                    duration_sec=round(e - s, 3),
                    confidence=self.threshold,
                ))

        return segments

    def unload(self) -> None:
        self.model = None
