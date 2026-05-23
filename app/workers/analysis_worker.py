# 분석 Worker
# SQS에서 분석 요청 메시지를 수신해 전체 AI 분석 파이프라인을 실행한다
# CPU Worker(VAD, Kiwi, RAG)와 GPU Worker(Whisper, pyannote, EXAONE)로 분리 배포 가능하다
from app.schemas import JobMessage
from app.pipelines.analysis_pipeline import run_analysis


def handle_message(message: dict) -> None:
    """SQS 메시지를 JobMessage로 파싱해 분석 파이프라인에 전달한다."""
    job = JobMessage(**message)
    run_analysis(job)


def start_worker() -> None:
    """SQS 큐를 폴링하며 메시지를 수신하고 handle_message를 호출하는 루프."""
    # TODO: SQS 폴링 루프 (long polling, visibility timeout 관리)
    raise NotImplementedError
