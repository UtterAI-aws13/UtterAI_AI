# 비유창성(Disfluency) 탐지 — 말더듬·간투사·반복 빈도 계산
#
# 탐지 유형:
#   filler      — 간투사 (어, 음, 아, 으, 저 등)
#   repetition  — 동일 토큰의 연속 반복 (나 나 나는 → 2회)
#   prolongation— 모음/자음 연장 (아아아 → 패턴 감지)
#
# 주의: 텍스트 기반 탐지이므로 prolongation은 ASR이 그대로 전사한 경우만 감지된다.
import re
from app.schemas import Utterance

KOREAN_FILLERS = {
    "어", "음", "아", "으", "이", "저", "뭐", "그",
    "있잖아", "있잖", "근데", "뭔가", "그러니까",
    "에", "어어", "음음", "아아", "잠깐", "그게", "막",
}

_PROLONGATION_RE = re.compile(r"(.)\1{2,}")


def _is_prolongation(token: str) -> bool:
    """같은 문자가 3회 이상 연속되면 연장으로 간주한다."""
    return bool(_PROLONGATION_RE.search(token))


def _count_repetitions(tokens: list[str]) -> int:
    """연속된 동일 토큰 반복 횟수를 반환한다 (토큰 단위)."""
    count = 0
    for i in range(1, len(tokens)):
        if tokens[i] == tokens[i - 1]:
            count += 1
    return count


class DisfluencyResult:
    __slots__ = ("filler_count", "repetition_count", "prolongation_count", "total_tokens")

    def __init__(
        self,
        filler_count: int,
        repetition_count: int,
        prolongation_count: int,
        total_tokens: int,
    ) -> None:
        self.filler_count = filler_count
        self.repetition_count = repetition_count
        self.prolongation_count = prolongation_count
        self.total_tokens = total_tokens

    @property
    def total_disfluency(self) -> int:
        return self.filler_count + self.repetition_count + self.prolongation_count

    @property
    def disfluency_rate(self) -> float:
        """전체 토큰 대비 비유창성 비율. 토큰이 없으면 0.0."""
        if self.total_tokens == 0:
            return 0.0
        return round(self.total_disfluency / self.total_tokens, 4)


def calculate_disfluency(utterances: list[Utterance]) -> DisfluencyResult:
    """발화 목록에서 비유창성 지표를 계산한다.

    filler_count      — KOREAN_FILLERS에 포함된 토큰 수
    repetition_count  — 연속 동일 토큰 반복 수
    prolongation_count— 문자 연장 패턴 수 (AAA 형태)
    total_tokens      — 전체 토큰 수 (비율 계산 기준)
    """
    filler_count = 0
    repetition_count = 0
    prolongation_count = 0
    total_tokens = 0

    for u in utterances:
        tokens = u.tokens
        total_tokens += len(tokens)
        for tok in tokens:
            if tok in KOREAN_FILLERS:
                filler_count += 1
            if _is_prolongation(tok):
                prolongation_count += 1
        repetition_count += _count_repetitions(tokens)

    return DisfluencyResult(filler_count, repetition_count, prolongation_count, total_tokens)