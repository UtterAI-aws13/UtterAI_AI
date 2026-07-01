from app.observability.phoenix import safe_id, set_safe_attributes
from app.config import settings


class DummySpan:
    def __init__(self):
        self.attributes = {}

    def set_attribute(self, key, value):
        self.attributes[key] = value


def test_safe_id_hashes_without_exposing_raw_value():
    raw = "session-123"

    hashed = safe_id(raw)

    assert hashed != raw
    assert hashed == safe_id(raw)
    assert len(hashed) == 16


def test_set_safe_attributes_skips_complex_values(monkeypatch):
    monkeypatch.setattr(settings, "phoenix_tracing_enabled", True)
    span = DummySpan()

    set_safe_attributes(span, {
        "prompt.text": "do-not-use-this-helper-for-raw-prompts",
        "count": 3,
        "nested": {"raw": "value"},
        "empty": None,
    })

    assert span.attributes == {
        "count": 3,
    }
