# EXAONE 프롬프트 빌더
# 언어 지표, 대표 발화, RAG 근거를 조합해 SOAP Note 생성 프롬프트를 만든다
# 프롬프트에는 출력 JSON schema와 안전 지침(진단 확정 금지)이 반드시 포함되어야 한다
from app.schemas import Utterance, SpeakerMetrics, RagResult

REPORT_SYSTEM_PROMPT = """당신은 언어치료 세션 분석을 보조하는 AI입니다.
아래 규칙을 반드시 따르세요:
- 검색된 근거 문서에 없는 내용은 단정하지 마세요.
- 아동을 진단하지 마세요.
- 출력은 반드시 JSON 형식을 따르세요.
- 치료사가 검토할 초안임을 명시하세요."""

# EXAONE이 반드시 따라야 하는 출력 JSON 구조
REPORT_OUTPUT_SCHEMA = """{
  "soap_note": {
    "subjective": "string",
    "objective": "string",
    "assessment": "string",
    "plan": "string"
  },
  "clinical_flags": [
    {"type": "string", "description": "string", "evidence_chunk_ids": ["string"]}
  ],
  "recommended_review_points": ["string"],
  "disclaimer": "치료사 검토가 필요한 AI 생성 초안입니다."
}"""


def build_report_prompt(
    utterances: list[Utterance],
    metrics: list[SpeakerMetrics],
    rag_result: RagResult,
) -> str:
    """EXAONE 입력 프롬프트를 생성한다.

    LLM에는 원본 음성이나 전체 전사문 대신 다음 정보만 전달한다:
    - 화자별 언어 지표 수치
    - 대표 발화 최대 10개 (전체 전사문 노출 방지)
    - RAG 검색 근거 chunk (앞 200자만 사용해 컨텍스트 길이 제어)
    """
    metrics_text = "\n".join(
        f"- {m.speaker_role} ({m.speaker_id}): MLU={m.metrics.mlu_morpheme}, "
        f"NTW={m.metrics.ntw}, NDW={m.metrics.ndw}, TTR={m.metrics.ttr}"
        for m in metrics
    )

    evidence_text = "\n".join(
        f"[{e.chunk_id}] {e.title}: {e.text[:200]}"
        for e in rag_result.evidence
    )

    # 전체 발화 대신 앞 10개만 전달해 프롬프트 길이를 제한한다
    utterance_text = "\n".join(
        f"{u.speaker_role}: {u.text}" for u in utterances[:10]
    )

    return f"""{REPORT_SYSTEM_PROMPT}

## 언어 지표
{metrics_text}

## 대표 발화 (최대 10개)
{utterance_text}

## 검색 근거
{evidence_text}

## 출력 형식
{REPORT_OUTPUT_SCHEMA}
"""
