from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class ChatCreate(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    user_id: str | None = Field(default=None, max_length=64)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class ChatItem(BaseModel):
    id: str
    title: str
    user_id: str | None = None
    created_at: Any
    updated_at: Any


class MessageItem(BaseModel):
    id: str
    role: str
    content: str
    citations: list[dict[str, Any]] | None = None
    model: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: Any
