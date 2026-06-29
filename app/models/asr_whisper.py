# Whisper STT 모델 래퍼
# openai/whisper-large-v3-turbo 사용, GPU 권장
# 한국어 음성을 텍스트로 전사하고 segment별 timestamp를 함께 반환한다
# timestamp가 있어야 화자 분리 결과와 정렬(alignment)할 수 있다
from __future__ import annotations

from loguru import logger

from app.models.base import BaseModelWrapper
from app.schemas import ASRResult, ASRSegment, SpeechSegment

# VAD 구간 그룹화 파라미터
_VAD_MAX_GROUP_DURATION_S = 25.0   # 한 Whisper 호출당 최대 발화 길이 (30s 창 이내)
_VAD_MAX_GAP_S = 2.0               # 이 초 이상 침묵이면 새 그룹 시작
_VAD_AUDIO_PAD_S = 0.15            # 그룹 앞뒤에 붙이는 여백


class WhisperASRWrapper(BaseModelWrapper):
    """Whisper ASR 모델 래퍼.

    predict_with_vad(): VAD 발화 구간을 청크 기준으로 사용 (권장)
    predict():          고정 길이 청킹 폴백 (VAD 없을 때)
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
        self.language = language
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

    # ------------------------------------------------------------------
    # 메인 인터페이스: VAD 기반 전사 (Stage 2에서 호출)
    # ------------------------------------------------------------------

    def predict_with_vad(
        self,
        audio_path: str,
        speech_segments: list[SpeechSegment],
    ) -> ASRResult:
        """VAD 발화 구간을 청크 기준으로 Whisper 전사를 수행한다.

        고정 길이 청킹 대신 VAD가 찾은 발화 경계를 사용하므로:
        - 문장 중간에 청크 경계가 생기지 않는다
        - 침묵 구간을 모델에 노출하지 않아 할루시네이션이 줄어든다
        - 오디오 길이에 무관하게 전체 발화를 커버한다
        """
        import soundfile as sf

        audio, sr = sf.read(audio_path, dtype="float32")
        if audio.ndim > 1:
            audio = audio[:, 0]
        if sr != 16000:
            import librosa
            audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)
            sr = 16000
        audio_duration = len(audio) / sr

        logger.info(
            f"[ASR] 오디오 로드: duration={audio_duration:.2f}s, samples={len(audio)}"
        )

        if not speech_segments:
            logger.warning("[ASR] VAD 세그먼트 없음 → 고정 청킹 폴백")
            return self.predict(audio_path)

        groups = _group_vad_segments(speech_segments)
        logger.info(
            f"[ASR] VAD 그룹: {len(groups)}개 "
            f"(VAD 세그먼트 {len(speech_segments)}개, 오디오 {audio_duration:.1f}s)"
        )

        all_raw_chunks: list[dict] = []

        for i, (group_start, group_end) in enumerate(groups):
            s = max(0, int((group_start - _VAD_AUDIO_PAD_S) * sr))
            e = min(len(audio), int((group_end + _VAD_AUDIO_PAD_S) * sr))
            chunk_audio = audio[s:e]
            chunk_offset = s / sr
            chunk_duration = len(chunk_audio) / sr

            if chunk_duration < 0.1:
                continue

            # 그룹이 chunk_length_s 이내면 파이프라인 청킹 불필요
            use_chunking = chunk_duration > self.chunk_length_s
            pipeline_kwargs: dict = dict(
                generate_kwargs={
                    "language": self.language,
                    "condition_on_previous_text": False,
                },
                return_timestamps=True,
                batch_size=self.batch_size,
            )
            if use_chunking:
                pipeline_kwargs["chunk_length_s"] = self.chunk_length_s
                pipeline_kwargs["stride_length_s"] = (
                    self.stride_length_s,
                    self.stride_length_s,
                )

            result = self.pipeline(
                {"raw": chunk_audio, "sampling_rate": sr},
                **pipeline_kwargs,
            )

            raw = result.get("chunks", [])
            logger.debug(
                f"[ASR] 그룹 {i}: [{group_start:.1f}-{group_end:.1f}s] "
                f"duration={chunk_duration:.1f}s → {len(raw)}개 세그먼트"
            )

            # 그룹 내 상대 timestamp → 절대 timestamp 변환
            for chunk in raw:
                ts = chunk.get("timestamp") or (None, None)
                abs_start = (ts[0] + chunk_offset) if ts[0] is not None else chunk_offset
                abs_end = (ts[1] + chunk_offset) if ts[1] is not None else None
                all_raw_chunks.append({
                    "timestamp": (abs_start, abs_end),
                    "text": chunk.get("text", ""),
                })

        full_text = " ".join(
            c["text"].strip() for c in all_raw_chunks if c["text"].strip()
        )
        segments = self._postprocess_chunks(all_raw_chunks, audio_duration)

        if segments:
            logger.info(
                f"[ASR] 완료: segments={len(segments)}, "
                f"coverage={segments[-1].end_time:.2f}s / {audio_duration:.2f}s"
            )
        else:
            logger.warning("[ASR] 전사 결과 없음")

        return ASRResult(text=full_text, segments=segments)

    # ------------------------------------------------------------------
    # 폴백: 고정 길이 청킹 (VAD 없을 때)
    # ------------------------------------------------------------------

    def predict(self, audio_path: str) -> ASRResult:
        """음성 파일을 고정 길이 청킹으로 전사한다. VAD 없을 때만 사용한다."""
        import soundfile as sf

        audio, sr = sf.read(audio_path, dtype="float32")
        if audio.ndim > 1:
            audio = audio[:, 0]
        if sr != 16000:
            import librosa
            audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)
            sr = 16000
        audio_duration = len(audio) / sr

        logger.info(
            f"[ASR] 고정 청킹 모드: duration={audio_duration:.2f}s, "
            f"chunk={self.chunk_length_s}s, stride={self.stride_length_s}s"
        )

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

        if raw_chunks:
            last_ts = raw_chunks[-1].get("timestamp", (None, None))
            last_end = last_ts[1] if last_ts[1] is not None else last_ts[0]
            logger.info(
                f"[ASR] 파이프라인 원본: chunks={len(raw_chunks)}, "
                f"last_end={last_end}, audio={audio_duration:.2f}s"
            )
            if last_end is not None and last_end < audio_duration - 5.0:
                logger.warning(
                    f"[ASR] 파이프라인 출력이 오디오보다 짧음: "
                    f"{last_end:.2f}s < {audio_duration:.2f}s "
                    f"(손실 {audio_duration - last_end:.2f}s)"
                )
        else:
            logger.warning("[ASR] 파이프라인이 빈 chunks를 반환했습니다")

        segments = self._postprocess_chunks(raw_chunks, audio_duration)
        return ASRResult(text=full_text, segments=segments)

    # ------------------------------------------------------------------
    # 후처리
    # ------------------------------------------------------------------

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

        # 4. end <= start 보정
        for seg in parsed:
            if seg["end"] <= seg["start"]:
                seg["end"] = seg["start"] + 0.5

        # 5. 겹치는 세그먼트 제거 (forward sweep)
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


# ------------------------------------------------------------------
# VAD 세그먼트 그룹화 유틸리티
# ------------------------------------------------------------------

def _group_vad_segments(
    segments: list[SpeechSegment],
    max_duration: float = _VAD_MAX_GROUP_DURATION_S,
    max_gap: float = _VAD_MAX_GAP_S,
) -> list[tuple[float, float]]:
    """VAD 세그먼트를 Whisper 청크 단위로 그룹화한다.

    연속된 발화를 max_duration 이내로 묶는다.
    세그먼트 사이 침묵이 max_gap 이상이거나 그룹이 max_duration을 초과하면
    새 그룹을 시작한다.

    Returns:
        [(group_start_sec, group_end_sec), ...]
    """
    if not segments:
        return []

    groups: list[tuple[float, float]] = []
    group_start = segments[0].start_time
    group_end = segments[0].end_time

    for seg in segments[1:]:
        gap = seg.start_time - group_end
        extended = seg.end_time - group_start

        if gap > max_gap or extended > max_duration:
            groups.append((group_start, group_end))
            group_start = seg.start_time
            group_end = seg.end_time
        else:
            group_end = seg.end_time

    groups.append((group_start, group_end))
    return groups
