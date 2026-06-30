"""Internal API endpoint for report chat processing."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.pipelines.report_chat_pipeline import run_report_chat

router = APIRouter()


class ReportChatRequest(BaseModel):
    report_id: str
    report_version: int
    message: str
    segments: list[dict]
    history: list[dict]


class ReportChatResponse(BaseModel):
    intent: dict | None
    assistant_message: str
    patch_proposal: dict | None


@router.post("/report-chat", response_model=ReportChatResponse)
def report_chat(request: ReportChatRequest) -> ReportChatResponse:
    result = run_report_chat(
        report_id=request.report_id,
        report_version=request.report_version,
        message=request.message,
        segments=request.segments,
        history=request.history,
    )
    return ReportChatResponse(**result)