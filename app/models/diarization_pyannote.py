# pyannote 화자 분리 모델 래퍼
# pyannote/speaker-diarization-3.1 사용, GPU 권장
# Hugging Face 토큰 및 모델 접근 권한(gated model)이 필요하다
from app.models.base import BaseModelWrapper
from app.schemas import SpeakerSegment


class PyannoteWrapper(BaseModelWrapper):
    """pyannote.audio 화자 분리 파이프라인 래퍼.

    출력은 SPEAKER_00, SPEAKER_01 형태의 익명 레이블이다.
    PATIENT / SLP 역할 매핑은 alignment 이후 별도로 처리한다.
    """
    def __init__(self, model_name: str, device: str = "cuda", hf_token: str = ""):
        self.model_name = model_name
        self.device = device
        self.hf_token = hf_token   # gated model 접근용 HF 토큰
        self.pipeline = None

    def load(self) -> None:
        from pyannote.audio import Pipeline
        import torch

        self.pipeline = Pipeline.from_pretrained(
            self.model_name,
            use_auth_token=self.hf_token or None,
        )
        if self.device == "cuda" and torch.cuda.is_available():
            self.pipeline.to(torch.device("cuda"))

    def predict(self, audio_path: str) -> list[SpeakerSegment]:
        """음성 파일을 입력받아 화자별 시간 구간 목록을 반환한다."""
        import torchaudio
        # torchcodec/Windows DLL 문제 우회: 파일 경로 대신 waveform 텐서를 전달한다
        waveform, sample_rate = torchaudio.load(audio_path)
        diarization = self.pipeline({"waveform": waveform, "sample_rate": sample_rate})

        # pyannote ≥3.3 returns DiarizeOutput with .speaker_diarization; older returns Annotation directly
        if hasattr(diarization, "speaker_diarization"):
            diarization = diarization.speaker_diarization

        segments: list[SpeakerSegment] = []
        for i, (turn, _, speaker) in enumerate(diarization.itertracks(yield_label=True)):
            segments.append(SpeakerSegment(
                speaker_segment_id=f"spk_{i:03d}",
                speaker_id=speaker,
                speaker_role="UNKNOWN",
                start_time=round(turn.start, 3),
                end_time=round(turn.end, 3),
            ))

        return segments

    def unload(self) -> None:
        self.pipeline = None
