# CIU (Correct Information Units) — 맥락적 정보 단위
#
# Nicholas & Brookshire(1993)의 성인 담화 분석 지표를 한국어에 적용.
# 정의: 발화 내에서 맥락에 적합하고 정보를 전달하는 단어(형태소)의 비율.
#
# 한국어 적용 기준:
#   - 내용 형태소(명사·동사·형용사·부사) TAG만 집계
#   - 간투사(disfluency.KOREAN_FILLERS)에 해당하는 토큰이 포함된 형태소는 제외
#   - ASR confidence < 0.4인 발화 전체는 '불명료' 처리해 CIU에서 제외
#
# 반환값:
#   ciu_count     — 내용 형태소 수
#   total_morphemes — 전체 형태소 수
#   ciu_rate      — ciu_count / total_morphemes (0~1)
from dataclasses import dataclass

from app.metrics.disfluency import KOREAN_FILLERS
from app.schemas import Utterance

# Kiwi 품사 태그 중 '내용어'로 취급할 태그
_CONTENT_TAGS = frozenset({
    "NNG",  # 일반명사
    "NNP",  # 고유명사
    "NNB",  # 의존명사
    "VV",   # 동사
    "VA",   # 형용사
    "VX",   # 보조동사
    "MAG",  # 일반부사
    "MM",   # 관형사
})

_LOW_CONFIDENCE_THRESHOLD = 0.4


@dataclass(frozen=True)
class CIUResult:
    ciu_count: int
    total_morphemes: int
    ciu_rate: float


def calculate_ciu(utterances: list[Utterance]) -> CIUResult:
    """발화 목록에서 CIU 지표를 계산한다.

    asr_confidence < 0.4인 발화는 전체를 불명료 처리해 제외한다.
    morphemes가 비어 있는 발화도 건너뛴다.
    """
    total_morphemes = 0
    ciu_count = 0

    for u in utterances:
        if u.asr_confidence < _LOW_CONFIDENCE_THRESHOLD:
            continue
        if not u.morphemes:
            continue
        # 발화 토큰에 간투사가 포함되면 해당 발화의 CIU 기여를 낮춘다
        has_filler = any(tok in KOREAN_FILLERS for tok in u.tokens)
        for m in u.morphemes:
            total_morphemes += 1
            if m.tag in _CONTENT_TAGS and not has_filler:
                ciu_count += 1

    ciu_rate = round(ciu_count / total_morphemes, 4) if total_morphemes else 0.0
    return CIUResult(ciu_count=ciu_count, total_morphemes=total_morphemes, ciu_rate=ciu_rate)