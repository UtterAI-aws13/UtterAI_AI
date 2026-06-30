# 언어 지표 계산 파이프라인
# Utterance 목록을 받아 화자별로 언어 지표를 계산한다.
#
# response_latency는 전체 발화 흐름에서 SLP→PATIENT 전환 구간을 탐색하므로
# 화자 그룹별이 아닌 전체 utterances를 시간순으로 정렬한 뒤 한 번만 계산한다.
# 결과는 PATIENT 화자의 LanguageMetrics에만 포함하고, 나머지 화자는 None으로 둔다.
#
# FCM 예측도 PATIENT 화자에게만 제공한다.
from collections import defaultdict

from app.metrics import ciu, disfluency, fcm, lexical_diversity, llu, mlu, pcc, response_latency
from app.schemas import LanguageMetrics, SpeakerMetrics, Utterance
from app.schemas.metrics import DisfluencyMetrics, FCMEstimateSchema


def calculate_metrics(utterances: list[Utterance], session_id: str) -> list[SpeakerMetrics]:
    """Utterance 목록에서 화자별 언어 지표를 계산해 SpeakerMetrics 목록을 반환한다.

    speaker_role이 미확정(UNKNOWN)인 경우 모든 화자의 지표를 출력해
    SLP가 직접 PATIENT 화자를 선택할 수 있게 한다.
    """
    if not utterances:
        return []

    sorted_utts = sorted(utterances, key=lambda u: u.start_time)

    # SLP→PATIENT 전환 탐색은 전체 흐름 기준으로 한 번만 계산
    global_latency = response_latency.calculate_average_response_latency(sorted_utts)

    # 화자별 그룹핑 (speaker_id 기준)
    groups: dict[str, list[Utterance]] = defaultdict(list)
    for u in sorted_utts:
        groups[u.speaker_id].append(u)

    result: list[SpeakerMetrics] = []

    for speaker_id, utts in groups.items():
        speaker_role = utts[0].speaker_role

        # 기존 지표
        mlu_val = mlu.calculate_mlu(utts)
        ntw_val = lexical_diversity.calculate_ntw(utts)
        ndw_val = lexical_diversity.calculate_ndw(utts)
        ttr_val = lexical_diversity.calculate_ttr(utts)

        # 신규 지표
        llu_m = llu.calculate_llu_morpheme(utts)
        llu_w = llu.calculate_llu_word(utts)
        pcc_val = pcc.calculate_pcc(utts)

        dis_result = disfluency.calculate_disfluency(utts)
        dis_metrics = DisfluencyMetrics(
            filler_count=dis_result.filler_count,
            repetition_count=dis_result.repetition_count,
            prolongation_count=dis_result.prolongation_count,
            total_count=dis_result.total_disfluency,
            rate=dis_result.disfluency_rate,
        )

        ciu_result = ciu.calculate_ciu(utts)

        # 반응 지연 시간·FCM 예측은 PATIENT 화자에게만 의미 있는 지표
        latency = global_latency if speaker_role == "PATIENT" else None
        fcm_estimate: FCMEstimateSchema | None = None
        if speaker_role == "PATIENT":
            fcm_raw = fcm.estimate_fcm_range(
                mlu_morpheme=mlu_val,
                disfluency_rate=dis_result.disfluency_rate,
                ciu_rate=ciu_result.ciu_rate,
            )
            fcm_estimate = FCMEstimateSchema(
                low=fcm_raw.low,
                high=fcm_raw.high,
                note=fcm_raw.note,
            )

        warnings: list[str] = []
        if speaker_role == "UNKNOWN":
            warnings.append("speaker_role_not_assigned")
        if all(len(u.morphemes) == 0 for u in utts):
            warnings.append("morphemes_empty_mlu_may_be_zero")
        if pcc_val is None:
            warnings.append("pcc_unavailable_no_target_text")
        if ciu_result.total_morphemes == 0:
            warnings.append("ciu_unavailable_morphemes_empty")

        metrics = LanguageMetrics(
            session_id=session_id,
            target_speaker=speaker_role if speaker_role != "UNKNOWN" else speaker_id,
            total_utterances=len(utts),
            ntw=ntw_val,
            ndw=ndw_val,
            ttr=round(ttr_val, 4),
            mlu_morpheme=round(mlu_val, 2),
            avg_response_latency_sec=latency,
            llu_morpheme=llu_m,
            llu_word=llu_w,
            pcc=pcc_val,
            disfluency=dis_metrics,
            ciu_count=ciu_result.ciu_count,
            ciu_rate=ciu_result.ciu_rate,
            fcm_estimate=fcm_estimate,
            warnings=warnings,
        )

        result.append(SpeakerMetrics(
            speaker_id=speaker_id,
            speaker_role=speaker_role,
            metrics=metrics,
        ))

    return result