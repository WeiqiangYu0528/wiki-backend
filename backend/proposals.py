"""Proposal data model and in-memory store for approval-gated doc changes."""

import difflib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

ALLOWED_PATH_PREFIX = "docs/"


class ProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class FileChange(BaseModel):
    path: str
    original_content: str
    proposed_content: str
    diff: str = ""


class Proposal(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    summary: str
    commit_message: str
    files: list[FileChange]
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    result: Optional[dict] = None


def compute_diff(file_path: str, original: str, proposed: str) -> str:
    """Compute a unified diff between original and proposed content."""
    return "\n".join(difflib.unified_diff(
        original.splitlines(keepends=True),
        proposed.splitlines(keepends=True),
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
    ))


class ProposalStore:
    """In-memory proposal store. Swap for Redis in cloud deployment."""

    def __init__(self) -> None:
        self._proposals: dict[str, Proposal] = {}

    def create(self, summary: str, commit_message: str, files: list[FileChange]) -> Proposal:
        proposal = Proposal(summary=summary, commit_message=commit_message, files=files)
        self._proposals[proposal.id] = proposal
        return proposal

    def get(self, proposal_id: str) -> Optional[Proposal]:
        return self._proposals.get(proposal_id)

    def update_status(
        self, proposal_id: str, status: ProposalStatus, result: Optional[dict] = None
    ) -> Optional[Proposal]:
        p = self._proposals.get(proposal_id)
        if p:
            p.status = status
            if result is not None:
                p.result = result
        return p

    def list_pending(self) -> list[Proposal]:
        return [p for p in self._proposals.values() if p.status == ProposalStatus.PENDING]


# Singleton — shared across agent and API
proposal_store = ProposalStore()
