# 3단계 분리 파이프라인
#
# run_cpu_stage    : VAD + 전처리 → S3 저장 → audio-ml-queue 발행
# run_ml_gpu_stage : pyannote + Whisper → S3 저장 → llm-queue 발행
# run_llm_gpu_stage: 정렬 + 지표 + RAG + EXAONE → 최종 S3/RDS 저장
#
# 각 스테이지는 독립적으로 실행되며 S3를 통해 중간 결과를 넘긴다.
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

import boto3
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
from app.models.llm_exaone import EXAONEWrapper
from app.rag.retriever import Retriever
from app.storage import s3_client
from app.config import settings


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
    llm: EXAONEWrapper
    retriever: Retriever


def _get_sqs():
    return boto3.client("sqs", region_name=settings.aws_region)


# ---------------------------------------------------------------------------
# Stage 1 — CPU Worker
# ---------------------------------------------------------------------------

async def run_cpu_stage(message: JobMessage, models: CPUModels) -> None:
    """전처리 + VAD 실행 후 S3에 저장하고 audio-ml-queue에 발행한다."""
    job_id = message.job_id
    session_id = message.session_id

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        suffix = Path(message.audio.key).suffix
        original_path = str(tmp / f"original{suffix}")
        wav_path = str(tmp / "processed.wav")

        logger.info(f"[{job_id}] CPU STAGE: DOWNLOADING")
        s3_client.download(message.audio.bucket, message.audio.key, original_path)

        logger.info(f"[{job_id}] CPU STAGE: PREPROCESSING")
        audio_meta = preprocess_audio(original_path, wav_path)
        logger.info(f"[{job_id}] duration={audio_meta.duration_sec:.1f}s")

        logger.info(f"[{job_id}] CPU STAGE: VAD")
        speech_segments = models.vad.predict(wav_path)
        logger.info(f"[{job_id}] speech_segments={len(speech_segments)}")

        # 전처리된 WAV + VAD 결과를 S3에 저장
        wav_key = f"intermediate/{session_id}/{job_id}/processed.wav"
        vad_key = f"intermediate/{session_id}/{job_id}/vad_segments.json"

        s3_client.upload(wav_path, settings.s3_bucket_audio, wav_key)

        vad_path = str(tmp / "vad_segments.json")
        Path(vad_path).write_text(
            json.dumps([s.model_dump() for s in speech_segments]), encoding="utf-8"
        )
        s3_client.upload(vad_path, settings.s3_bucket_audio, vad_key)

    # audio-ml-queue에 발행
    ml_msg = MLGpuMessage(
        job_id=job_id,
        session_id=session_id,
        wav_s3_key=wav_key,
        vad_s3_key=vad_key,
        options=message.options,
    )
    _get_sqs().send_message(
        QueueUrl=settings.sqs_gpu_inference_queue_url,
        MessageBody=ml_msg.model_dump_json(),
    )
    logger.info(f"[{job_id}] CPU STAGE: DONE → audio-ml-queue 발행")


# ---------------------------------------------------------------------------
# Stage 2 — ML GPU Worker
# ---------------------------------------------------------------------------

