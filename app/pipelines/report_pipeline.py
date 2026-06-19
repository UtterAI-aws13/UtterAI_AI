# 리포트 생성 파이프라인
# 언어 지표 + RAG 검색 근거를 Bedrock Claude에 입력해 SOAP Note 초안 JSON을 생성한다
#
# JSON 파싱 및 재시도는 bedrock_client.invoke_claude()가 처리한다.
# 필수 필드 누락 시 빈 문자열로 채워 schema 오류를 방지한다 (schema repair).
import uuid
from typing import TYPE_CHECKING

from app.schemas import (
    Utterance, SpeakerMetrics, RagResult, ReportDraft,
    SOAPNote, ClinicalFlag, ModelVersions,
)
from app.rag.prompt_templates import build_report_prompt
from app.config import settings

if TYPE_CHECKING:
    from app.schemas.job import ReportJobMessage


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
    model_versions: ModelVersions | None = None,
) -> ReportDraft:
    """Bedrock Claude에 프롬프트를 전달하고 반환된 JSON을 ReportDraft로 변환한다.

    재시도 및 JSON 파싱은 bedrock_client.invoke_claude()가 처리한다.
    """
    from app.pipelines.bedrock_client import invoke_claude

    prompt = build_report_prompt(utterances, metrics, rag_result)
    data = invoke_claude(prompt)
    data = _repair_schema(data)

    if model_versions is None:
        model_versions = ModelVersions(
            vad=settings.vad_model_name,
            diarization=settings.diarization_model_name,
            asr=settings.asr_model_name,
            embedding=settings.embedding_model_name,
            llm=settings.bedrock_report_model_id,
        )

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


# ---------------------------------------------------------------------------
# Bedrock pipeline — real RDS data
# ---------------------------------------------------------------------------

def _compute_metrics_from_segments(segments: list[dict]) -> dict:
    """transcript_segments 목록에서 언어 지표를 계산한다.

    MLU는 형태소 분석기(Kiwi)가 없으므로 단어(공백) 기준으로 계산한다.
    NTW/NDW/TTR은 PATIENT 발화의 공백 분리 토큰 기준.
    반응 지연은 SLP 발화 종료 → PATIENT 발화 시작 간격(0~10초 범위).
    """
    patient_segs = [s for s in segments if s.get("speaker_role") == "PATIENT" and s.get("text")]

    all_words = [w for s in patient_segs for w in s["text"].split() if w]
    ntw = len(all_words)
    ndw = len(set(all_words))
    ttr = round(ndw / ntw, 3) if ntw else 0.0
    mlu_word = (
        round(sum(len(s["text"].split()) for s in patient_segs) / len(patient_segs), 2)
        if patient_segs else 0.0
    )

    latencies: list[float] = []
    for i in range(1, len(segments)):
        prev, curr = segments[i - 1], segments[i]
        if (
            prev.get("speaker_role") == "SLP"
            and curr.get("speaker_role") == "PATIENT"
            and prev.get("end_ms") is not None
            and curr.get("start_ms") is not None
        ):
            gap = (curr["start_ms"] - prev["end_ms"]) / 1000.0
            if 0 <= gap <= 10:
                latencies.append(gap)

    return {
        "total_utterances": len(patient_segs),
        "ntw": ntw,
        "ndw": ndw,
        "ttr": ttr,
        "mlu_word": mlu_word,
        "avg_response_latency_sec": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        "max_response_latency_sec": round(max(latencies), 2) if latencies else 0.0,
    }


