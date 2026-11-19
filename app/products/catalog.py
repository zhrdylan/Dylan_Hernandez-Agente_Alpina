from __future__ import annotations

import html
import re
from datetime import date
from typing import Any

MEDIA_BASE = "https://alpina.com/media/catalog/product"
SITE_BASE = "https://alpina.com"
IVA_RATE = 0.19

_SIZE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l|litros?|unidades?|und)\b",
    re.IGNORECASE,
)
_PACK_RE = re.compile(r"(?:x|por)\s*(\d+)\s*(?:und|unidades?)\b", re.IGNORECASE)
_PROTEIN_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*g(?:ramos)?\s*(?:de\s*)?prote[ií]na",
    re.IGNORECASE,
)
_CLAIM_PATTERNS = [
    (
        re.compile(
            r"(?:sin|no tiene)\s+az[uú]car(?:es)?\s+a[ñn]adid[oa]s?",
            re.IGNORECASE,
        ),
        "Sin azúcar añadido",
    ),
    (
        re.compile(
            r"(\d+(?:[.,]\d+)?\s*g\s*(?:de\s*)?prote[ií]na(?:\s+por\s+porci[oó]n)?)",
            re.IGNORECASE,
        ),
        None,
    ),
    (
        re.compile(r"fuente\s+de\s+([^,.;]+)", re.IGNORECASE),
        "Fuente de {value}",
    ),
    (
        re.compile(r"libre\s+de\s+([^,.;]+)", re.IGNORECASE),
        "Libre de {value}",
    ),
    (
        re.compile(r"alto\s+en\s+([^,.;]+)", re.IGNORECASE),
        "Alto en {value}",
    ),
    (re.compile(r"ingredientes\s+naturales", re.IGNORECASE), "Ingredientes naturales"),
]


def strip_html(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = html.unescape(text)
    return " ".join(text.split())


def _normalize_size(value: str) -> str:
    amount = value.replace(",", ".")
    if "." in amount:
        amount = amount.rstrip("0").rstrip(".")
    return amount


def parse_presentation(
    name: str,
    measurement_unit: str | None = None,
) -> str | None:
    text = " ".join(str(name or "").split())
    if not text:
        return None

    pack_match = _PACK_RE.search(text)
    pack = int(pack_match.group(1)) if pack_match else None

    size_match = None
    for match in _SIZE_RE.finditer(text):
        size_match = match
    if size_match:
        amount = _normalize_size(size_match.group(1))
        unit = size_match.group(2).lower()
        if unit.startswith("litro"):
            unit = "L"
        elif unit == "l":
            unit = "L"
        elif unit == "und" or unit.startswith("unidade"):
            unit = "und"
        size = f"{amount} {unit}"
        return f"{pack} x {size}" if pack else size

    if pack:
        return f"{pack} und"
    return None


def parse_protein(description: str) -> float | None:
    match = _PROTEIN_RE.search(str(description or ""))
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    if 0 < value <= 100:
        return value
    return None


def extract_claims(description: str, short_description: str = "") -> list[str]:
    text = " ".join(
        part for part in [strip_html(short_description), strip_html(description)] if part
    )
    claims: list[str] = []
    seen: set[str] = set()

    for pattern, template in _CLAIM_PATTERNS:
        for match in pattern.finditer(text):
            if template is None:
                claim = " ".join(match.group(1).split())
                claim = re.sub(r"\s+", " ", claim).strip(" .,;")
            else:
                value = " ".join((match.group(1) if match.groups() else "").split())
                claim = template.format(value=value).strip(" .,;")
            normalized = claim.casefold()
            if claim and normalized not in seen:
                seen.add(normalized)
                claims.append(claim)
            if len(claims) >= 5:
                return claims

    if not claims:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            clean = " ".join(sentence.split()).strip(" .,;")
            if clean and any(
                token in clean.casefold()
                for token in ("sin ", "0%", "fuente", "proteína", "calcio", "natural")
            ):
                claims.append(clean[:120])
                if len(claims) >= 3:
                    break

    return claims


def catalog_item_to_product(item: dict) -> dict:
    attributes = {
        str(attribute.get("attribute_code")): attribute.get("value")
        for attribute in (item.get("custom_attributes") or [])
        if attribute.get("attribute_code")
    }

    name = " ".join(str(item.get("name") or "").split())
    sku = str(item.get("sku") or "").strip()
    description = strip_html(attributes.get("description"))
    short_description = strip_html(attributes.get("short_description"))
    price = float(item.get("price") or 0)
    try:
        tax_class_id = int(attributes.get("tax_class_id") or 0)
    except (TypeError, ValueError):
        tax_class_id = 0
    display_price = round(price * (1 + IVA_RATE)) if tax_class_id == 2 else round(price)

    ean = str(attributes.get("ean") or "").strip() or None
    image = str(attributes.get("image") or attributes.get("small_image") or "")
    if image and not image.startswith("http"):
        image_url = f"{MEDIA_BASE}{image if image.startswith('/') else '/' + image}"
    else:
        image_url = image or None

    url_key = str(attributes.get("url_key") or sku)
    source_url = f"{SITE_BASE}/{url_key.lstrip('/')}"
    status = int(item.get("status") or 0)
    availability = "Disponible" if status == 1 else "No disponible"

    metadata = {
        "description": description,
        "short_description": short_description,
        "image_url": image_url,
        "url_key": url_key,
        "label": attributes.get("label"),
        "measurement_unit": attributes.get("measurement_unit"),
        "tax_class_id": tax_class_id,
        "price_before_tax": round(price, 2),
        "category_ids": attributes.get("category_ids") or [],
        "source": "alpina.com REST",
        "verified_on": date.today().isoformat(),
    }
    if display_price is not None and display_price < 100:
        metadata["original_price"] = round(price, 2)
        display_price = None

    return {
        "id": sku,
        "ean": ean,
        "name": name,
        "brand": "Alpina",
        "presentation": parse_presentation(name, attributes.get("measurement_unit")),
        "price": display_price,
        "currency": "COP",
        "protein_g": parse_protein(description),
        "claims": extract_claims(description, short_description),
        "ingredients": None,
        "allergens": None,
        "availability": availability,
        "source_url": source_url,
        "source_page": 1,
        "metadata": metadata,
    }


def is_catalog_product(item: dict) -> bool:
    name = str(item.get("name") or "").casefold()
    if any(
        token in name
        for token in ("receta", "test", "sin titulo", "sin título")
    ):
        return False
    attributes = {
        str(attribute.get("attribute_code")): attribute.get("value")
        for attribute in (item.get("custom_attributes") or [])
        if attribute.get("attribute_code")
    }
    return bool(str(attributes.get("ean") or "").strip())


def dedupe_eans(
    products: list[dict],
    reserved: set[str] | None = None,
) -> list[dict]:
    seen = {str(value) for value in (reserved or set()) if value}
    for product in products:
        ean = product.get("ean")
        if not ean:
            continue
        if ean in seen:
            metadata = dict(product.get("metadata") or {})
            metadata["original_ean"] = ean
            product["metadata"] = metadata
            product["ean"] = None
            continue
        seen.add(ean)
    return products
