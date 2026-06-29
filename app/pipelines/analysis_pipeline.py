# 3단계 분리 파이프라인
#
# run_cpu_stage    : VAD + 전처리 → S3 저장 → gpu-inference-queue 발행
# run_ml_gpu_stage : pyannote + Whisper → S3 저장 → report-analysis-queue 발행 (BE finalize 경유)
# run_llm_gpu_stage: 정렬 + 지표 + RAG + Bedrock Claude → 최종 S3/RDS 저장
#
# 각 스테이지는 독립적으로 실행되며 S3를 통해 중간 결과를 넘긴다.
import json
import tempfile
from time import perf_counter
from dataclasses import dataclass
from pathlib import Path

import boto3
from opentelemetry import trace
from loguru import logger

from app.schemas import (
    JobMessage, MLGpuMessage, LLMMessage, RagQuery,
    SpeechSegment, SpeakerSegment, ASRResult,
)
from app.pipelines.audio_preprocess import preprocess_audio
from app.pipelines.alignment import align_segments
from app.pipelines.metrics_pipeline import calculate_metrics
from app.pipelines.report_pipeline import generate_report
from app.models.vad_silero import SileroVADWrapper
from app.models.diarization_pyannote import PyannoteWrapper
from app.models.asr_whisper import WhisperASRWrapper
from app.models.embedding_kure import KUREEmbeddingWrapper
from app.rag.retriever import Retriever
from app.storage import s3_client
from app.storage.rds import (
    get_analysis_job_status,
    save_transcript_draft,
    update_analysis_job_status,
    update_session_status,
)
from app.config import settings
from app.observability.metrics import record_sqs_publish, record_stage_duration
from app.observability.sqs import build_message_attributes_from_current_context


@dataclass
class CPUModels:
    vad: SileroVADWrapper
    embedding: KUREEmbeddingWrapper


@dataclass
class MLGpuModels:
    diarize: PyannoteWrapper
    asr: WhisperASRWrapper


@dataclass
class LLMModels:
    embedding: KUREEmbeddingWrapper
    retriever: Retriever


def _get_sqs():
    return boto3.client("sqs", region_name=settings.aws_region)


def _send_sqs(queue_url: str, message_body: str, stage: str) -> None:
    _get_sqs().send_message(
        QueueUrl=queue_url,
        MessageBody=message_body,
        MessageAttributes=build_message_attributes_from_current_context(),
    )
    record_sqs_publish(stage)


# ---------------------------------------------------------------------------
# Stage 1 — CPU Worker
# ---------------------------------------------------------------------------

