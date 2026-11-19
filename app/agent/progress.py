from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_store: dict[str, dict[str, Any]] = {}


def record_progress(chat_id: str, node: str, status: str) -> None:
    key = str(chat_id or "").strip()
    if not key:
        return
    with _lock:
        _store[key] = {
            "node": str(node),
            "status": str(status),
            "updated_at": time.time(),
        }


def get_progress(chat_id: str) -> dict[str, Any] | None:
    key = str(chat_id or "").strip()
    if not key:
        return None
    with _lock:
        value = _store.get(key)
        return dict(value) if value else None


def clear_progress(chat_id: str) -> None:
    key = str(chat_id or "").strip()
    if not key:
        return
    with _lock:
        _store.pop(key, None)
