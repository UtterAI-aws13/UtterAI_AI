from __future__ import annotations

import re

# 진단 단정 표현 패턴
_DIAGNOSTIC_ASSERTION_PATTERNS = [
    r"(확진|확진됨|확진되었다|확진 결과)",
    r"(장애가 있(다|습니다|음))",
    r"(장애로\s*(판단|확인|진단))",
    r"(진단\s*결과\s*[^\(]*장애)",
    r"(\[진단\]|\[확진\])",
    # 장애/진단명 자체를 "의심"과 묶어 쓰면 진단 시사로 읽혀 금지 대상이다
    # (01_production_5_agent_agentic_rag_design.md §8.2 대표 예시: "자폐가 의심됩니다").
    # "발달 지연이 의심됩니다" 같은 일반 관찰 문구는 임상적으로 허용되는 완곡
    # 표현이라 여기서 걸러지지 않도록, 진단명/장애명이 명시된 경우만 잡는다.
    r"(자폐|ADHD|ADD|지적장애|조음장애|언어장애|발달장애|주의력결핍|과잉행동장애|증후군)\s*(이|가)?\s*(으로)?\s*의심",
]

# 근거 없는 단정 개선/악화 표현
_UNSUPPORTED_CLAIM_PATTERNS = [
    r"(확실히\s*(개선|향상|악화)됨)",
    r"(명확히\s*(회복|저하|개선))",
]


def check_clinical_safety(text: str) -> tuple[bool, str]:
    """Returns (is_safe, violation_description). is_safe=False means the text is unsafe."""
    for pattern in _DIAGNOSTIC_ASSERTION_PATTERNS:
        if re.search(pattern, text):
            return False, f"진단 단정 표현이 포함되어 있습니다 (패턴: {pattern})"
    for pattern in _UNSUPPORTED_CLAIM_PATTERNS:
        if re.search(pattern, text):
            return False, f"근거 없는 단정 표현이 포함되어 있습니다 (패턴: {pattern})"
    return True, ""
