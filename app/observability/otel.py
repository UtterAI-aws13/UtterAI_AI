"""OpenTelemetry bootstrap and framework instrumentation."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as HTTPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPSpanExporter
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import settings
from app.storage.db import get_engine

_LOGGER = logging.getLogger(__name__)
_INITIALIZED = False


def _resource() -> Resource:
    attributes: dict[str, str] = {}
    for item in settings.otel_resource_attributes.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        attributes[key.strip()] = value.strip()
    attributes.setdefault("service.name", settings.otel_service_name)
    attributes.setdefault("service.version", "0.1.0")
    return Resource.create(attributes)


def _trace_exporter():
    base = settings.otel_exporter_otlp_endpoint.rstrip("/")
    return HTTPSpanExporter(endpoint=f"{base}/v1/traces")


def _metric_exporter():
    base = settings.otel_exporter_otlp_endpoint.rstrip("/")
    return HTTPMetricExporter(endpoint=f"{base}/v1/metrics")


def initialize_observability() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return

    resource = _resource()

    tracer_provider = TracerProvider(resource=resource)
    if settings.otel_traces_exporter != "none":
        tracer_provider.add_span_processor(BatchSpanProcessor(_trace_exporter()))
    trace.set_tracer_provider(tracer_provider)

    metric_readers = (
        [PeriodicExportingMetricReader(_metric_exporter())]
        if settings.otel_metrics_exporter != "none"
        else []
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=metric_readers))

    try:
        SQLAlchemyInstrumentor().instrument(engine=get_engine().sync_engine)
    except Exception:  # pragma: no cover - best effort instrumentation
        _LOGGER.exception("Failed to instrument SQLAlchemy")

    try:
        HTTPXClientInstrumentor().instrument()
    except Exception:  # pragma: no cover - best effort instrumentation
        _LOGGER.exception("Failed to instrument HTTPX")

    try:
        BotocoreInstrumentor().instrument()
    except Exception:  # pragma: no cover - best effort instrumentation
        _LOGGER.exception("Failed to instrument botocore")

    _INITIALIZED = True


def instrument_fastapi_app(app: FastAPI) -> None:
    initialize_observability()
    FastAPIInstrumentor.instrument_app(app)


def get_tracer(name: str):
    return trace.get_tracer(name)


def get_meter(name: str):
    return metrics.get_meter(name)
