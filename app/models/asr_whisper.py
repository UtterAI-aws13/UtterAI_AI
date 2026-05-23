from app.models.base import BaseModelWrapper
from app.schemas import ASRResult


class WhisperASRWrapper(BaseModelWrapper):
    def __init__(self, model_name: str, device: str = "cuda", language: str = "ko"):
        self.model_name = model_name
        self.device = device
        self.language = language
        self.pipeline = None

    def load(self) -> None:
        # TODO: transformers pipeline 또는 faster-whisper 로드
        pass

    def predict(self, audio_path: str) -> ASRResult:
        # TODO: STT 추론 후 ASRResult 반환
        return ASRResult(text="", segments=[])

    def unload(self) -> None:
        self.pipeline = None
