# FastAPI 앱 진입점
# 라우터를 등록하고 uvicorn으로 실행한다
# 실행: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
from fastapi import FastAPI

from app.observability.otel import initialize_observability, instrument_fastapi_app
from app.api import health, jobs, rag
from app.api.insight_map import router as insight_map_router
from app.api.report_chat import router as report_chat_router

app = FastAPI(title="UtterAI AI Module", version="0.1.0")

initialize_observability()

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(jobs.router, prefix="/internal/ai/analysis-jobs", tags=["analysis-jobs"])
app.include_router(rag.router, prefix="/ai/rag", tags=["rag"])
app.include_router(report_chat_router, prefix="/ai", tags=["report-chat"])
app.include_router(insight_map_router, prefix="/ai/insight-map", tags=["insight-map"])
instrument_fastapi_app(app)
