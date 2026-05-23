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

    def load(self) -> None:
        # TODO: ONNX Runtime 기반 silero-vad 로드
        pass

    def predict(self, audio_path: str) -> list[SpeechSegment]:
        """16kHz mono WAV 파일을 입력받아 말소리 구간 목록을 반환한다."""
        # TODO: VAD 추론 후 SpeechSegment 리스트 반환
        return []

    def unload(self) -> None:
        self.model = None
