"""WhisperASRWrapper._postprocess_chunks 및 _group_vad_segments 단위 테스트.

GPU/모델 없이 후처리 로직만 검증한다.
"""
import pytest
from app.models.asr_whisper import WhisperASRWrapper, _group_vad_segments
from app.schemas import SpeechSegment


@pytest.fixture
def asr():
    """모델 로드 없이 인스턴스만 생성한다."""
    return WhisperASRWrapper(model_name="dummy")


def _chunk(start, end, text):
    return {"timestamp": (start, end), "text": text}


def _seg(asr_instance, chunks, audio_duration):
    return asr_instance._postprocess_chunks(chunks, audio_duration)


class TestEmptyTextFilter:
    def test_removes_empty_text(self, asr):
        chunks = [_chunk(0.0, 5.0, "   "), _chunk(5.0, 10.0, "안녕")]
        segs = _seg(asr, chunks, 10.0)
        assert len(segs) == 1
        assert segs[0].text == "안녕"

    def test_all_empty_returns_empty(self, asr):
        chunks = [_chunk(0.0, 5.0, ""), _chunk(5.0, 10.0, "  ")]
        segs = _seg(asr, chunks, 10.0)
        assert segs == []


class TestTimestampFix:
    def test_none_end_uses_next_start(self, asr):
        chunks = [_chunk(0.0, None, "첫번째"), _chunk(5.0, 10.0, "두번째")]
        segs = _seg(asr, chunks, 10.0)
        assert segs[0].end_time == 5.0

    def test_none_end_last_segment_uses_audio_duration(self, asr):
        chunks = [_chunk(0.0, 5.0, "첫번째"), _chunk(5.0, None, "마지막")]
        segs = _seg(asr, chunks, 12.5)
        assert segs[1].end_time == 12.5

    def test_end_equal_start_gets_half_second_pad(self, asr):
        chunks = [_chunk(3.0, 3.0, "짧은")]
        segs = _seg(asr, chunks, 10.0)
        assert segs[0].end_time == pytest.approx(3.5)

    def test_end_before_start_gets_half_second_pad(self, asr):
        chunks = [_chunk(5.0, 4.0, "역방향")]
        segs = _seg(asr, chunks, 10.0)
        assert segs[0].end_time == pytest.approx(5.5)


class TestSorting:
    def test_out_of_order_chunks_sorted(self, asr):
        chunks = [_chunk(10.0, 15.0, "나중"), _chunk(0.0, 5.0, "먼저")]
        segs = _seg(asr, chunks, 15.0)
        assert segs[0].text == "먼저"
        assert segs[1].text == "나중"


class TestOverlapRemoval:
    def test_overlapping_segment_skipped(self, asr):
        # 청크1 [0-25], 청크2 [20-45] → 20-25 겹침 → 청크2 건너뜀
        chunks = [_chunk(0.0, 25.0, "청크1"), _chunk(20.0, 45.0, "청크2겹침")]
        segs = _seg(asr, chunks, 45.0)
        assert len(segs) == 1
        assert segs[0].text == "청크1"

    def test_non_overlapping_both_kept(self, asr):
        chunks = [_chunk(0.0, 25.0, "청크1"), _chunk(25.0, 50.0, "청크2")]
        segs = _seg(asr, chunks, 50.0)
        assert len(segs) == 2

    def test_segment_ids_renumbered_after_filter(self, asr):
        chunks = [
            _chunk(0.0, 10.0, "A"),
            _chunk(5.0, 15.0, "겹침B"),   # 건너뜀
            _chunk(10.0, 20.0, "C"),
        ]
        segs = _seg(asr, chunks, 20.0)
        assert segs[0].asr_segment_id == "asr_000"
        assert segs[1].asr_segment_id == "asr_001"


class TestHallucinationFilter:
    def test_consecutive_duplicate_text_removed(self, asr):
        chunks = [
            _chunk(0.0, 5.0, "반복"),
            _chunk(5.0, 10.0, "반복"),
            _chunk(10.0, 15.0, "다른"),
        ]
        segs = _seg(asr, chunks, 15.0)
        assert len(segs) == 2
        assert segs[0].text == "반복"
        assert segs[1].text == "다른"

    def test_non_consecutive_same_text_kept(self, asr):
        # "반복" → "다른" → "반복" 순서는 모두 유지
        chunks = [
            _chunk(0.0, 5.0, "반복"),
            _chunk(5.0, 10.0, "다른"),
            _chunk(10.0, 15.0, "반복"),
        ]
        segs = _seg(asr, chunks, 15.0)
        assert len(segs) == 3


class TestSegmentIds:
    def test_ids_are_sequential_zero_padded(self, asr):
        chunks = [_chunk(float(i * 5), float((i + 1) * 5), f"텍스트{i}") for i in range(5)]
        segs = _seg(asr, chunks, 25.0)
        for i, seg in enumerate(segs):
            assert seg.asr_segment_id == f"asr_{i:03d}"


