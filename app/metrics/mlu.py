# MLU (Mean Length of Utterance) 계산
# 한국어는 조사/어미가 의미를 가지므로 단어 기준이 아닌 형태소 기준 MLU를 사용한다
# morphemes 필드는 Kiwi 형태소 분석 후 Utterance에 채워진다
from app.schemas import Utterance


def calculate_mlu(utterances: list[Utterance]) -> float:
    """형태소 기준 MLU = 전체 형태소 수 / 전체 발화 수.

    예) 발화1 형태소 6개 + 발화2 형태소 5개, 발화 2개 → MLU = 5.5
    morphemes가 비어있으면 Kiwi 분석이 아직 실행되지 않은 것이다.
    """
    if not utterances:
        return 0.0
    total_morphemes = sum(len(u.morphemes) for u in utterances)
    return total_morphemes / len(utterances)
