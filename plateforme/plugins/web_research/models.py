"""Structured outputs of the tools, published as their MCP output schemas.

Every text field holds external content: data for the reader, never instructions (R5).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

MAX_RESULTS = 10


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SearchHit(_Out):
    rank: int = Field(ge=1, le=MAX_RESULTS)
    title: str
    url: str
    snippet: str
    age: str | None = Field(default=None, description="Ancienneté annoncée par le moteur")


class SearchResults(_Out):
    query: str
    provider: str
    results: list[SearchHit] = Field(max_length=MAX_RESULTS)


class PageText(_Out):
    url: str = Field(description="URL demandée")
    final_url: str = Field(description="URL lue après les redirections")
    content_type: str
    title: str | None
    published: str | None = Field(description="Date trouvée dans la page, non vérifiée")
    text: str
    truncated: bool = Field(description="Texte coupé à la limite de caractères")
    retrieved_at: str
