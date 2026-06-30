# LLU (Longest Length of Utterance) — 최장 발화 길이
# 형태소 기준(llu_morpheme)과 단어(토큰) 기준(llu_word) 두 가지를 제공한다.
# MLU와 함께 봐야 발화 능력의 상한선을 파악할 수 있다.
from app.schemas import Utterance


def calculate_llu_morpheme(utterances: list[Utterance]) -> int:
    """가장 긴 단일 발화의 형태소 수를 반환한다. 발화가 없으면 0."""
    if not utterances:
        return 0
    return max(len(u.morphemes) for u in utterances)


def calculate_llu_word(utterances: list[Utterance]) -> int:
    """가장 긴 단일 발화의 토큰(어절) 수를 반환한다. 발화가 없으면 0."""
    if not utterances:
        return 0
    return max(len(u.tokens) for u in utterances)