async def run_cpu_stage(message: JobMessage, models: CPUModels) -> None:
    """전처리 + VAD 실행 후 S3에 저장하고 gpu-inference-queue에 발행한다."""
    tracer = trace.get_tracer(__name__)
    job_id = message.job_id
    session_id = message.session_id
    with tracer.start_as_current_span("worker.cpu.pipeline") as span:
        span.set_attribute("job.id", job_id)
        start_total = perf_counter()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            suffix = Path(message.audio.key).suffix
            original_path = str(tmp / f"original{suffix}")
            wav_path = str(tmp / "processed.wav")

            logger.info(f"[{job_id}] CPU STAGE: DOWNLOADING")
            download_start = perf_counter()
            with tracer.start_as_current_span("worker.cpu.download"):
                s3_client.download(message.audio.bucket, message.audio.key, original_path)
            record_stage_duration("cpu-worker", "download", perf_counter() - download_start)

            logger.info(f"[{job_id}] CPU STAGE: PREPROCESSING")
            preprocess_start = perf_counter()
            with tracer.start_as_current_span("worker.cpu.preprocess"):
                audio_meta = preprocess_audio(original_path, wav_path)
            record_stage_duration("cpu-worker", "preprocess", perf_counter() - preprocess_start)
            logger.info(f"[{job_id}] duration={audio_meta.duration_sec:.1f}s")

            logger.info(f"[{job_id}] CPU STAGE: VAD")
            vad_start = perf_counter()
            with tracer.start_as_current_span("worker.cpu.vad"):
                speech_segments = models.vad.predict(wav_path)
            record_stage_duration("cpu-worker", "vad", perf_counter() - vad_start)
            logger.info(f"[{job_id}] speech_segments={len(speech_segments)}")

            wav_key = f"intermediate/{session_id}/{job_id}/processed.wav"
            vad_key = f"intermediate/{session_id}/{job_id}/vad_segments.json"

            upload_start = perf_counter()
            with tracer.start_as_current_span("worker.cpu.persist_intermediate"):
                s3_client.upload(wav_path, settings.s3_bucket_audio, wav_key)
                vad_path = str(tmp / "vad_segments.json")
                Path(vad_path).write_text(
                    json.dumps([s.model_dump() for s in speech_segments]), encoding="utf-8"
                )
                s3_client.upload(vad_path, settings.s3_bucket_audio, vad_key)
            record_stage_duration("cpu-worker", "persist", perf_counter() - upload_start)

        ml_msg = MLGpuMessage(
            job_id=job_id,
            session_id=session_id,
            audio_file_id=message.audio_file_id,
            wav_s3_key=wav_key,
            vad_s3_key=vad_key,
            options=message.options,
        )
        with tracer.start_as_current_span("worker.cpu.publish_ml_gpu") as child_span:
            child_span.set_attribute("queue.name", settings.sqs_gpu_inference_queue_url)
            _send_sqs(
                settings.sqs_gpu_inference_queue_url,
                ml_msg.model_dump_json(),
                "cpu-to-ml",
            )
        record_stage_duration("cpu-worker", "publish", perf_counter() - start_total)
        logger.info(f"[{job_id}] CPU STAGE: DONE → gpu-inference-queue 발행")


# ---------------------------------------------------------------------------
# Stage 2 — ML GPU Worker
# ---------------------------------------------------------------------------

