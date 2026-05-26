"""
로컬 개발용 파이프라인 직접 실행 스크립트.
SQS/S3 없이 로컬 오디오 파일로 전체 워크플로우를 테스트한다.

전제 조건:
  1. docker compose up -d          (PostgreSQL + pgvector)
  2. python scripts/create_tables.py  (최초 1회)
  3. .env 파일에 HF_TOKEN, DATABASE_URL 설정

사용법:
  python scripts/dev_run.py --audio path/to/audio.wav
  python scripts/dev_run.py --audio path/to/audio.wav --question "MLU 기준값은?"
"""
import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.schemas import RagQuery, RagResult


def _header(name: str) -> None:
    print(f"\n── {name} {'─' * (45 - len(name))}")


def _ok(label: str, val: str = "") -> None:
    suffix = f" : {val}" if val else ""
    print(f"  [OK]   {label}{suffix}")


def _stub(label: str) -> None:
    print(f"  [STUB] {label} — 빈 결과 반환 (미구현)")


def _err(label: str, exc: Exception) -> None:
    print(f"  [ERR]  {label} : {exc}")


async def main(audio_path: str, question: str) -> None:
    job_id = f"dev_{uuid.uuid4().hex[:8]}"
    session_id = f"dev_{uuid.uuid4().hex[:8]}"
    tmp_dir = Path("./tmp")
    tmp_dir.mkdir(exist_ok=True)
    tmp_wav = str(tmp_dir / f"{session_id}.wav")

    print(f"job_id    : {job_id}")
    print(f"session_id: {session_id}")
    print(f"audio     : {audio_path}")
    print(f"question  : {question}")

    # ──────────────────────────────────────────
    # 1. audio preprocess
    # ──────────────────────────────────────────
    _header("1. audio_preprocess")
    wav_path = audio_path  # fallback: 원본 파일 그대로 사용
    try:
        from app.pipelines.audio_preprocess import preprocess_audio
        audio_meta = preprocess_audio(audio_path, tmp_wav)
        _ok("preprocess_audio", f"duration={audio_meta.duration_sec:.1f}s")
        wav_path = tmp_wav
    except NotImplementedError:
        _stub("preprocess_audio")
        print(f"         원본 파일 그대로 사용: {audio_path}")

    # ──────────────────────────────────────────
    # 2. VAD
    # ──────────────────────────────────────────
    _header("2. Silero VAD")
    from app.models.vad_silero import SileroVADWrapper
    vad = SileroVADWrapper(settings.vad_model_name)
    vad.load()
    speech_segments = vad.predict(wav_path)
    if speech_segments:
        _ok("SileroVAD", f"{len(speech_segments)}개 구간")
    else:
        _stub("SileroVAD.predict")

    # ──────────────────────────────────────────
    # 3. Diarization
    # ──────────────────────────────────────────
    _header("3. pyannote diarization")
    from app.models.diarization_pyannote import PyannoteWrapper
    diarize = PyannoteWrapper(settings.diarization_model_name, hf_token=settings.hf_token)
    diarize.load()
    speaker_segments = diarize.predict(wav_path)
    if speaker_segments:
        _ok("PyannoteWrapper", f"{len(speaker_segments)}개 화자 구간")
    else:
        _stub("PyannoteWrapper.predict")

    # ──────────────────────────────────────────
    # 4. ASR (Whisper)
    # ──────────────────────────────────────────
    _header("4. Whisper ASR")
    from app.models.asr_whisper import WhisperASRWrapper
    asr_model = WhisperASRWrapper(settings.asr_model_name, device=settings.asr_device)
    asr_model.load()
    asr_result = asr_model.predict(wav_path)
    if asr_result.segments:
        _ok("WhisperASR", f"'{asr_result.text[:60]}'")
    else:
        _stub("WhisperASR.predict")

    # ──────────────────────────────────────────
    # 5. Alignment
    # ──────────────────────────────────────────
    _header("5. alignment")
    from app.pipelines.alignment import align_segments
    utterances = align_segments(speech_segments, speaker_segments, asr_result.segments)
    _ok("align_segments", f"{len(utterances)}개 발화")
    if not utterances:
        print("         (ASR segments가 비어 있어 Utterance 없음 — ASR 구현 후 정상 결과 확인 가능)")

    # ──────────────────────────────────────────
    # 6. Metrics
    # ──────────────────────────────────────────
    _header("6. metrics_pipeline")
    from app.pipelines.metrics_pipeline import calculate_metrics
    metrics = calculate_metrics(utterances, session_id)
    _ok("calculate_metrics", f"{len(metrics)}명 화자")
    for m in metrics:
        print(
            f"         {m.speaker_id} | "
            f"MLU={m.metrics.mlu_morpheme}  NTW={m.metrics.ntw}  "
            f"NDW={m.metrics.ndw}  TTR={m.metrics.ttr}"
        )

    # ──────────────────────────────────────────
    # 7. RAG retrieval  (DB 세션 필요)
    # ──────────────────────────────────────────
    _header("7. RAG retrieval")
    rag_result: RagResult

    try:
        from app.storage.db import engine
        from app.models.embedding_kure import KUREEmbeddingWrapper
        from app.rag.vector_store import VectorStore
        from app.rag.retriever import Retriever

        embedding_model = KUREEmbeddingWrapper(settings.embedding_model_name)
        embedding_model.load()
        _ok("KURE embedding 로드 완료")

        async with AsyncSession(engine) as session:
            vector_store = VectorStore(session)
            retriever = Retriever(
                vector_store, embedding_model,
                settings.rag_top_k, settings.rag_score_threshold,
            )
            rag_result = await retriever.retrieve(RagQuery(question=question))

        _ok("RAG retrieve", f"evidence={len(rag_result.evidence)}개")
        for ev in rag_result.evidence:
            print(f"         [{ev.chunk_id}] score={ev.score:.3f} | {ev.text[:60]}...")
        if not rag_result.evidence:
            print("         (벡터 DB가 비어 있음 — POST /ai/rag/ingest 로 문서를 먼저 등록하세요)")

    except Exception as e:
        _err("RAG retrieval", e)
        rag_result = RagResult(query=question, expanded_query=[], evidence=[])

    # ──────────────────────────────────────────
    # 8. Report (EXAONE LLM)
    # ──────────────────────────────────────────
    _header("8. report_pipeline (EXAONE)")
    try:
        from app.models.llm_exaone import EXAONEWrapper
        from app.pipelines.report_pipeline import generate_report

        llm = EXAONEWrapper(settings.llm_model_name, device=settings.llm_device)
        llm.load()
        _ok("EXAONE 로드 완료")

        report = generate_report(job_id, session_id, utterances, metrics, rag_result, llm)
        _ok("SOAP Note 생성 완료")
        s = report.soap_note
        print(f"\n  S (Subjective): {s.subjective}")
        print(f"  O (Objective) : {s.objective}")
        print(f"  A (Assessment): {s.assessment}")
        print(f"  P (Plan)      : {s.plan}")
        if report.clinical_flags:
            print(f"\n  clinical_flags: {[f.type for f in report.clinical_flags]}")
        if report.requires_human_review:
            print("  requires_human_review: True")

    except Exception as e:
        _err("report_pipeline", e)

    print("\n[DONE]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="UtterAI 로컬 파이프라인 직접 실행 (SQS/S3 없음)"
    )
    parser.add_argument("--audio", required=True, help="로컬 오디오 파일 경로 (.wav / .m4a / .mp3)")
    parser.add_argument(
        "--question",
        default="이 아동의 언어 발달 수준과 적합한 중재 방법은?",
        help="RAG 검색 질문 (기본값: 언어 중재 일반 질문)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.audio, args.question))
