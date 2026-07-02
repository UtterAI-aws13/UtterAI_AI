"""Pydantic schemas for insight map agent structured output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResolvedConcept(BaseModel):
    concept_id: str
    match_reason: str


class QueryResolveResult(BaseModel):
    resolved_concepts: list[ResolvedConcept] = Field(default_factory=list)


class ExplainResult(BaseModel):
    summary: str = ""
