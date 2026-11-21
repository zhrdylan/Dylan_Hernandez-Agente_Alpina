import unicodedata
from collections.abc import Mapping
from typing import Any


def get_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def normalize_text(text: Any) -> str:
    """Unifica el espacio y las mayúsculas al comparar texto documental."""
    return " ".join(str(text or "").split()).casefold()


def ascii_fold(text: str) -> str:
    """Convierte texto acentuado a ASCII conservando las mayúsculas."""
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
