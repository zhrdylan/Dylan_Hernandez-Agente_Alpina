from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import chats, documents, products, reports, system

api_router = APIRouter()

api_router.include_router(system.router)
api_router.include_router(chats.router)
api_router.include_router(reports.router)
api_router.include_router(documents.router)
api_router.include_router(products.router)
