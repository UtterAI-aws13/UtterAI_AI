# 리포트 생성 파이프라인
# 언어 지표 + RAG 검색 근거를 EXAONE에 입력해 SOAP Note 초안 JSON을 생성한다
#
# LLM 출력 JSON 처리 전략:
#   1차 시도: raw 텍스트를 직접 json.loads()
#   2차 시도: ```json ... ``` 마크다운 블록에서 추출
#   3차 시도: 텍스트에서 첫 번째 {...} 블록 추출
#   필수 필드 누락 시 빈 문자열로 채워 schema 오류 방지 (schema repair)
#   MAX_RETRIES 초과 시 RuntimeError 발생
import json
import re
import uuid

from app.schemas import (
    Utterance, SpeakerMetrics, RagResult, ReportDraft,
    SOAPNote, ClinicalFlag, ModelVersions,
)
from app.rag.prompt_templates import build_report_prompt
from app.config import settings

MAX_RETRIES = 3

_JSON_BLOCK_RE = re.compile(r'```(?:json)?\s*([\s\S]*?)\s*```')
_JSON_OBJECT_RE = re.compile(r'\{[\s\S]*\}')


def _extract_json(raw: str) -> dict:
    """LLM 출력에서 JSON 객체를 추출한다. 파싱 불가 시 ValueError를 발생시킨다."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK_RE.search(raw)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = _JSON_OBJECT_RE.search(raw)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"JSON 파싱 실패. LLM 출력 앞 200자: {raw[:200]}")


def _repair_schema(data: dict) -> dict:
    """필수 SOAP 필드가 없을 때 빈 문자열로 채운다."""
    soap = data.get("soap_note") or {}
    for field in ("subjective", "objective", "assessment", "plan"):
        if not soap.get(field):
            soap[field] = ""
    data["soap_note"] = soap

    if not isinstance(data.get("clinical_flags"), list):
        data["clinical_flags"] = []
    if not isinstance(data.get("recommended_review_points"), list):
        data["recommended_review_points"] = []

    return data


def generate_report(
    job_id: str,
    session_id: str,
    utterances: list[Utterance],
    metrics: list[SpeakerMetrics],
    rag_result: RagResult,
    llm,
    model_versions: ModelVersions | None = None,
) -> ReportDraft:
    """EXAONE에 프롬프트를 전달하고 반환된 JSON을 ReportDraft로 변환한다.

    JSON 파싱 실패 시 MAX_RETRIES 횟수만큼 재시도한다.
    모든 시도 실패 시 RuntimeError를 발생시킨다.
    """
    prompt = build_report_prompt(utterances, metrics, rag_result)

    if model_versions is None:
        model_versions = ModelVersions(
            vad=settings.vad_model_name,
            diarization=settings.diarization_model_name,
            asr=settings.asr_model_name,
            embedding=settings.embedding_model_name,
            llm=settings.llm_model_name,
        )

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        raw = llm.predict(prompt)
        try:
            data = _extract_json(raw)
            data = _repair_schema(data)

            soap_note = SOAPNote(**data["soap_note"])

            clinical_flags = [
                ClinicalFlag(**f) for f in data.get("clinical_flags", [])
                if isinstance(f, dict)
            ]

            evidence_ids = [e.chunk_id for e in rag_result.evidence]

            return ReportDraft(
                report_id=str(uuid.uuid4()),
                job_id=job_id,
                session_id=session_id,
                model_versions=model_versions,
                soap_note=soap_note,
                clinical_flags=clinical_flags,
                recommended_review_points=data.get("recommended_review_points", []),
                evidence_chunk_ids=evidence_ids,
            )

        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(
        f"리포트 생성 {MAX_RETRIES}회 시도 모두 실패. 마지막 오류: {last_error}"
    )


# ---------------------------------------------------------------------------
# Bedrock + Mock pipeline (local dev / MVP)
# ---------------------------------------------------------------------------

async def run_report_pipeline(job_id: str) -> dict:
    """Bedrock Claude 기반 리포트 생성 파이프라인 (Mock 데이터 사용).

    음성 파이프라인 완성 후 아래 세 줄을 RDS 조회로 교체한다:
        metrics    = await repositories.get_language_metrics(job_id)
        utterances = await repositories.get_child_utterances(job_id)
        session    = await repositories.get_session_by_job(job_id)
    """
    from datetime import datetime, timezone

    from app.mocks.mock_metrics import MOCK_METRICS
    from app.mocks.mock_session import MOCK_SESSION
    from app.mocks.mock_utterances import MOCK_PATIENT_UTTERANCES
    from app.rag.retriever import retrieve_evidence
    from app.rag.prompt_templates import build_bedrock_report_prompt
    from app.pipelines.bedrock_client import invoke_claude
    from app.config import settings

    metrics = {**MOCK_METRICS, "job_id": job_id}
    utterances = MOCK_PATIENT_UTTERANCES
    session = {**MOCK_SESSION, "job_id": job_id}

    evidence = await retrieve_evidence(metrics=metrics, session=session)
    print(f"[RAG] 검색된 근거: {len(evidence)}개")

    prompt = build_bedrock_report_prompt(
        metrics=metrics,
        utterances=utterances,
        session=session,
        evidence=evidence,
    )
    report_data = invoke_claude(prompt)

    report_data.update({
        "report_id": f"report_{job_id}",
        "job_id": job_id,
        "session_id": session["session_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_used": settings.bedrock_report_model_id,
        "requires_human_review": True,
    })

    return report_data
