# 언어 지표 계산 파이프라인
# Utterance 목록을 받아 화자별로 MLU, NDW, NTW, TTR, 반응 지연 시간을 계산한다
#
# response_latency는 전체 발화 흐름에서 THERAPIST→CHILD 전환 구간을 탐색하므로
# 화자 그룹별이 아닌 전체 utterances를 시간순으로 정렬한 뒤 한 번만 계산한다.
# 결과는 CHILD 화자의 LanguageMetrics에만 포함하고, 나머지 화자는 None으로 둔다.
from collections import defaultdict

from app.schemas import Utterance, LanguageMetrics, SpeakerMetrics
from app.metrics import mlu, lexical_diversity, response_latency


def calculate_metrics(utterances: list[Utterance], session_id: str) -> list[SpeakerMetrics]:
    """Utterance 목록에서 화자별 언어 지표를 계산해 SpeakerMetrics 목록을 반환한다.

    speaker_role이 미확정(UNKNOWN)인 경우 모든 화자의 지표를 출력해
    치료사가 직접 CHILD 화자를 선택할 수 있게 한다.
    """
    if not utterances:
        return []

    sorted_utts = sorted(utterances, key=lambda u: u.start_time)

    # THERAPIST→CHILD 전환 탐색은 전체 흐름 기준으로 한 번만 계산
    global_latency = response_latency.calculate_average_response_latency(sorted_utts)

    # 화자별 그룹핑 (speaker_id 기준)
    groups: dict[str, list[Utterance]] = defaultdict(list)
    for u in sorted_utts:
        groups[u.speaker_id].append(u)

    result: list[SpeakerMetrics] = []

    for speaker_id, utts in groups.items():
        speaker_role = utts[0].speaker_role

        mlu_val = mlu.calculate_mlu(utts)
        ntw_val = lexical_diversity.calculate_ntw(utts)
        ndw_val = lexical_diversity.calculate_ndw(utts)
        ttr_val = lexical_diversity.calculate_ttr(utts)

        # 반응 지연 시간은 CHILD 화자에게만 의미 있는 지표
        latency = global_latency if speaker_role == "CHILD" else None

        warnings: list[str] = []
        if speaker_role == "UNKNOWN":
            warnings.append("speaker_role_not_assigned")
        if all(len(u.morphemes) == 0 for u in utts):
            warnings.append("morphemes_empty_mlu_may_be_zero")

        metrics = LanguageMetrics(
            session_id=session_id,
            target_speaker=speaker_role if speaker_role != "UNKNOWN" else speaker_id,
            total_utterances=len(utts),
            ntw=ntw_val,
            ndw=ndw_val,
            ttr=round(ttr_val, 4),
            mlu_morpheme=round(mlu_val, 2),
            average_response_latency_sec=latency,
            warnings=warnings,
        )

        result.append(SpeakerMetrics(
            speaker_id=speaker_id,
            speaker_role=speaker_role,
            metrics=metrics,
        ))

    return result
