"""Helpers for Phoenix-friendly AI tracing.

Phoenix receives selected OpenTelemetry spans from the collector. Keep
attributes here intentionally low-cardinality and free of raw prompt,
transcript, SOAP note, or patient-identifying content.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from app.config import settings

OI_SPAN_KIND = "openinference.span.kind"
OI_CHAIN = "CHAIN"
OI_RETRIEVER = "RETRIEVER"
OI_LLM = "LLM"

_BLOCKED_ATTRIBUTE_KEYS = {
    "prompt",
    "llm.prompt",
    "transcript.text",
    "soap",
    "soap_note",
    "patient",
    "user",
}

_BLOCKED_ATTRIBUTE_PREFIXES = (
    "prompt.text",
    "llm.prompt.",
    "transcript.raw",
    "transcript.text",
    "soap.",
    "soap_note.",
    "patient.",
    "user.",
)


def phoenix_enabled() -> bool:
    return settings.phoenix_tracing_enabled


def safe_id(value: str | None) -> str:
    if not value:
        return "unknown"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def set_safe_attributes(span: Any, attributes: Mapping[str, Any]) -> None:
    if not phoenix_enabled():
        return
    for key, value in attributes.items():
        if value is None:
            continue
        if key in _BLOCKED_ATTRIBUTE_KEYS or key.startswith(_BLOCKED_ATTRIBUTE_PREFIXES):
            continue
        if isinstance(value, (str, bool, int, float)):
            span.set_attribute(key, value)


def set_openinference_span_kind(span: Any, kind: str) -> None:
    if not phoenix_enabled():
        return
    span.set_attribute(OI_SPAN_KIND, kind)
