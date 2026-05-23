from app.schemas import SpeechSegment, SpeakerSegment, ASRSegment, Utterance


def calculate_overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def align_segments(
    speech_segments: list[SpeechSegment],
    speaker_segments: list[SpeakerSegment],
    asr_segments: list[ASRSegment],
) -> list[Utterance]:
    # TODO: ASR segment마다 overlap 최대 speaker 선택 후 Utterance 생성
    raise NotImplementedError