async def run_ml_gpu_stage(message: "MLGpuMessage", models: MLGpuModels, db) -> None:
    """STT + 화자분리 + alignment 실행 후 transcript draft를 S3/RDS에 저장하고 job status를 업데이트한다."""
    tracer = trace.get_tracer(__name__)
    job_id = message.job_id
    session_id = message.session_id
    with tracer.start_as_current_span("worker.ml_gpu.pipeline") as span:
        span.set_attribute("job.id", job_id)

        current_status = await get_analysis_job_status(db, job_id)
        if current_status == "CANCELLED":
            logger.info(f"[{job_id}] ML GPU STAGE: job was cancelled, skipping")
            return

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp = Path(tmp_dir)
                wav_path = str(tmp / "processed.wav")

                logger.info(f"[{job_id}] ML GPU STAGE: DOWNLOADING WAV")
                download_start = perf_counter()
                with tracer.start_as_current_span("worker.ml_gpu.download"):
                    s3_client.download(settings.s3_bucket_audio, message.wav_s3_key, wav_path)
                record_stage_duration("ml-gpu-worker", "download", perf_counter() - download_start)

                # VAD 결과를 ASR 전에 로드한다.
                # ASR이 VAD 발화 구간을 청크 기준으로 사용하므로 순서가 중요하다.
                logger.info(f"[{job_id}] ML GPU STAGE: LOADING VAD")
                vad_path = str(tmp / "vad_segments.json")
                s3_client.download(settings.s3_bucket_audio, message.vad_s3_key, vad_path)
                speech_segments = [
                    SpeechSegment(**s) for s in json.loads(Path(vad_path).read_text())
                ]
                logger.info(f"[{job_id}] speech_segments={len(speech_segments)}")

                if message.options.enable_diarization:
                    logger.info(f"[{job_id}] ML GPU STAGE: DIARIZATION")
                    diarize_start = perf_counter()
                    with tracer.start_as_current_span("worker.ml_gpu.diarization"):
                        speaker_segments = models.diarize.predict(wav_path)
                    record_stage_duration("ml-gpu-worker", "diarization", perf_counter() - diarize_start)
                    logger.info(f"[{job_id}] speaker_segments={len(speaker_segments)}")
                else:
                    speaker_segments = []

                logger.info(f"[{job_id}] ML GPU STAGE: ASR")
                asr_start = perf_counter()
                with tracer.start_as_current_span("worker.ml_gpu.asr"):
                    asr_result = models.asr.predict_with_vad(wav_path, speech_segments)
                record_stage_duration("ml-gpu-worker", "asr", perf_counter() - asr_start)
                logger.info(f"[{job_id}] asr_segments={len(asr_result.segments)}")

                # step 12: raw artifact → S3
                speaker_key = f"intermediate/{session_id}/{job_id}/speaker_segments.json"
                asr_key = f"intermediate/{session_id}/{job_id}/asr_result.json"
                persist_start = perf_counter()
                with tracer.start_as_current_span("worker.ml_gpu.persist_intermediate"):
                    speaker_path = str(tmp / "speaker_segments.json")
                    Path(speaker_path).write_text(
                        json.dumps([s.model_dump() for s in speaker_segments]), encoding="utf-8"
                    )
                    s3_client.upload(speaker_path, settings.s3_bucket_audio, speaker_key)

                    asr_path = str(tmp / "asr_result.json")
                    Path(asr_path).write_text(asr_result.model_dump_json(), encoding="utf-8")
                    s3_client.upload(asr_path, settings.s3_bucket_audio, asr_key)
                record_stage_duration("ml-gpu-worker", "persist", perf_counter() - persist_start)

                # alignment
                logger.info(f"[{job_id}] ML GPU STAGE: ALIGNING")
                align_start = perf_counter()
                with tracer.start_as_current_span("worker.ml_gpu.align"):
                    utterances = align_segments(speech_segments, speaker_segments, asr_result.segments)
                record_stage_duration("ml-gpu-worker", "align", perf_counter() - align_start)
                logger.info(f"[{job_id}] utterances={len(utterances)}")

                # step 13: transcript draft → S3 + RDS
                # 처리 중 취소된 경우 DB 저장을 건너뛴다.
                # save 전에 다시 확인하지 않으면 CANCELLED 상태를 덮어써 세션이 오염된다.
                recheck_status = await get_analysis_job_status(db, job_id)
                if recheck_status == "CANCELLED":
                    logger.info(f"[{job_id}] ML GPU STAGE: job cancelled during processing, skipping save")
                    return

                logger.info(f"[{job_id}] ML GPU STAGE: SAVING TRANSCRIPT DRAFT")
                draft_key = f"transcript-drafts/{session_id}/{job_id}/transcript_draft.json"
                draft_path = str(tmp / "transcript_draft.json")
                Path(draft_path).write_text(
                    json.dumps([u.model_dump() for u in utterances], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                s3_client.upload(draft_path, settings.s3_bucket_transcript, draft_key)
                await save_transcript_draft(
                    db, job_id, session_id, message.audio_file_id, draft_key, utterances
                )
                logger.info(f"[{job_id}] transcript draft 저장 완료: {draft_key}")

            # step 14: sessions.status → ANALYSIS_COMPLETED, analysis_jobs.status → COMPLETED
            await update_session_status(db, session_id, "ANALYSIS_COMPLETED")
            await update_analysis_job_status(db, job_id, "COMPLETED", pipeline_stage="COMPLETED")
            logger.info(f"[{job_id}] ML GPU STAGE: DONE")

        except Exception as exc:
            logger.error(f"[{job_id}] ML GPU STAGE 실패: {exc}")
            await update_session_status(db, session_id, "FAILED")
            await update_analysis_job_status(
                db, job_id, "FAILED",
                pipeline_stage="ML_GPU",
                error_code="ML_GPU_STAGE_FAILED",
                error_message=str(exc),
            )
            raise


# ---------------------------------------------------------------------------
# Stage 3 — LLM GPU Worker
# ---------------------------------------------------------------------------

async def run_llm_gpu_stage(message: "LLMMessage", models: LLMModels) -> None:
    """지표 + RAG + Bedrock Claude 실행 후 리포트를 S3에 저장한다."""
    tracer = trace.get_tracer(__name__)
    job_id = message.job_id
    session_id = message.session_id
    with tracer.start_as_current_span("worker.llm.pipeline") as span:
        span.set_attribute("job.id", job_id)
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)

            logger.info(f"[{job_id}] LLM STAGE: LOADING INTERMEDIATE RESULTS")
            vad_path = str(tmp / "vad_segments.json")
            speaker_path = str(tmp / "speaker_segments.json")
            asr_path = str(tmp / "asr_result.json")

            load_start = perf_counter()
            with tracer.start_as_current_span("worker.llm.load_intermediate"):
                s3_client.download(settings.s3_bucket_audio, message.vad_s3_key, vad_path)
                s3_client.download(settings.s3_bucket_audio, message.speaker_s3_key, speaker_path)
                s3_client.download(settings.s3_bucket_audio, message.asr_s3_key, asr_path)
            record_stage_duration("llm-gpu-worker", "load", perf_counter() - load_start)

            speech_segments = [
                SpeechSegment(**s) for s in json.loads(Path(vad_path).read_text())
            ]
            speaker_segments = [
                SpeakerSegment(**s) for s in json.loads(Path(speaker_path).read_text())
            ]
            asr_result = ASRResult(**json.loads(Path(asr_path).read_text()))

            logger.info(f"[{job_id}] LLM STAGE: ALIGNING")
            align_start = perf_counter()
            with tracer.start_as_current_span("worker.llm.align"):
                utterances = align_segments(speech_segments, speaker_segments, asr_result.segments)
            record_stage_duration("llm-gpu-worker", "align", perf_counter() - align_start)

            logger.info(f"[{job_id}] LLM STAGE: METRICS")
            metrics_start = perf_counter()
            with tracer.start_as_current_span("worker.llm.metrics"):
                metrics = calculate_metrics(utterances, session_id)
            record_stage_duration("llm-gpu-worker", "metrics", perf_counter() - metrics_start)

            if message.options.enable_rag:
                logger.info(f"[{job_id}] LLM STAGE: RAG")
                rag_start = perf_counter()
                rag_query = _build_rag_query(metrics)
                with tracer.start_as_current_span("worker.llm.rag"):
                    rag_result = await models.retriever.retrieve(RagQuery(question=rag_query))
                record_stage_duration("llm-gpu-worker", "rag", perf_counter() - rag_start)
                logger.info(f"[{job_id}] evidence={len(rag_result.evidence)}")
            else:
                from app.schemas import RagResult
                rag_result = RagResult(query="", expanded_query=[], evidence=[])

            logger.info(f"[{job_id}] LLM STAGE: GENERATING REPORT")
            report_start = perf_counter()
            with tracer.start_as_current_span("worker.llm.report"):
                report = generate_report(job_id, session_id, utterances, metrics, rag_result)
            record_stage_duration("llm-gpu-worker", "report", perf_counter() - report_start)

            report_path = str(tmp / "report.json")
            Path(report_path).write_text(report.model_dump_json(indent=2), encoding="utf-8")
            report_key = f"reports/{session_id}/{job_id}.json"
            persist_start = perf_counter()
            with tracer.start_as_current_span("worker.llm.persist_report"):
                s3_client.upload(report_path, settings.s3_bucket_report, report_key)
            record_stage_duration("llm-gpu-worker", "persist", perf_counter() - persist_start)

        logger.info(f"[{job_id}] LLM STAGE: COMPLETED report_key={report_key}")


def _build_rag_query(metrics) -> str:
    if not metrics:
        return "언어 발달 지연 아동의 표현언어 중재 방법은?"
    child = next((m for m in metrics if m.speaker_role == "PATIENT"), metrics[0])
    m = child.metrics
    return (
        f"MLU {m.mlu_morpheme:.1f}, TTR {m.ttr:.3f}, NDW {m.ndw} 수준 아동의 "
        "언어 발달 평가와 적합한 중재 방법은?"
    )
