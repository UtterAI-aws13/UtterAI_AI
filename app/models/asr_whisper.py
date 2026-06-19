# Whisper STT 모델 래퍼
# openai/whisper-large-v3-turbo 사용, GPU 권장
# 한국어 음성을 텍스트로 전사하고 segment별 timestamp를 함께 반환한다
# timestamp가 있어야 화자 분리 결과와 정렬(alignment)할 수 있다
from app.models.base import BaseModelWrapper
from app.schemas import ASRResult, ASRSegment


class WhisperASRWrapper(BaseModelWrapper):
    """Whisper ASR 모델 래퍼.

    transformers pipeline 방식과 faster-whisper 방식 중 하나를 선택해 구현한다.
    faster-whisper는 CTranslate2 기반으로 GPU 메모리 효율이 더 좋다.
    """
    def __init__(
        self,
        model_name: str,
        device: str = "cuda",
        language: str = "ko",
        chunk_length_s: int = 30,
        stride_length_s: int = 5,
        batch_size: int = 8,
    ):
        self.model_name = model_name
        self.device = device
        self.language = language   # 한국어 고정 ("ko")
        self.chunk_length_s = chunk_length_s
        self.stride_length_s = stride_length_s
        self.batch_size = batch_size
        self.pipeline = None

    def load(self) -> None:
        import torch
        from transformers import pipeline

        device = 0 if self.device == "cuda" and torch.cuda.is_available() else -1
        dtype = torch.float16 if device == 0 else torch.float32

        self.pipeline = pipeline(
            "automatic-speech-recognition",
            model=self.model_name,
            device=device,
            torch_dtype=dtype,
        )

    def predict(self, audio_path: str) -> ASRResult:
        """음성 파일을 입력받아 전체 전사 텍스트와 timestamp 포함 구간 목록을 반환한다."""
        result = self.pipeline(
            audio_path,
            generate_kwargs={"language": self.language},
            return_timestamps=True,
            chunk_length_s=self.chunk_length_s,
            stride_length_s=(self.stride_length_s, self.stride_length_s),
            batch_size=self.batch_size,
        )

        full_text: str = result["text"].strip()
        chunks: list[dict] = result.get("chunks", [])

        asr_segments = []
        for i, chunk in enumerate(chunks):
            ts = chunk.get("timestamp") or (None, None)
            start = float(ts[0]) if ts[0] is not None else 0.0
            end = float(ts[1]) if ts[1] is not None else start + 1.0
            asr_segments.append(ASRSegment(
                asr_segment_id=f"asr_{i:03d}",
                start_time=round(start, 3),
                end_time=round(end, 3),
                text=chunk["text"].strip(),
                confidence=1.0,
            ))

        return ASRResult(text=full_text, segments=asr_segments)

    def unload(self) -> None:
        self.pipeline = None
