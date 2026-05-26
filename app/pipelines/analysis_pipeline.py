# 전체 분석 파이프라인 오케스트레이터
# Worker가 SQS 메시지를 수신하면 이 함수를 호출해 전체 파이프라인을 순서대로 실행한다
# 각 단계 진입 시 Job 상태를 로그로 기록하고, 실패 시 예외를 전파한다
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from app.schemas import JobMessage, RagQuery
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
class PipelineModels:
    vad: SileroVADWrapper
    diarize: PyannoteWrapper
    asr: WhisperASRWrapper
    retriever: Retriever
    llm: EXAONEWrapper


async def run_analysis(message: JobMessage, models: PipelineModels) -> None:
    """JobMessage를 받아 전체 AI 분석 파이프라인을 실행한다.

    실행 순서:
    1. S3에서 음성 다운로드
    2. ffmpeg 전처리 (16kHz mono WAV)
    3. Silero VAD (말소리 구간 추출)
    4. pyannote 화자 분리
    5. Whisper STT
    6. VAD + 화자 + STT 정렬 → Utterance 생성
    7. 언어 지표 계산 (MLU, NDW, NTW, TTR, latency)
    8. RAG 문서 검색
    9. EXAONE 리포트 초안 생성
    10. 리포트 JSON → S3 저장
    """
    job_id = message.job_id
    session_id = message.session_id

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        original_path = str(tmp / f"original{Path(message.audio.key).suffix}")
        wav_path = str(tmp / "processed.wav")

        # 1. S3 다운로드
        logger.info(f"[{job_id}] DOWNLOADING s3://{message.audio.bucket}/{message.audio.key}")
        s3_client.download(message.audio.bucket, message.audio.key, original_path)

        # 2. 전처리
        logger.info(f"[{job_id}] PREPROCESSING")
        audio_meta = preprocess_audio(original_path, wav_path)
        logger.info(f"[{job_id}] duration={audio_meta.duration_sec:.1f}s")

        # 3. VAD
        logger.info(f"[{job_id}] RUNNING_VAD")
        speech_segments = models.vad.predict(wav_path)
        logger.info(f"[{job_id}] speech_segments={len(speech_segments)}")

        # 4. 화자 분리
        if message.options.enable_diarization:
            logger.info(f"[{job_id}] RUNNING_DIARIZATION")
            speaker_segments = models.diarize.predict(wav_path)
            logger.info(f"[{job_id}] speaker_segments={len(speaker_segments)}")
        else:
            speaker_segments = []

        # 5. STT
        logger.info(f"[{job_id}] RUNNING_ASR")
        asr_result = models.asr.predict(wav_path)
        logger.info(f"[{job_id}] asr_segments={len(asr_result.segments)}")

        # 6. 정렬
        logger.info(f"[{job_id}] ALIGNING")
        utterances = align_segments(speech_segments, speaker_segments, asr_result.segments)
        logger.info(f"[{job_id}] utterances={len(utterances)}")

        # 7. 언어 지표
        logger.info(f"[{job_id}] CALCULATING_METRICS")
        metrics = calculate_metrics(utterances, session_id)

        # 8. RAG 검색
        if message.options.enable_rag:
            logger.info(f"[{job_id}] RUNNING_RAG")
            rag_query = _build_rag_query(metrics)
            rag_result = await models.retriever.retrieve(RagQuery(question=rag_query))
            logger.info(f"[{job_id}] evidence={len(rag_result.evidence)}")
        else:
            from app.schemas import RagResult
            rag_result = RagResult(query="", expanded_query=[], evidence=[])

        # 9. 리포트 생성
        logger.info(f"[{job_id}] GENERATING_REPORT")
        report = generate_report(job_id, session_id, utterances, metrics, rag_result, models.llm)

        # 10. S3 저장
        logger.info(f"[{job_id}] SAVING_RESULT")
        report_path = str(tmp / "report.json")
        Path(report_path).write_text(report.model_dump_json(indent=2), encoding="utf-8")
        report_key = f"reports/{session_id}/{job_id}.json"
        s3_client.upload(report_path, settings.s3_bucket_report, report_key)

    logger.info(f"[{job_id}] COMPLETED report_key={report_key}")


def _build_rag_query(metrics) -> str:
    """언어 지표를 바탕으로 RAG 검색 질문을 구성한다."""
    if not metrics:
        return "언어 발달 지연 아동의 표현언어 중재 방법은?"

    child = next((m for m in metrics if m.speaker_role == "CHILD"), metrics[0])
    m = child.metrics
    return (
        f"MLU {m.mlu_morpheme:.1f}, TTR {m.ttr:.3f}, NDW {m.ndw} 수준 아동의 "
        "언어 발달 평가와 적합한 중재 방법은?"
    )
