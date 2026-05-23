from app.schemas import JobMessage
from app.pipelines.analysis_pipeline import run_analysis


def handle_message(message: dict) -> None:
    job = JobMessage(**message)
    run_analysis(job)


def start_worker() -> None:
    # TODO: SQS 폴링 루프
    raise NotImplementedError
