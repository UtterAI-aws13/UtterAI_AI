from app.schemas import Utterance, LanguageMetrics, SpeakerMetrics
from app.metrics import mlu, lexical_diversity, response_latency


def calculate_metrics(utterances: list[Utterance], session_id: str) -> list[SpeakerMetrics]:
    # TODO: speaker별로 그룹핑 후 각 지표 계산
    raise NotImplementedError
