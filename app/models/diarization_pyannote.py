from app.models.base import BaseModelWrapper
from app.schemas import SpeakerSegment


class PyannoteWrapper(BaseModelWrapper):
    def __init__(self, model_name: str, device: str = "cuda", hf_token: str = ""):
        self.model_name = model_name
        self.device = device
        self.hf_token = hf_token
        self.pipeline = None

    def load(self) -> None:
        # TODO: pyannote.audio Pipeline 로드
        pass

    def predict(self, audio_path: str) -> list[SpeakerSegment]:
        # TODO: 화자 분리 추론 후 SpeakerSegment 리스트 반환
        return []

    def unload(self) -> None:
        self.pipeline = None
