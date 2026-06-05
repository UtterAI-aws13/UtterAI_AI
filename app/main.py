# FastAPI 앱 진입점
# 라우터를 등록하고 uvicorn으로 실행한다
# 실행: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
from fastapi import FastAPI
from app.api import health, jobs, rag

app = FastAPI(title="UtterAI AI Module", version="0.1.0")

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(jobs.router, prefix="/internal/ai/analysis-jobs", tags=["analysis-jobs"])
app.include_router(rag.router, prefix="/ai/rag", tags=["rag"])
