from typing import (
    Literal,
)

from pydantic import (
    BaseModel,
    Field,
)


class EvidencePayload(BaseModel):
    snippet: str = Field(description="Exact code fragment copied from the patch")
    line_start: int | None = None
    line_end: int | None = None


class FindingPayload(BaseModel):
    line_start: int
    line_end: int
    severity: Literal["critical", "major", "minor", "nitpick"]
    category: Literal[
        "correctness",
        "security",
        "performance",
        "style",
        "tests",
        "architecture",
    ]
    title: str
    body: str
    code_fragment: str = Field(description="Exact line or lines the finding refers to")
    anchor_symbol: str | None = Field(
        default=None,
        description="Enclosing function or class, used for deduplication",
    )
    suggested_patch: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[EvidencePayload] = Field(default_factory=list)


class ReviewPayload(BaseModel):
    findings: list[FindingPayload] = Field(default_factory=list)
