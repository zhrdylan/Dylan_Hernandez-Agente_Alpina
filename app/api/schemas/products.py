from __future__ import annotations

from typing import Any
from pydantic import BaseModel


class ProductItem(BaseModel):
    id: str
    ean: str | None = None
    name: str
    brand: str | None = None
    presentation: str | None = None
    price: float | None = None
    currency: str | None = None
    protein_g: float | None = None
    claims: list[str] | None = None
    ingredients: str | None = None
    allergens: str | None = None
    availability: str | None = None
    source_url: str | None = None
    source_page: int | None = None
    image_url: str | None = None
    verified_at: Any = None
    metadata: dict[str, Any] | None = None


class ProductListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int
