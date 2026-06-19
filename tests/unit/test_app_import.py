def test_app_import(monkeypatch):
    """CI에서 FastAPI 앱이 최소 설정으로 import되는지 확인합니다."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://utterai:utterai@localhost:5432/utterai_ai",
    )
    monkeypatch.setenv("APP_ENV", "ci")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-2")

    from app.main import app

    assert app.title == "UtterAI AI Module"
