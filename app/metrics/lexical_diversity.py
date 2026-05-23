from app.schemas import Utterance


def calculate_ntw(utterances: list[Utterance]) -> int:
    """Number of Total Words"""
    return sum(len(u.tokens) for u in utterances)


def calculate_ndw(utterances: list[Utterance]) -> int:
    """Number of Different Words"""
    all_tokens = [token for u in utterances for token in u.tokens]
    return len(set(all_tokens))


def calculate_ttr(utterances: list[Utterance]) -> float:
    """Type Token Ratio = NDW / NTW"""
    ntw = calculate_ntw(utterances)
    if ntw == 0:
        return 0.0
    return calculate_ndw(utterances) / ntw
