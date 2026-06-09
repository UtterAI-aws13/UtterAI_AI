"""Shared pytest fixtures for UtterAI AI tests."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def app():
    import os
    os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://utterai:utterai@localhost:5432/utterai_ai_test")
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("AWS_REGION", "ap-northeast-2")

    from app.main import app as _app
    return _app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c
