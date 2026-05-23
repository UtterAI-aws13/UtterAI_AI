# 어휘 다양성 지표 계산: NTW, NDW, TTR
# tokens 필드(공백 기준 단어 목록)를 기반으로 계산한다
#
# NTW (Number of Total Words): 총 단어 수 - 발화량 지표
# NDW (Number of Different Words): 서로 다른 단어 수 - 어휘 다양성 지표
# TTR (Type Token Ratio = NDW / NTW): 발화량이 늘수록 낮아지므로 단독 판단 금지
from app.schemas import Utterance


def calculate_ntw(utterances: list[Utterance]) -> int:
    """모든 발화의 토큰 수를 합산한다 (중복 포함)."""
    return sum(len(u.tokens) for u in utterances)


def calculate_ndw(utterances: list[Utterance]) -> int:
    """모든 발화의 토큰을 합쳐 중복을 제거한 고유 단어 수를 반환한다."""
    all_tokens = [token for u in utterances for token in u.tokens]
    return len(set(all_tokens))


def calculate_ttr(utterances: list[Utterance]) -> float:
    """TTR = NDW / NTW. 발화가 없으면 0.0을 반환한다."""
    ntw = calculate_ntw(utterances)
    if ntw == 0:
        return 0.0
    return calculate_ndw(utterances) / ntw
