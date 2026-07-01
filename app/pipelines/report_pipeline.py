# 리포트 생성 파이프라인
# 언어 지표 + RAG 검색 근거를 Bedrock Claude에 입력해 SOAP Note 초안 JSON을 생성한다
#
# JSON 파싱 및 재시도는 bedrock_client.invoke_claude()가 처리한다.
# 필수 필드 누락 시 빈 문자열로 채워 schema 오류를 방지한다 (schema repair).
import json
import uuid
from time import perf_counter
from typing import TYPE_CHECKING

from opentelemetry import trace

from app.schemas import (
    Utterance, SpeakerMetrics, RagResult, ReportDraft,
    SOAPNote, ClinicalFlag, ModelVersions,
)
from app.rag.prompt_templates import build_report_prompt
from app.config import settings
from app.observability.phoenix import safe_id, set_safe_attributes

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
    """transcript_segments를 RDS에서 읽어 AgentCore 에이전트로 리포트를 생성하고 저장한다.

    비템플릿 경로: AgentCore가 search_evidence tool을 통해 RAG 검색과 SOAP Note 생성을 통합 처리한다.
    템플릿 경로: 커스텀 섹션 출력 형식이 AgentCore 시스템 프롬프트와 다르므로 기존 Bedrock 경로를 유지한다.
    """
    from loguru import logger
    from app.pipelines.agentcore_client import invoke_agent
    from app.rag.prompt_templates import build_session_prompt
    from app.storage.rds import get_transcript_segments, get_session_context, save_report, update_session_status
    from app.config import settings

    job_id = message.job_id
    session_id = message.session_id
    transcript_id = message.transcript_id
    report_saved = False
    tracer = trace.get_tracer(__name__)

    try:
        with tracer.start_as_current_span("phoenix.cpu_report.load_transcript") as span:
            set_safe_attributes(span, {
                "job.hash": safe_id(job_id),
                "session.hash": safe_id(session_id),
                "transcript.hash": safe_id(transcript_id),
                "transcript.source": "s3" if message.final_s3_key else "rds",
            })
            logger.info(f"[{job_id}] REPORT STAGE: LOADING TRANSCRIPT transcript_id={transcript_id} final_s3_key={message.final_s3_key!r}")
            if message.final_s3_key:
                from app.storage.s3_client import get_bytes
                raw = get_bytes(settings.s3_bucket_transcript, message.final_s3_key)
                segments = json.loads(raw)
                logger.info(f"[{job_id}] REPORT STAGE: TRANSCRIPT LOADED FROM S3 key={message.final_s3_key} segments={len(segments)}")
            else:
                segments = await get_transcript_segments(db, transcript_id)
                logger.info(f"[{job_id}] REPORT STAGE: TRANSCRIPT LOADED FROM RDS segments={len(segments)}")
            set_safe_attributes(span, {"transcript.segment_count": len(segments)})
            if not segments:
                logger.warning(f"[{job_id}] REPORT STAGE: transcript_segments 비어있음 — transcript_id={transcript_id}")

        with tracer.start_as_current_span("phoenix.cpu_report.compute_metrics") as span:
            logger.info(f"[{job_id}] REPORT STAGE: COMPUTING METRICS ({len(segments)} segments)")
            metrics = _compute_metrics_from_segments(segments)
            set_safe_attributes(span, {
                "metrics.mlu_word": metrics.get("mlu_word"),
                "metrics.ndw": metrics.get("ndw"),
                "metrics.ttr": metrics.get("ttr"),
                "metrics.avg_response_latency_sec": metrics.get("avg_response_latency_sec"),
            })
            logger.info(f"[{job_id}] REPORT STAGE: metrics={metrics}")

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

        template_id = message.template_id
        template_sections = None
        if template_id:
            from app.storage.rds import get_template_sections
            logger.info(f"[{job_id}] REPORT STAGE: 템플릿 섹션 조회 template_id={template_id}")
            template_sections = await get_template_sections(db, template_id)
            logger.info(f"[{job_id}] REPORT STAGE: 템플릿 섹션 {len(template_sections) if template_sections else 0}개")

        custom_sections_to_save = None
        soap_note = {}
        evidence_chunk_ids: list[str] = []

        if template_sections:
            # 커스텀 템플릿: 기존 Bedrock 직접 호출 경로 유지 (AgentCore 시스템 프롬프트와 출력 형식이 다름)
            from app.pipelines.bedrock_client import invoke_claude
            from app.rag.retriever import retrieve_evidence
            from app.rag.prompt_templates import build_template_report_prompt

            logger.info(f"[{job_id}] REPORT STAGE: [TEMPLATE] RAG 시작")
            rag_start = perf_counter()
            with tracer.start_as_current_span("phoenix.cpu_report.rag") as span:
                set_safe_attributes(span, {"report.path": "template", "rag.top_k": settings.rag_top_k})
                evidence = await retrieve_evidence(
                    metrics=metrics,
                    session=session,
                    embedding_model=embedding_model,
                )
                set_safe_attributes(span, {
                    "rag.evidence_count": len(evidence),
                    "rag.duration_ms": round((perf_counter() - rag_start) * 1000, 2),
                })
            logger.info(f"[{job_id}] REPORT STAGE: [TEMPLATE] RAG 완료 evidence={len(evidence)}")

            with tracer.start_as_current_span("phoenix.cpu_report.build_prompt") as span:
                prompt = build_template_report_prompt(
                    metrics=metrics,
                    utterances=patient_utterances or all_utterances,
                    session=session,
                    evidence=evidence,
                    sections=template_sections,
                )
                set_safe_attributes(span, {
                    "report.path": "template",
                    "prompt.length": len(prompt),
                    "utterance.patient_count": len(patient_utterances),
                    "utterance.total_count": len(all_utterances),
                })
            logger.debug(f"[{job_id}] REPORT STAGE: [TEMPLATE] prompt_len={len(prompt)}")
            llm_start = perf_counter()
            with tracer.start_as_current_span("phoenix.cpu_report.invoke_llm") as span:
                set_safe_attributes(span, {
                    "report.path": "template",
                    "llm.provider": "bedrock",
                    "llm.model": settings.bedrock_report_model_id,
                })
                report_data = invoke_claude(prompt)
                set_safe_attributes(span, {"llm.duration_ms": round((perf_counter() - llm_start) * 1000, 2)})
            logger.info(f"[{job_id}] REPORT STAGE: [TEMPLATE] BEDROCK 완료 keys={list(report_data.keys())}")

            evidence_chunk_ids = [e.get("chunk_id", "") for e in evidence if isinstance(e, dict)]
            raw_sections = report_data.get("sections", {})
            custom_sections_to_save = [
                {
                    "key": s.get("key", ""),
                    "title": s.get("title", s.get("key", "")),
                    "content": raw_sections.get(s.get("key", ""), ""),
                }
                for s in template_sections
            ]
        elif settings.agentcore_agent_id:
            # AgentCore 경로: search_evidence tool로 RAG 검색과 SOAP Note 생성을 통합 처리
            logger.info(f"[{job_id}] REPORT STAGE: AGENTCORE 호출 시작 session_id={session_id}")
            with tracer.start_as_current_span("phoenix.cpu_report.build_prompt") as span:
                prompt = build_session_prompt(
                    metrics=metrics,
                    utterances=patient_utterances or all_utterances,
                    session=session,
                )
                set_safe_attributes(span, {
                    "report.path": "agentcore",
                    "prompt.length": len(prompt),
                    "utterance.patient_count": len(patient_utterances),
                    "utterance.total_count": len(all_utterances),
                })
            logger.debug(f"[{job_id}] REPORT STAGE: prompt_len={len(prompt)}")
            llm_start = perf_counter()
            with tracer.start_as_current_span("phoenix.cpu_report.invoke_llm") as span:
                set_safe_attributes(span, {
                    "report.path": "agentcore",
                    "llm.provider": "bedrock-agentcore",
                    "llm.model": settings.bedrock_report_model_id,
                })
                report_data = invoke_agent(prompt=prompt, session_id=session_id)
                set_safe_attributes(span, {"llm.duration_ms": round((perf_counter() - llm_start) * 1000, 2)})
            logger.info(f"[{job_id}] REPORT STAGE: AGENTCORE 완료 keys={list(report_data.keys())}")
            soap_note = report_data.get("soap_note", {})
        else:
            # Fallback: AgentCore 미설정 시 기존 Bedrock 직접 호출 경로
            from app.pipelines.bedrock_client import invoke_claude
            from app.rag.retriever import retrieve_evidence
            from app.rag.prompt_templates import build_bedrock_report_prompt

            logger.info(f"[{job_id}] REPORT STAGE: [FALLBACK] RAG 시작 (agentcore_agent_id 미설정)")
            rag_start = perf_counter()
            with tracer.start_as_current_span("phoenix.cpu_report.rag") as span:
                set_safe_attributes(span, {"report.path": "fallback", "rag.top_k": settings.rag_top_k})
                evidence = await retrieve_evidence(
                    metrics=metrics,
                    session=session,
                    embedding_model=embedding_model,
                )
                set_safe_attributes(span, {
                    "rag.evidence_count": len(evidence),
                    "rag.duration_ms": round((perf_counter() - rag_start) * 1000, 2),
                })
            logger.info(f"[{job_id}] REPORT STAGE: [FALLBACK] RAG 완료 evidence={len(evidence)}")
            with tracer.start_as_current_span("phoenix.cpu_report.build_prompt") as span:
                prompt = build_bedrock_report_prompt(
                    metrics=metrics,
                    utterances=patient_utterances or all_utterances,
                    session=session,
                    evidence=evidence,
                )
                set_safe_attributes(span, {
                    "report.path": "fallback",
                    "prompt.length": len(prompt),
                    "utterance.patient_count": len(patient_utterances),
                    "utterance.total_count": len(all_utterances),
                })
            logger.debug(f"[{job_id}] REPORT STAGE: [FALLBACK] prompt_len={len(prompt)}")
            llm_start = perf_counter()
            with tracer.start_as_current_span("phoenix.cpu_report.invoke_llm") as span:
                set_safe_attributes(span, {
                    "report.path": "fallback",
                    "llm.provider": "bedrock",
                    "llm.model": settings.bedrock_report_model_id,
                })
                report_data = invoke_claude(prompt)
                set_safe_attributes(span, {"llm.duration_ms": round((perf_counter() - llm_start) * 1000, 2)})
            logger.info(f"[{job_id}] REPORT STAGE: [FALLBACK] BEDROCK 완료 keys={list(report_data.keys())}")
            evidence_chunk_ids = [e.get("chunk_id", "") for e in evidence if isinstance(e, dict)]
            soap_note = report_data.get("soap_note", {})

        clinical_flags = report_data.get("clinical_flags", [])

        logger.info(f"[{job_id}] REPORT STAGE: SAVING")
        with tracer.start_as_current_span("phoenix.cpu_report.persist_report") as span:
            set_safe_attributes(span, {
                "report.path": "template" if template_sections else "agentcore" if settings.agentcore_agent_id else "fallback",
                "report.clinical_flag_count": len(clinical_flags),
                "rag.evidence_count": len(evidence_chunk_ids),
                "template.enabled": bool(template_sections),
            })
            await save_report(
                db=db,
                job_id=job_id,
                session_id=session_id,
                soap_note=soap_note,
                clinical_flags=clinical_flags,
                evidence_chunk_ids=evidence_chunk_ids,
                model_used=settings.bedrock_report_model_id,
                template_id=template_id,
                custom_sections=custom_sections_to_save,
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