class TestRounding:
    def test_timestamps_rounded_to_three_decimals(self, asr):
        chunks = [_chunk(0.1234567, 5.9876543, "텍스트")]
        segs = _seg(asr, chunks, 10.0)
        assert segs[0].start_time == pytest.approx(0.123, abs=1e-9)
        assert segs[0].end_time == pytest.approx(5.988, abs=1e-9)


def _vad(seg_id, start, end):
    return SpeechSegment(
        segment_id=seg_id,
        start_time=start,
        end_time=end,
        duration_sec=round(end - start, 3),
        confidence=0.9,
    )


class TestVadGrouping:
    """_group_vad_segments 단위 테스트."""

    def test_single_segment_returns_one_group(self):
        segs = [_vad("v0", 1.0, 5.0)]
        groups = _group_vad_segments(segs)
        assert groups == [(1.0, 5.0)]

    def test_close_segments_merged_into_one_group(self):
        # gap=0.5s < max_gap=2s → 하나로 묶임
        segs = [_vad("v0", 0.0, 5.0), _vad("v1", 5.5, 10.0)]
        groups = _group_vad_segments(segs)
        assert len(groups) == 1
        assert groups[0] == (0.0, 10.0)

    def test_large_gap_splits_into_two_groups(self):
        # gap=3s > max_gap=2s → 두 그룹
        segs = [_vad("v0", 0.0, 5.0), _vad("v1", 8.0, 13.0)]
        groups = _group_vad_segments(segs)
        assert len(groups) == 2

    def test_max_duration_exceeded_splits_group(self):
        # 첫 두 세그먼트 합산이 max_duration=25s 초과 → 분할
        segs = [
            _vad("v0", 0.0, 15.0),
            _vad("v1", 15.5, 26.0),  # extended=26s > 25s
            _vad("v2", 26.5, 30.0),
        ]
        groups = _group_vad_segments(segs)
        assert len(groups) >= 2
        for g_start, g_end in groups:
            assert g_end - g_start <= 26.0  # 단일 세그먼트는 예외 허용

    def test_empty_segments_returns_empty(self):
        assert _group_vad_segments([]) == []

    def test_60s_audio_produces_multiple_groups(self):
        # 60초 오디오, 자연스러운 발화 패턴
        segs = [
            _vad("v0", 0.5, 8.0),
            _vad("v1", 8.5, 15.0),
            _vad("v2", 15.5, 22.0),
            _vad("v3", 25.0, 35.0),  # 3s gap → 새 그룹
            _vad("v4", 36.0, 45.0),
            _vad("v5", 50.0, 58.0),  # 5s gap → 새 그룹
        ]
        groups = _group_vad_segments(segs)
        # 전체 발화 구간이 모두 포함되어야 한다
        all_covered_start = min(g[0] for g in groups)
        all_covered_end = max(g[1] for g in groups)
        assert all_covered_start <= 0.5
        assert all_covered_end >= 58.0


class TestSixtySecondCoverage:
    """60초 오디오에서 3청크 처리 시 전체 커버리지 검증 (핵심 버그 재현 시나리오)."""

    def test_three_chunks_full_coverage(self, asr):
        # chunk=30, stride=5, step=20 → 60s 오디오: 3청크
        # Chunk 0: [0-30], 유효 [0-25]
        # Chunk 1: [20-50], 유효 [25-45]
        # Chunk 2: [40-60], 유효 [45-60]
        chunks = [
            _chunk(0.0, 5.0, "발화1"),
            _chunk(5.0, 12.0, "발화2"),
            _chunk(12.0, 25.0, "발화3"),   # chunk 0 유효 끝
            _chunk(25.0, 35.0, "발화4"),
            _chunk(35.0, 45.0, "발화5"),   # chunk 1 유효 끝
            _chunk(45.0, 52.0, "발화6"),
            _chunk(52.0, 60.0, "발화7"),   # chunk 2 유효 끝 = 오디오 끝
        ]
        segs = _seg(asr, chunks, 60.0)
        assert len(segs) == 7
        assert segs[-1].end_time == 60.0, "마지막 세그먼트가 60초까지 커버해야 한다"

    def test_transcript_not_truncated_at_40s(self, asr):
        # 40초 이후에도 발화가 있어야 한다
        chunks = [
            _chunk(0.0, 20.0, "앞부분"),
            _chunk(20.0, 40.0, "중간부분"),
            _chunk(40.0, 60.0, "뒷부분"),  # 40초 이후 발화
        ]
        segs = _seg(asr, chunks, 60.0)
        last_end = max(s.end_time for s in segs)
        assert last_end == 60.0, f"전사문이 {last_end}초에서 잘림 (60초여야 함)"
        texts = [s.text for s in segs]
        assert "뒷부분" in texts, "40초 이후 발화가 전사문에 포함되어야 한다"
