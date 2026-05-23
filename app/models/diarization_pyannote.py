# pyannote 화자 분리 모델 래퍼
# pyannote/speaker-diarization-3.1 사용, GPU 권장
# Hugging Face 토큰 및 모델 접근 권한(gated model)이 필요하다
from app.models.base import BaseModelWrapper
from app.schemas import SpeakerSegment


class PyannoteWrapper(BaseModelWrapper):
    """pyannote.audio 화자 분리 파이프라인 래퍼.

    출력은 SPEAKER_00, SPEAKER_01 형태의 익명 레이블이다.
    CHILD / THERAPIST 역할 매핑은 alignment 이후 별도로 처리한다.
    """
    def __init__(self, model_name: str, device: str = "cuda", hf_token: str = ""):
        self.model_name = model_name
        self.device = device
        self.hf_token = hf_token   # gated model 접근용 HF 토큰
        self.pipeline = None

    def load(self) -> None:
        # TODO: pyannote.audio Pipeline 로드 (use_auth_token=self.hf_token)
        pass

    def predict(self, audio_path: str) -> list[SpeakerSegment]:
        """음성 파일을 입력받아 화자별 시간 구간 목록을 반환한다."""
        # TODO: 화자 분리 추론 후 SpeakerSegment 리스트 반환
        return []

    def unload(self) -> None:
        self.pipeline = None
