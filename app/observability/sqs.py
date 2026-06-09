"""Trace context helpers for SQS MessageAttributes."""

from __future__ import annotations

from opentelemetry.context import get_current
from opentelemetry.propagate import extract, inject


def build_message_attributes_from_current_context() -> dict[str, dict[str, str]]:
    carrier: dict[str, str] = {}
    inject(carrier, context=get_current())
    attributes: dict[str, dict[str, str]] = {}
    for key, value in carrier.items():
        attributes[key] = {"DataType": "String", "StringValue": value}
    return attributes


def extract_context_from_message_attributes(message_attributes: dict | None):
    carrier: dict[str, str] = {}
    if message_attributes:
        for key, value in message_attributes.items():
            string_value = value.get("StringValue") if isinstance(value, dict) else None
            if string_value:
                carrier[key] = string_value
    return extract(carrier)
