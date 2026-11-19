from __future__ import annotations

from typing import Any
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    environment: str
    agent_ready: bool
    startup_error: str | None = None


class SuggestionsResponse(BaseModel):
    items: list[str]
    total: int


class StatsResponse(BaseModel):
    documents: int
    products: int
    chunks: int
    embeddings: int
    pages: int
