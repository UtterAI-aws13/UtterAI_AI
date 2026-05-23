from app.models.base import BaseModelWrapper
from app.schemas import SpeechSegment


class SileroVADWrapper(BaseModelWrapper):
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

    def load(self) -> None:
        # TODO: ONNX Runtime 기반 silero-vad 로드
        pass

    def predict(self, audio_path: str) -> list[SpeechSegment]:
        # TODO: VAD 추론 후 SpeechSegment 리스트 반환
        return []

    def unload(self) -> None:
        self.model = None
