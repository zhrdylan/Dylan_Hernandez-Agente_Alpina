from __future__ import annotations

from pydantic import BaseModel, Field


class ChatCreate(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
