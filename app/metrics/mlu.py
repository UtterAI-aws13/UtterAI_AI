from app.schemas import Utterance


def calculate_mlu(utterances: list[Utterance]) -> float:
    """형태소 기준 MLU = 전체 형태소 수 / 전체 발화 수"""
    if not utterances:
        return 0.0
    total_morphemes = sum(len(u.morphemes) for u in utterances)
    return total_morphemes / len(utterances)
