# PCC (Percent Consonants Correct) — 자음 정확도
#
# 조음장애 평가의 핵심 지표.
# 계산 방법: PCC = (정확하게 산출된 자음 수 / 목표 자음 수) × 100
#
# 한국어 구현:
#   - 한글 음절을 초성·중성·종성 자모로 분해한다.
#   - 초성 ㅇ(무음)은 자음으로 집계하지 않는다.
#   - target_text가 없는 발화는 건너뛴다 → utterance.target_text 필드가 필요하다.
#
# 임상 주의: ASR 전사본은 자동 정규화가 개입할 수 있어 발음 오류를 완전히 포착하지 못할
# 수 있다. target_text는 SLP가 직접 입력하거나 치료 계획에서 가져와야 한다.
from app.schemas import Utterance

# 초성 인덱스 → 자모 문자
_INITIALS = [
    "ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ",
    "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
]

# 종성 인덱스 → 자모 문자 (0 = 없음)
_FINALS = [
    "", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ",
    "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ",
    "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
]

_HANGUL_BASE = 0xAC00
_SILENT_INITIAL = "ㅇ"


def _extract_consonants(text: str) -> list[str]:
    """텍스트에서 자음 목록을 추출한다 (초성 ㅇ 제외)."""
    consonants: list[str] = []
    for ch in text:
        code = ord(ch) - _HANGUL_BASE
        if not (0 <= code <= 11171):
            continue
        jong_idx = code % 28
        jung_idx = (code // 28) % 21
        cho_idx = code // 28 // 21
        _ = jung_idx  # 중성은 자음이 아님
        cho = _INITIALS[cho_idx]
        if cho != _SILENT_INITIAL:
            consonants.append(cho)
        jong = _FINALS[jong_idx]
        if jong:
            consonants.append(jong)
    return consonants


def _compare_consonants(produced: list[str], target: list[str]) -> int:
    """위치별로 자음을 비교해 일치 수를 반환한다.

    길이가 다른 경우 짧은 쪽에 맞춰 비교한다.
    """
    return sum(p == t for p, t in zip(produced, target))


def calculate_pcc(utterances: list[Utterance]) -> float | None:
    """PCC = (정확 자음 수 / 목표 자음 수) × 100.

    utterance.target_text가 있는 발화만 계산에 포함한다.
    유효한 쌍이 하나도 없으면 None을 반환한다.
    """
    total_target = 0
    total_correct = 0

    for u in utterances:
        if not u.target_text:
            continue
        produced = _extract_consonants(u.text)
        target = _extract_consonants(u.target_text)
        if not target:
            continue
        total_target += len(target)
        total_correct += _compare_consonants(produced, target)

    if total_target == 0:
        return None
    return round(total_correct / total_target * 100, 2)