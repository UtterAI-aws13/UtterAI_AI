from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DiffOp:
    op: str
    a_lines: list[int] = field(default_factory=list)
    b_lines: list[int] = field(default_factory=list)


@dataclass
class RevisionProposal:
    target_section: str
    original_text: str
    proposed_text: str
    rationale: str
    evidence_refs: list[str] = field(default_factory=list)
    diff_ops: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "target_section": self.target_section,
            "original_text": self.original_text,
            "proposed_text": self.proposed_text,
            "rationale": self.rationale,
            "evidence_refs": self.evidence_refs,
        }


@dataclass
class ChatAgentResult:
    intent: dict
    assistant_message: str
    patch_proposal: Optional[RevisionProposal] = None

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "assistant_message": self.assistant_message,
            "patch_proposal": self.patch_proposal.to_dict() if self.patch_proposal else None,
        }
