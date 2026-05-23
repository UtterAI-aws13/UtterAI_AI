from fastapi import FastAPI
from app.api import health, jobs, rag

app = FastAPI(title="UtterAI AI Module", version="0.1.0")

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(jobs.router, prefix="/ai/jobs", tags=["jobs"])
app.include_router(rag.router, prefix="/ai/rag", tags=["rag"])
