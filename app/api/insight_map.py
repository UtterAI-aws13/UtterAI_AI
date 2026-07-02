"""Internal API endpoints for insight map auxiliary agents (query resolve, explain)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.insight_map.explainer_agent import run_explainer
from app.agents.insight_map.query_resolver_agent import run_query_resolver
from app.rag.paper_metadata import get_doi_url
from app.rag.retriever import retrieve_evidence

router = APIRouter()


class ResolveQueryRequest(BaseModel):
    query: str


class ResolvedConceptResponse(BaseModel):
    concept_id: str
    match_reason: str


class ResolveQueryResponse(BaseModel):
    resolved_concepts: list[ResolvedConceptResponse]


@router.post("/resolve-query", response_model=ResolveQueryResponse)
def resolve_query(request: ResolveQueryRequest) -> ResolveQueryResponse:
    result = run_query_resolver(request.query)
    return ResolveQueryResponse(**result)


class ExplainPathNode(BaseModel):
    label: str
    type: str = ""
    relation_from_prev: str | None = None


class ExplainRequest(BaseModel):
    path: list[ExplainPathNode]


class ExplainResponse(BaseModel):
    summary: str


@router.post("/explain", response_model=ExplainResponse)
def explain(request: ExplainRequest) -> ExplainResponse:
    result = run_explainer([node.model_dump() for node in request.path])
    return ExplainResponse(**result)


class EvidenceRequest(BaseModel):
    query: str
    top_k: int = 3


class EvidenceItem(BaseModel):
    title: str
    content: str
    score: float
    doi_url: str | None = None


class EvidenceResponse(BaseModel):
    evidence: list[EvidenceItem]


@router.post("/evidence", response_model=EvidenceResponse)
async def get_evidence(request: EvidenceRequest) -> EvidenceResponse:
    results = await retrieve_evidence(metrics={}, session={}, top_k=request.top_k, direct_query=request.query)
    return EvidenceResponse(
        evidence=[
            EvidenceItem(
                title=r["title"],
                content=r["content"],
                score=r["score"],
                doi_url=get_doi_url(r["document_id"]),
            )
            for r in results
        ]
    )