async def run_ml_gpu_stage(message: "MLGpuMessage", models: MLGpuModels) -> None:
    """pyannote 화자 분리 + Whisper STT 실행 후 S3에 저장하고 llm-queue에 발행한다."""
    job_id = message.job_id
    session_id = message.session_id

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        wav_path = str(tmp / "processed.wav")

        logger.info(f"[{job_id}] ML GPU STAGE: DOWNLOADING WAV")
        s3_client.download(settings.s3_bucket_audio, message.wav_s3_key, wav_path)

        if message.options.enable_diarization:
            logger.info(f"[{job_id}] ML GPU STAGE: DIARIZATION")
            speaker_segments = models.diarize.predict(wav_path)
            logger.info(f"[{job_id}] speaker_segments={len(speaker_segments)}")
        else:
            speaker_segments = []

        logger.info(f"[{job_id}] ML GPU STAGE: ASR")
        asr_result = models.asr.predict(wav_path)
        logger.info(f"[{job_id}] asr_segments={len(asr_result.segments)}")

        # 결과를 S3에 저장
        speaker_key = f"intermediate/{session_id}/{job_id}/speaker_segments.json"
        asr_key = f"intermediate/{session_id}/{job_id}/asr_result.json"

        speaker_path = str(tmp / "speaker_segments.json")
        Path(speaker_path).write_text(
            json.dumps([s.model_dump() for s in speaker_segments]), encoding="utf-8"
        )
        s3_client.upload(speaker_path, settings.s3_bucket_audio, speaker_key)

        asr_path = str(tmp / "asr_result.json")
        Path(asr_path).write_text(asr_result.model_dump_json(), encoding="utf-8")
        s3_client.upload(asr_path, settings.s3_bucket_audio, asr_key)

    # llm-queue에 발행
    llm_msg = LLMMessage(
        job_id=job_id,
        session_id=session_id,
        vad_s3_key=message.vad_s3_key,
        speaker_s3_key=speaker_key,
        asr_s3_key=asr_key,
        options=message.options,
    )
    _get_sqs().send_message(
        QueueUrl=settings.sqs_report_analysis_queue_url,
        MessageBody=llm_msg.model_dump_json(),
    )
    logger.info(f"[{job_id}] ML GPU STAGE: DONE → llm-queue 발행")


# ---------------------------------------------------------------------------
# Stage 3 — LLM GPU Worker
# ---------------------------------------------------------------------------

async def run_llm_gpu_stage(message: "LLMMessage", models: LLMModels) -> None:
    """정렬 + 지표 + RAG + EXAONE 실행 후 리포트를 S3에 저장한다."""
    job_id = message.job_id
    session_id = message.session_id

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)

        logger.info(f"[{job_id}] LLM STAGE: LOADING INTERMEDIATE RESULTS")
        vad_path = str(tmp / "vad_segments.json")
        speaker_path = str(tmp / "speaker_segments.json")
        asr_path = str(tmp / "asr_result.json")

        s3_client.download(settings.s3_bucket_audio, message.vad_s3_key, vad_path)
        s3_client.download(settings.s3_bucket_audio, message.speaker_s3_key, speaker_path)
        s3_client.download(settings.s3_bucket_audio, message.asr_s3_key, asr_path)

        speech_segments = [
            SpeechSegment(**s) for s in json.loads(Path(vad_path).read_text())
        ]
        speaker_segments = [
            SpeakerSegment(**s) for s in json.loads(Path(speaker_path).read_text())
        ]
        asr_result = ASRResult(**json.loads(Path(asr_path).read_text()))

        logger.info(f"[{job_id}] LLM STAGE: ALIGNING")
        utterances = align_segments(speech_segments, speaker_segments, asr_result.segments)

        logger.info(f"[{job_id}] LLM STAGE: METRICS")
        metrics = calculate_metrics(utterances, session_id)

        if message.options.enable_rag:
            logger.info(f"[{job_id}] LLM STAGE: RAG")
            rag_query = _build_rag_query(metrics)
            rag_result = await models.retriever.retrieve(RagQuery(question=rag_query))
            logger.info(f"[{job_id}] evidence={len(rag_result.evidence)}")
        else:
            from app.schemas import RagResult
            rag_result = RagResult(query="", expanded_query=[], evidence=[])

        logger.info(f"[{job_id}] LLM STAGE: GENERATING REPORT")
        report = generate_report(job_id, session_id, utterances, metrics, rag_result, models.llm)

        report_path = str(tmp / "report.json")
        Path(report_path).write_text(report.model_dump_json(indent=2), encoding="utf-8")
        report_key = f"reports/{session_id}/{job_id}.json"
        s3_client.upload(report_path, settings.s3_bucket_report, report_key)

    logger.info(f"[{job_id}] LLM STAGE: COMPLETED report_key={report_key}")


def _build_rag_query(metrics) -> str:
    if not metrics:
        return "언어 발달 지연 아동의 표현언어 중재 방법은?"
    child = next((m for m in metrics if m.speaker_role == "CHILD"), metrics[0])
    m = child.metrics
    return (
        f"MLU {m.mlu_morpheme:.1f}, TTR {m.ttr:.3f}, NDW {m.ndw} 수준 아동의 "
        "언어 발달 평가와 적합한 중재 방법은?"
    )
