from app.schemas import Utterance, SpeakerMetrics, RagResult

REPORT_SYSTEM_PROMPT = """당신은 언어치료 세션 분석을 보조하는 AI입니다.
아래 규칙을 반드시 따르세요:
- 검색된 근거 문서에 없는 내용은 단정하지 마세요.
- 아동을 진단하지 마세요.
- 출력은 반드시 JSON 형식을 따르세요.
- 치료사가 검토할 초안임을 명시하세요."""

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
    metrics_text = "\n".join(
        f"- {m.speaker_role} ({m.speaker_id}): MLU={m.metrics.mlu_morpheme}, "
        f"NTW={m.metrics.ntw}, NDW={m.metrics.ndw}, TTR={m.metrics.ttr}"
        for m in metrics
    )

    evidence_text = "\n".join(
        f"[{e.chunk_id}] {e.title}: {e.text[:200]}"
        for e in rag_result.evidence
    )

    sample_utterances = utterances[:10]
    utterance_text = "\n".join(
        f"{u.speaker_role}: {u.text}" for u in sample_utterances
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
