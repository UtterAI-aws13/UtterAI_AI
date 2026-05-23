# 언어 지표 계산 파이프라인
# Utterance 목록을 받아 화자별로 MLU, NDW, NTW, TTR, 반응 지연 시간을 계산한다
# speaker_role이 CHILD로 확정된 경우 아동 발화만 별도로 집계한다
from app.schemas import Utterance, LanguageMetrics, SpeakerMetrics
from app.metrics import mlu, lexical_diversity, response_latency


def calculate_metrics(utterances: list[Utterance], session_id: str) -> list[SpeakerMetrics]:
    """Utterance 목록에서 화자별 언어 지표를 계산해 SpeakerMetrics 목록을 반환한다.

    speaker_role이 미확정(UNKNOWN)인 경우 모든 화자의 지표를 출력해
    치료사가 직접 CHILD 화자를 선택할 수 있게 한다.
    """
    # TODO: speaker별로 그룹핑 후 각 지표 계산
    raise NotImplementedError
