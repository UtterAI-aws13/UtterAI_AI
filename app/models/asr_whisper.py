# Whisper STT 모델 래퍼
# openai/whisper-large-v3-turbo 사용, GPU 권장
# 한국어 음성을 텍스트로 전사하고 segment별 timestamp를 함께 반환한다
# timestamp가 있어야 화자 분리 결과와 정렬(alignment)할 수 있다
from loguru import logger

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
        batch_size: int = 1,
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
        import soundfile as sf
        import numpy as np

        # 오디오를 numpy array로 직접 읽어 파이프라인에 전달한다.
        # 파일 경로 전달 시 내부 ffmpeg 리샘플링과 soundfile 중복 읽기로
        # 인코딩에 따라 길이가 다르게 계산되는 문제를 방지한다.
        audio, sr = sf.read(audio_path, dtype="float32")
        if audio.ndim > 1:
            audio = audio[:, 0]
        if sr != 16000:
            import librosa
            audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)
            sr = 16000
        audio_duration = len(audio) / sr

        logger.info(
            f"[ASR] 오디오 로드 완료: duration={audio_duration:.2f}s, "
            f"samples={len(audio)}, sr={sr}"
        )

        # condition_on_previous_text=False: 이전 청크 텍스트를 다음 청크 컨텍스트로
        # 쓰지 않음. True(기본값)이면 이전 청크에서 발생한 할루시네이션이
        # 이후 청크로 전파되어 조기 종료 또는 반복 루프가 생길 수 있다.
        result = self.pipeline(
            {"raw": audio, "sampling_rate": sr},
            generate_kwargs={
                "language": self.language,
                "condition_on_previous_text": False,
            },
            return_timestamps=True,
            chunk_length_s=self.chunk_length_s,
            stride_length_s=(self.stride_length_s, self.stride_length_s),
            batch_size=self.batch_size,
        )

        full_text: str = result["text"].strip()
        raw_chunks: list[dict] = result.get("chunks", [])

        # 파이프라인 원본 출력 진단 로그
        if raw_chunks:
            first_ts = raw_chunks[0].get("timestamp", (None, None))
            last_ts = raw_chunks[-1].get("timestamp", (None, None))
            logger.info(
                f"[ASR] 파이프라인 원본: chunks={len(raw_chunks)}, "
                f"first={first_ts}, last={last_ts}, "
                f"audio_duration={audio_duration:.2f}s"
            )
            # 마지막 청크 end가 오디오 전체 길이 대비 얼마나 커버하는지 확인
            last_end = last_ts[1] if last_ts[1] is not None else last_ts[0]
            if last_end is not None and last_end < audio_duration - 5.0:
                logger.warning(
                    f"[ASR] 파이프라인 출력이 오디오보다 짧음: "
                    f"last_end={last_end:.2f}s, audio_duration={audio_duration:.2f}s "
                    f"(손실={audio_duration - last_end:.2f}s) — "
                    f"Whisper 할루시네이션 또는 chunk 누락 가능성"
                )
        else:
            logger.warning("[ASR] 파이프라인이 빈 chunks를 반환했습니다")

        segments = self._postprocess_chunks(raw_chunks, audio_duration)

        logger.info(
            f"[ASR] 후처리 완료: segments={len(segments)}, "
            f"coverage={segments[-1].end_time:.2f}s/{audio_duration:.2f}s"
            if segments else "[ASR] 후처리 결과 없음"
        )

        return ASRResult(text=full_text, segments=segments)

    def _postprocess_chunks(self, chunks: list[dict], audio_duration: float) -> list[ASRSegment]:
        """Whisper 청크 출력을 정제해 ASRSegment 목록을 반환한다.

        처리 순서:
        1. 빈 텍스트 제거
        2. 시작 시간 기준 정렬
        3. None end timestamp 수정 (다음 세그먼트 시작 또는 오디오 전체 길이)
        4. end <= start 보정
        5. 겹치는 세그먼트 제거 (청크 경계 스티칭 아티팩트)
        6. 연속 중복 텍스트 제거 (Whisper 환각 루프)
        """
        # 1. 파싱 + 빈 텍스트 필터
        parsed: list[dict] = []
        for chunk in chunks:
            ts = chunk.get("timestamp") or (None, None)
            text = chunk.get("text", "").strip()
            if not text:
                continue
            start = float(ts[0]) if ts[0] is not None else 0.0
            end = float(ts[1]) if ts[1] is not None else None
            parsed.append({"start": start, "end": end, "text": text})

        # 2. 시작 시간 기준 정렬
        parsed.sort(key=lambda s: s["start"])

        # 3. None end timestamp 수정
        for i, seg in enumerate(parsed):
            if seg["end"] is None:
                seg["end"] = parsed[i + 1]["start"] if i + 1 < len(parsed) else audio_duration

        # 4. end <= start 보정 (Whisper가 동일한 timestamp를 반환하는 엣지케이스)
        for seg in parsed:
            if seg["end"] <= seg["start"]:
                seg["end"] = seg["start"] + 0.5

        # 5. 겹치는 세그먼트 제거 (forward sweep)
        #    청크 경계에서 stride 처리가 겹칠 경우 나중 세그먼트를 건너뜀
        filtered: list[dict] = []
        cursor = 0.0
        for seg in parsed:
            if seg["start"] >= cursor:
                filtered.append(seg)
                cursor = seg["end"]

        # 6. 연속 중복 텍스트 제거 (Whisper 환각 루프 방어)
        deduped: list[dict] = []
        prev_text: str | None = None
        for seg in filtered:
            if seg["text"] != prev_text:
                deduped.append(seg)
            prev_text = seg["text"]

        return [
            ASRSegment(
                asr_segment_id=f"asr_{i:03d}",
                start_time=round(seg["start"], 3),
                end_time=round(seg["end"], 3),
                text=seg["text"],
                confidence=1.0,
            )
            for i, seg in enumerate(deduped)
        ]

    def unload(self) -> None:
        self.pipeline = None