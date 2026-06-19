"""Observability helpers for AI API and workers."""

from app.observability.metrics import (
    record_job_created,
    record_sqs_publish,
    record_sqs_receive,
    record_stage_duration,
    record_stage_failure,
)
from app.observability.otel import (
    get_meter,
    get_tracer,
    initialize_observability,
    instrument_fastapi_app,
)
from app.observability.sqs import (
    build_message_attributes_from_current_context,
    extract_context_from_message_attributes,
)

__all__ = [
    "build_message_attributes_from_current_context",
    "extract_context_from_message_attributes",
    "get_meter",
    "get_tracer",
    "initialize_observability",
    "instrument_fastapi_app",
    "record_job_created",
    "record_sqs_publish",
    "record_sqs_receive",
    "record_stage_duration",
    "record_stage_failure",
]
