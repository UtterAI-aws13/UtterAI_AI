"""Internal API endpoint for report chat processing."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.report_editing_chatbot.agent import run_agent

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
    result = run_agent(
        report_id=request.report_id,
        report_version=request.report_version,
        message=request.message,
        segments=request.segments,
        history=request.history,
    )
    return ReportChatResponse(**result)
