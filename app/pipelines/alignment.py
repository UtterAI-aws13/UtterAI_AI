# 발화 정렬(alignment) 파이프라인
# VAD(SpeechSegment), 화자 분리(SpeakerSegment), STT(ASRSegment) 세 결과를 합쳐
# 최종 발화 단위(Utterance)를 생성한다
#
# 정렬 기준: ASR segment와 가장 많이 시간이 겹치는 SpeakerSegment를 해당 발화의 화자로 선택
# Kiwi 형태소 분석으로 morphemes(MLU용)와 tokens(NTW/NDW/TTR용)를 채운다
from app.schemas import SpeechSegment, SpeakerSegment, ASRSegment, Utterance, Morpheme, UtteranceSource

_kiwi = None


def _get_kiwi():
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    return _kiwi


def _analyze_text(text: str) -> tuple[list[Morpheme], list[str]]:
    """Kiwi 형태소 분석으로 morphemes와 공백 기준 tokens를 반환한다.

    Kiwi 로드 실패 시 빈 morphemes와 공백 분리 tokens로 폴백한다.
    """
    try:
        kiwi = _get_kiwi()
        result = kiwi.tokenize(text)
        morphemes = [Morpheme(form=t.form, tag=str(t.tag)) for t in result]
    except Exception:
        morphemes = []
    tokens = [t for t in text.split() if t]
    return morphemes, tokens


def calculate_overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """두 시간 구간이 겹치는 길이(초)를 반환한다. 겹치지 않으면 0.0."""
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def align_segments(
    speech_segments: list[SpeechSegment],
    speaker_segments: list[SpeakerSegment],
    asr_segments: list[ASRSegment],
) -> list[Utterance]:
    """ASR 구간마다 overlap이 가장 큰 화자를 선택해 Utterance 리스트를 생성한다.

    speaker_role은 이 단계에서 pyannote 원본 값을 유지한다.
    UNKNOWN이면 이후 치료사 지정 또는 자동 추정 로직에서 업데이트한다.
    """
    utterances: list[Utterance] = []

    for asr in sorted(asr_segments, key=lambda s: s.start_time):
        best_speaker: SpeakerSegment | None = None
        best_overlap = 0.0

        for spk in speaker_segments:
            overlap = calculate_overlap(asr.start_time, asr.end_time, spk.start_time, spk.end_time)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = spk

        speaker_id = best_speaker.speaker_id if best_speaker else "UNKNOWN"
        speaker_role = best_speaker.speaker_role if best_speaker else "UNKNOWN"

        morphemes, tokens = _analyze_text(asr.text)

        utterances.append(Utterance(
            utterance_id=f"utt_{asr.asr_segment_id}",
            speaker_id=speaker_id,
            speaker_role=speaker_role,
            start_time=asr.start_time,
            end_time=asr.end_time,
            duration_sec=round(asr.end_time - asr.start_time, 3),
            text=asr.text,
            asr_confidence=asr.confidence,
            morphemes=morphemes,
            tokens=tokens,
            source=UtteranceSource(asr_segment_id=asr.asr_segment_id),
        ))

    return utterances
