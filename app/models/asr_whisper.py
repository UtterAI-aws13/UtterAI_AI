# Whisper STT 모델 래퍼
# openai/whisper-large-v3-turbo 사용, GPU 권장
# 한국어 음성을 텍스트로 전사하고 segment별 timestamp를 함께 반환한다
# timestamp가 있어야 화자 분리 결과와 정렬(alignment)할 수 있다
from app.models.base import BaseModelWrapper
from app.schemas import ASRResult


class WhisperASRWrapper(BaseModelWrapper):
    """Whisper ASR 모델 래퍼.

    transformers pipeline 방식과 faster-whisper 방식 중 하나를 선택해 구현한다.
    faster-whisper는 CTranslate2 기반으로 GPU 메모리 효율이 더 좋다.
    """
    def __init__(self, model_name: str, device: str = "cuda", language: str = "ko"):
        self.model_name = model_name
        self.device = device
        self.language = language   # 한국어 고정 ("ko")
        self.pipeline = None

    def load(self) -> None:
        # TODO: transformers pipeline 또는 faster-whisper 로드
        pass

    def predict(self, audio_path: str) -> ASRResult:
        """음성 파일을 입력받아 전체 전사 텍스트와 timestamp 포함 구간 목록을 반환한다."""
        # TODO: STT 추론 후 ASRResult 반환
        return ASRResult(text="", segments=[])

    def unload(self) -> None:
        self.pipeline = None
