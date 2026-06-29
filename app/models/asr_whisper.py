# Whisper STT 모델 래퍼 — faster-whisper (CTranslate2) 기반
# Systran/faster-whisper-large-v3-turbo 사용, GPU 권장
#
# transformers pipeline 대비:
#   - 장문 오디오 청킹/타임스탬프 처리가 안정적 (40초 잘림 없음)
#   - 동일 GPU에서 2~4배 빠름
#   - VAD 없이도 전체 오디오 커버
from __future__ import annotations

from loguru import logger

from app.models.base import BaseModelWrapper
from app.schemas import ASRResult, ASRSegment, SpeechSegment

# VAD 구간 그룹화 파라미터 (predict_with_vad 에서 사용)
_VAD_MAX_GROUP_DURATION_S = 25.0
_VAD_MAX_GAP_S = 2.0
_VAD_AUDIO_PAD_S = 0.15


class WhisperASRWrapper(BaseModelWrapper):
    """faster-whisper 기반 Whisper ASR 래퍼.

    predict_with_vad(): analysis_pipeline에서 호출 (권장)
    predict():          직접 호출용 폴백
    """

    def __init__(
        self,
        model_name: str,
        device: str = "cuda",
        language: str = "ko",
        beam_size: int = 5,
        compute_type: str | None = None,
    ):
        self.model_name = model_name
        self.device = device
        self.language = language
        self.beam_size = beam_size
        # device에 맞는 compute_type 자동 선택
        self.compute_type = compute_type or ("float16" if device == "cuda" else "int8")
        self.model = None

    def load(self) -> None:
        from faster_whisper import WhisperModel

        self.model = WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
        )
        logger.info(
            f"[ASR] faster-whisper 로드 완료: model={self.model_name}, "
            f"device={self.device}, compute_type={self.compute_type}"
        )

    # ------------------------------------------------------------------
    # 메인 인터페이스 (analysis_pipeline → predict_with_vad 호출)
    # ------------------------------------------------------------------

    def predict_with_vad(
        self,
        audio_path: str,
        speech_segments: list[SpeechSegment],
    ) -> ASRResult:
        """faster-whisper는 장문 오디오를 자체적으로 정확히 처리하므로
        전체 오디오에 대해 직접 전사한다. speech_segments는 alignment에서 사용.
        """
        return self.predict(audio_path)

    def predict(self, audio_path: str) -> ASRResult:
        """오디오 파일 전체를 전사해 ASRResult를 반환한다."""
        segments_gen, info = self.model.transcribe(
            audio_path,
            language=self.language,
            beam_size=self.beam_size,
            word_timestamps=False,
            vad_filter=False,    # Stage 1 SileroVAD 결과를 별도로 사용
            condition_on_previous_text=False,  # 청크 간 컨텍스트 전파 차단
        )

        raw_chunks: list[dict] = []
        for seg in segments_gen:  # generator → list 소비
            raw_chunks.append({
                "timestamp": (seg.start, seg.end),
                "text": seg.text,
            })

        audio_duration = info.duration

        if raw_chunks:
            last_end = raw_chunks[-1]["timestamp"][1]
            logger.info(
                f"[ASR] faster-whisper 완료: "
                f"duration={audio_duration:.2f}s, segments={len(raw_chunks)}, "
                f"coverage={last_end:.2f}s"
            )
            if last_end < audio_duration - 5.0:
                logger.warning(
                    f"[ASR] 커버리지 부족: last_end={last_end:.2f}s < "
                    f"audio_duration={audio_duration:.2f}s "
                    f"(손실 {audio_duration - last_end:.2f}s)"
                )
        else:
            logger.warning("[ASR] 전사 결과 없음")

        full_text = " ".join(
            c["text"].strip() for c in raw_chunks if c["text"].strip()
        )
        segments = self._postprocess_chunks(raw_chunks, audio_duration)
        return ASRResult(text=full_text, segments=segments)

    # ------------------------------------------------------------------
    # 후처리
    # ------------------------------------------------------------------

    def _postprocess_chunks(
        self, chunks: list[dict], audio_duration: float
    ) -> list[ASRSegment]:
        """faster-whisper 세그먼트 출력을 정제해 ASRSegment 목록을 반환한다.

        처리 순서:
        1. 빈 텍스트 제거
        2. 시작 시간 기준 정렬
        3. None end timestamp 수정
        4. end <= start 보정
        5. 겹치는 세그먼트 제거
        6. 연속 중복 텍스트 제거 (환각 루프 방어)
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
                seg["end"] = (
                    parsed[i + 1]["start"] if i + 1 < len(parsed) else audio_duration
                )

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

        # 6. 연속 중복 텍스트 제거
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
        self.model = None


# ------------------------------------------------------------------
# VAD 세그먼트 그룹화 유틸리티 (테스트 및 향후 확장용)
# ------------------------------------------------------------------

def _group_vad_segments(
    segments: list[SpeechSegment],
    max_duration: float = _VAD_MAX_GROUP_DURATION_S,
    max_gap: float = _VAD_MAX_GAP_S,
) -> list[tuple[float, float]]:
    """VAD 세그먼트를 Whisper 청크 단위로 그룹화한다."""
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
