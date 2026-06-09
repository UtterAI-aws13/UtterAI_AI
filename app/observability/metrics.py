"""Business metrics for the AI service."""

from __future__ import annotations

from functools import lru_cache

from app.observability.otel import get_meter


@lru_cache(maxsize=1)
def _meter():
    return get_meter("utterai.ai.metrics")


@lru_cache(maxsize=1)
def _counter(name: str, description: str):
    return _meter().create_counter(name, description=description)


@lru_cache(maxsize=1)
def _histogram(name: str, description: str):
    return _meter().create_histogram(name, description=description, unit="s")


def record_job_created() -> None:
    _counter("utterai_ai_jobs_created_total", "Total job create requests accepted by AI API").add(1)


def record_sqs_publish(stage: str) -> None:
    _counter(
        "utterai_ai_sqs_publish_total",
        "Total SQS messages published by AI workers and API",
    ).add(1, {"stage": stage})


def record_sqs_receive(worker: str) -> None:
    _counter(
        "utterai_ai_sqs_receive_total",
        "Total SQS messages consumed by AI workers",
    ).add(1, {"worker": worker})


def record_stage_duration(worker: str, stage: str, seconds: float) -> None:
    _histogram(
        "utterai_ai_stage_duration_seconds",
        "Duration of AI pipeline stages",
    ).record(seconds, {"worker": worker, "stage": stage})


def record_stage_failure(worker: str, stage: str) -> None:
    _counter(
        "utterai_ai_stage_failures_total",
        "Total failed AI pipeline stages",
    ).add(1, {"worker": worker, "stage": stage})
