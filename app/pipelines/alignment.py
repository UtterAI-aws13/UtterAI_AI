# 발화 정렬(alignment) 파이프라인
# VAD(SpeechSegment), 화자 분리(SpeakerSegment), STT(ASRSegment) 세 결과를 합쳐
# 최종 발화 단위(Utterance)를 생성한다
#
# 정렬 기준: ASR segment와 가장 많이 시간이 겹치는 SpeakerSegment를 해당 발화의 화자로 선택
from app.schemas import SpeechSegment, SpeakerSegment, ASRSegment, Utterance


def calculate_overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """두 시간 구간이 겹치는 길이(초)를 반환한다. 겹치지 않으면 0.0."""
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def align_segments(
    speech_segments: list[SpeechSegment],
    speaker_segments: list[SpeakerSegment],
    asr_segments: list[ASRSegment],
) -> list[Utterance]:
    """ASR 구간마다 overlap이 가장 큰 화자를 선택해 Utterance 리스트를 생성한다.

    speaker_role은 이 단계에서 UNKNOWN으로 유지되며,
    이후 치료사 지정 또는 자동 추정 로직에서 업데이트된다.
    """
    # TODO: ASR segment마다 overlap 최대 speaker 선택 후 Utterance 생성
    raise NotImplementedError
