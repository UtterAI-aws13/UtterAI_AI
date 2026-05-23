import json
from app.schemas import Utterance, SpeakerMetrics, RagResult, ReportDraft
from app.rag.prompt_templates import build_report_prompt


def generate_report(
    job_id: str,
    session_id: str,
    utterances: list[Utterance],
    metrics: list[SpeakerMetrics],
    rag_result: RagResult,
    llm,
) -> ReportDraft:
    prompt = build_report_prompt(utterances, metrics, rag_result)
    raw = llm.predict(prompt)
    # TODO: JSON 파싱 실패 시 retry / schema repair
    data = json.loads(raw)
    raise NotImplementedError