async def run_bedrock_report_stage(
    message: "ReportJobMessage",
    retriever,
    db,
    embedding_model=None,
) -> None:
    """transcript_segments를 RDS에서 읽어 RAG + Bedrock Claude로 리포트를 생성하고 저장한다."""
    from loguru import logger
    from app.pipelines.bedrock_client import invoke_claude
    from app.rag.prompt_templates import build_bedrock_report_prompt
    from app.rag.retriever import retrieve_evidence
    from app.storage.rds import get_transcript_segments, get_session_context, save_report, update_session_status
    from app.config import settings

    job_id = message.job_id
    session_id = message.session_id
    transcript_id = message.transcript_id

    try:
        logger.info(f"[{job_id}] REPORT STAGE: LOADING TRANSCRIPT transcript_id={transcript_id}")
        segments = await get_transcript_segments(db, transcript_id)
        logger.info(f"[{job_id}] REPORT STAGE: TRANSCRIPT LOADED segments={len(segments)}")
        if not segments:
            logger.warning(f"[{job_id}] REPORT STAGE: transcript_segments 비어있음 — transcript_id={transcript_id}")

        logger.info(f"[{job_id}] REPORT STAGE: COMPUTING METRICS ({len(segments)} segments)")
        metrics = _compute_metrics_from_segments(segments)
        logger.debug(f"[{job_id}] REPORT STAGE: metrics={metrics}")

        logger.info(f"[{job_id}] REPORT STAGE: LOADING SESSION CONTEXT")
        session_ctx = await get_session_context(db, session_id)
        logger.debug(f"[{job_id}] REPORT STAGE: session_ctx={session_ctx}")
        session = {
            "session_id": session_id,
            "job_id": job_id,
            **session_ctx,
        }

        patient_utterances = [
            {"speaker_role": s["speaker_role"], "text": s["text"]}
            for s in segments
            if s.get("speaker_role") == "PATIENT" and s.get("text")
        ]
        all_utterances = [
            {"speaker_role": s["speaker_role"], "text": s["text"]}
            for s in segments
            if s.get("text")
        ]
        logger.info(
            f"[{job_id}] REPORT STAGE: utterances patient={len(patient_utterances)} all={len(all_utterances)}"
        )

        logger.info(f"[{job_id}] REPORT STAGE: RAG 시작")
        evidence = await retrieve_evidence(
            metrics=metrics,
            session=session,
            embedding_model=embedding_model,
        )
        logger.info(f"[{job_id}] REPORT STAGE: RAG 완료 evidence={len(evidence)}")

        logger.info(f"[{job_id}] REPORT STAGE: BEDROCK 호출 시작 model={settings.bedrock_report_model_id}")
        prompt = build_bedrock_report_prompt(
            metrics=metrics,
            utterances=patient_utterances or all_utterances,
            session=session,
            evidence=evidence,
        )
        logger.debug(f"[{job_id}] REPORT STAGE: prompt_len={len(prompt)}")
        report_data = invoke_claude(prompt)
        logger.info(f"[{job_id}] REPORT STAGE: BEDROCK 호출 완료 keys={list(report_data.keys())}")

        soap_note = report_data.get("soap_note", {})
        clinical_flags = report_data.get("clinical_flags", [])
        evidence_chunk_ids = [e.get("chunk_id", "") for e in evidence if isinstance(e, dict)]

        logger.info(f"[{job_id}] REPORT STAGE: SAVING")
        report_saved = False
        await save_report(
            db=db,
            job_id=job_id,
            session_id=session_id,
            soap_note=soap_note,
            clinical_flags=clinical_flags,
            evidence_chunk_ids=evidence_chunk_ids,
            model_used=settings.bedrock_report_model_id,
        )
        report_saved = True
        await update_session_status(db, session_id, "REPORT_READY")
        logger.info(f"[{job_id}] REPORT STAGE: DONE")

    except Exception as exc:
        logger.exception(f"[{job_id}] REPORT STAGE 실패: {exc}")
        # save_report가 이미 커밋된 경우 세션을 FAILED로 바꾸면 리포트와 상태가 불일치한다.
        # 이 경우 세션을 REPORT_READY로 재시도하고, 그것도 실패하면 stuck 위험을 로그로 남긴다.
        if report_saved:
            try:
                await update_session_status(db, session_id, "REPORT_READY")
                logger.info(f"[{job_id}] 재시도로 REPORT_READY 상태 업데이트 완료")
            except Exception as retry_exc:
                logger.error(
                    f"[{job_id}] REPORT_READY 상태 업데이트 재시도 실패 — "
                    f"세션 REPORT_GENERATING stuck 위험: {retry_exc}"
                )
        else:
            try:
                await update_session_status(db, session_id, "FAILED")
            except Exception as status_exc:
                # 상태 업데이트 실패 시 세션이 REPORT_GENERATING에 영구 stuck되는 것을 방지하기 위해
                # 별도 로그를 남긴다. raise는 여전히 실행돼 SQS 메시지가 재처리될 수 있게 한다.
                logger.error(f"[{job_id}] FAILED 상태 업데이트 실패 (세션 stuck 위험): {status_exc}")
        raise


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
