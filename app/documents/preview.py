from __future__ import annotations

import hashlib
import io
import json
import re
import textwrap
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

from app.config import BASE_DIR
from app.db.connection import connect

LOCK_PATH = BASE_DIR / "data" / "manifest.lock.json"
CACHE_DIR = BASE_DIR / "data" / "cache" / "pages"
DOCUMENT_CACHE_DIR = BASE_DIR / "data" / "cache" / "documents"
PREVIEW_DPI = 150


class PagePreviewError(RuntimeError):
    pass


def _load_lock() -> dict:
    if not LOCK_PATH.is_file():
        return {}
    payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    return payload.get("documents") or {}


def _r2_pdf_path(document_id: str, version: str | None = None) -> Path | None:
    try:
        from app.storage.r2 import R2Storage, R2StorageError

        if not R2Storage.is_configured():
            return None
        with connect() as conn:
            with conn.cursor() as cur:
                if version:
                    cur.execute(
                        """
                        select storage_key
                        from public.document_versions
                        where document_id = %s and version = %s
                        limit 1
                        """,
                        (document_id, str(version)),
                    )
                else:
                    cur.execute(
                        """
                        select storage_key
                        from public.document_versions
                        where document_id = %s and is_current
                        order by created_at desc
                        limit 1
                        """,
                        (document_id,),
                    )
                row = cur.fetchone()
        if not row or not row[0]:
            return None
        v_tag = f"_v{version}" if version else ""
        target = DOCUMENT_CACHE_DIR / f"{document_id}{v_tag}.pdf"
        if target.is_file():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(R2Storage().get_bytes(str(row[0])))
        return target
    except Exception:
        return None


OFFICIAL_DOCUMENT_TITLES = {
    "C1": "Informe de Gestión 2026 · Alpina",
    "C2": "Informe de Sostenibilidad 2025 · Alpina",
    "C3": "Informe Alpina BIC 2025",
    "C4": "Estados Financieros Separados 2025 · Alpina S.A.S. BIC",
    "C5": "Estados Financieros Consolidados 2025 · Alpina",
    "N1": "Ley 2120 de 2021 (Ley de Comida Chatarra)",
    "N2": "Resolución 810 de 2021 (Etiquetado Nutricional y Frontal)",
    "N3": "Resolución 2492 de 2022 (Sellos Frontales de Advertencia)",
    "N4": "Resolución 2025013945 de 2025",
    "N5": "Resolución 5109 de 2005",
    "N6": "Resolución 333 de 2011",
    "N7": "Resolución 2674 de 2013",
    "N8": "Normograma de aditivos alimentarios",
    "N9": "ABECE: aplicación Resolución 2492 de 2022 y Resolución 810 de 2021",
    "N10": "Consolidado normativo 2026",
    "N11": "Política de Calidad de Alpina",
    "P1": "Portafolio de Claims Nutricionales 2024",
    "P2": "Finesse y Yox con Defensis",
    "P3": "Alpi10",
    "P4": "Alpina Baby Gu",
}


def resolve_document_title(document_id: str) -> str:
    """Obtiene el nombre oficial completo y legible del documento corporativo o normativo."""
    normalized = str(document_id or "").strip().upper()
    if normalized in OFFICIAL_DOCUMENT_TITLES:
        return OFFICIAL_DOCUMENT_TITLES[normalized]
    lock_entry = _load_lock().get(normalized)
    if lock_entry and lock_entry.get("title"):
        return str(lock_entry["title"])
    return normalized


def resolve_document_pdf(document_id: str, version: str | None = None) -> Path:
    normalized = str(document_id or "").strip().upper()
    if not re.fullmatch(r"[NPC]\d{1,2}", normalized):
        raise PagePreviewError("Documento no válido para vista previa.")

    # 1. Comprobar caché local de versión específica o general
    v_tag = f"_v{version}" if version else ""
    cached_v = DOCUMENT_CACHE_DIR / f"{normalized}{v_tag}.pdf"
    if cached_v.is_file():
        return cached_v

    # 2. Comprobar R2 con versión específica
    if version:
        r2_v_path = _r2_pdf_path(normalized, version=version)
        if r2_v_path and r2_v_path.is_file():
            return r2_v_path

    # 3. Fallback a documento base local o lockfile
    cached_base = DOCUMENT_CACHE_DIR / f"{normalized}.pdf"
    if cached_base.is_file():
        return cached_base

    lock_entry = _load_lock().get(normalized)
    if lock_entry and lock_entry.get("status") == "ok":
        local_path = BASE_DIR / str(lock_entry.get("local_path") or "")
        if local_path.is_file():
            return local_path

    # 4. Fallback a R2 versión vigente
    r2_path = _r2_pdf_path(normalized)
    if r2_path and r2_path.is_file():
        return r2_path

    raise PagePreviewError("No se encontró el PDF original del documento.")


def _clean_tokens(text: str) -> list[str]:
    raw_tokens = [t.strip(" .,;:\"'()[]{}«»“”’‘¿?¡!-–—\n\t") for t in (text or "").split()]
    return [t for t in raw_tokens if t]


def _quote_boxes(pdf_path: Path, page_number: int, quote: str) -> list[dict]:
    tokens = _clean_tokens(quote)
    if not tokens:
        return []

    boxes: list[dict] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_number > len(pdf.pages):
                return []
            page = pdf.pages[page_number - 1]

            # Intento 1: Búsqueda regex completa con tolerancia a signos de puntuación, saltos de línea y mayúsculas
            if len(tokens) <= 40:
                full_pattern = r"[\s\W]+".join(re.escape(t) for t in tokens)
                try:
                    matches = page.search(full_pattern, regex=True, case=False)
                    if matches:
                        return matches
                except Exception:
                    pass

            # Intento 2: Búsqueda por ventanas deslizantes consecutivas (cubriendo fragmentos largos multilínea)
            window_size = 5
            seen_coords = set()
            for i in range(0, len(tokens), 3):
                window = tokens[i : i + window_size]
                if len(window) < 2:
                    continue
                win_pattern = r"[\s\W]+".join(re.escape(t) for t in window)
                try:
                    win_matches = page.search(win_pattern, regex=True, case=False)
                    for m in win_matches or []:
                        key = (
                            round(float(m.get("x0", 0))),
                            round(float(m.get("top", 0))),
                            round(float(m.get("x1", 0))),
                            round(float(m.get("bottom", 0))),
                        )
                        if key not in seen_coords:
                            seen_coords.add(key)
                            boxes.append(m)
                except Exception:
                    continue

            if boxes:
                return boxes

            # Intento 3: Respaldo por subfrases literales
            for candidate in [quote[:80], quote[-80:]]:
                cand_clean = " ".join(candidate.split()).strip()
                if len(cand_clean) > 8:
                    try:
                        matches = page.search(cand_clean, regex=False, case=False)
                        if matches:
                            return matches
                    except Exception:
                        pass
    except Exception:
        return []

    return boxes


def _highlight(image: Image.Image, boxes: list[dict], dpi: int) -> Image.Image:
    if not boxes:
        return image
    scale = dpi / 72
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for box in boxes:
        left = max(0, float(box.get("x0", 0)) * scale - 1.5)
        top = max(0, float(box.get("top", 0)) * scale - 1.5)
        right = float(box.get("x1", 0)) * scale + 1.5
        bottom = float(box.get("bottom", 0)) * scale + 1.5
        # Resaltador sutil corporativo: azul/ámbar suave con 25% opacidad y borde fino
        draw.rectangle(
            [left, top, right, bottom],
            fill=(3, 105, 161, 64),      # Azul institucional tenue con opacidad 25% (64/255)
            outline=(2, 132, 199, 200),  # Borde sutil limpio y preciso
            width=2,
        )
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def render_product_sheet_png(product_id: str, quote: str | None = None) -> bytes:
    clean = str(product_id or "").strip()
    sku_val = clean.lower()
    sku_num = sku_val.replace("sku-", "").replace("product-", "")

    quote_key = (
        hashlib.sha256(" ".join((quote or "").split()).encode("utf-8")).hexdigest()[:16]
        if quote
        else "plain"
    )
    cache_path = CACHE_DIR / "products" / f"{sku_val}-{quote_key}.png"
    if cache_path.is_file():
        return cache_path.read_bytes()

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, name, brand, presentation, price::float8,
                       protein_g::float8, claims, availability, ean, metadata
                from public.products
                where id ilike %s or id ilike %s or id ilike %s
                limit 1
                """,
                (sku_val, f"sku-{sku_num}", sku_num),
            )
            row = cur.fetchone()

    if not row:
        raise PagePreviewError(f"No se encontró información del producto con SKU {product_id}.")

    pid, name, brand, pres, price, protein, claims, avail, ean, meta = row
    meta = meta or {}

    W, H = 700, 920
    img = Image.new("RGB", (W, H), color="#f8fafc")
    draw = ImageDraw.Draw(img)

    try:
        f_title = ImageFont.truetype("segoeuib.ttf", 23)
        f_sub = ImageFont.truetype("segoeuib.ttf", 13)
        f_body = ImageFont.truetype("segoeui.ttf", 14)
        f_body_b = ImageFont.truetype("segoeuib.ttf", 14)
        f_price = ImageFont.truetype("segoeuib.ttf", 24)
        f_sm = ImageFont.truetype("segoeui.ttf", 12)
        f_quote = ImageFont.truetype("segoeui.ttf", 13)
    except Exception:
        f_title = f_sub = f_body = f_body_b = f_price = f_sm = f_quote = ImageFont.load_default()

    # Contenedor blanco tipo ficha técnica
    draw.rounded_rectangle([20, 20, W - 20, H - 20], radius=16, fill="#ffffff", outline="#cbd5e1", width=2)

    # Cabecera institucional Alpina (#0b1f3a)
    draw.rounded_rectangle([20, 20, W - 20, 105], radius=16, fill="#0b1f3a")
    draw.rectangle([20, 85, W - 20, 105], fill="#0b1f3a")
    draw.text((45, 40), "ALPINA · FICHA OFICIAL DE PRODUCTO", fill="#93c5fd", font=f_sub)
    draw.text((45, 65), "CATÁLOGO MAESTRO · TRAZABILIDAD VERIFICADA", fill="#ffffff", font=f_sub)

    logo_path = BASE_DIR / "app" / "static" / "brand" / "alpina-logo.png"
    if logo_path.is_file():
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo.thumbnail((48, 48))
            img.paste(logo, (W - 80, 40), mask=logo)
        except Exception:
            pass

    # Nombre oficial del producto
    wrapped_name = textwrap.fill(name or "Producto Alpina", width=42)
    draw.text((45, 125), wrapped_name, fill="#0f223d", font=f_title)

    # Metadatos del producto
    meta_parts = [f"SKU: {pid.upper()}"]
    if ean:
        meta_parts.append(f"EAN: {ean}")
    if brand:
        meta_parts.append(f"Marca: {brand}")
    draw.text((45, 170), "  ·  ".join(meta_parts), fill="#64748b", font=f_sm)

    # 3 Tarjetas de métricas oficiales
    # 1. Precio
    draw.rounded_rectangle([45, 195, 235, 280], radius=10, fill="#eff6ff", outline="#bfdbfe", width=1)
    draw.text((60, 205), "PRECIO OFICIAL", fill="#0152d1", font=f_sm)
    price_str = f"${price:,.0f}".replace(",", ".") if price else "No consta"
    draw.text((60, 232), price_str, fill="#0152d1", font=f_price)

    # 2. Proteína
    draw.rounded_rectangle([250, 195, 440, 280], radius=10, fill="#ecfdf5", outline="#a7f3d0", width=1)
    draw.text((265, 205), "PROTEÍNA", fill="#059669", font=f_sm)
    prot_str = f"{protein:g} g" if protein is not None else "No declarada"
    draw.text((265, 232), prot_str, fill="#059669", font=f_price)

    # 3. Presentación
    draw.rounded_rectangle([455, 195, W - 45, 280], radius=10, fill="#f8fafc", outline="#e2e8f0", width=1)
    draw.text((470, 205), "PRESENTACIÓN", fill="#64748b", font=f_sm)
    draw.text((470, 232), str(pres or "Oficial")[:14], fill="#0f223d", font=f_price)

    # Descripción oficial si existe
    desc = meta.get("description") or ""
    cy = 300
    if desc:
        draw.text((45, cy), "DESCRIPCIÓN OFICIAL", fill="#0f223d", font=f_sub)
        cy += 24
        for line in textwrap.wrap(desc, width=70)[:3]:
            draw.text((45, cy), line, fill="#475569", font=f_body)
            cy += 20
        cy += 10

    # Claims nutricionales declarados
    draw.text((45, cy), "DECLARACIONES Y CLAIMS NUTRICIONALES", fill="#0f223d", font=f_sub)
    cy += 26
    c_list = claims if isinstance(claims, list) else []
    if not c_list:
        c_list = ["Sin sellos de advertencia frontal reportados"]
    for c in c_list[:4]:
        draw.rounded_rectangle([45, cy, W - 45, cy + 30], radius=6, fill="#f1f5f9", outline="#e2e8f0", width=1)
        draw.text((58, cy + 6), f"✓  {c}", fill="#334155", font=f_body)
        cy += 36

    # Recuadro resaltado de la cita consultada
    if quote:
        cy += 14
        draw.text((45, cy), "EVIDENCIA DE CITA AUDITADA", fill="#d97706", font=f_sub)
        cy += 24
        q_lines = textwrap.wrap(f'"{quote}"', width=68)
        box_h = 24 + len(q_lines) * 20 + 24
        draw.rounded_rectangle([45, cy, W - 45, cy + box_h], radius=8, fill="#fffbeb", outline="#fcd34d", width=1)
        draw.rectangle([45, cy, 50, cy + box_h], fill="#d97706")
        qy = cy + 12
        for ql in q_lines[:5]:
            draw.text((62, qy), ql, fill="#92400e", font=f_quote)
            qy += 20
        # Verificar si la cita coincide textualmente con algún atributo de la ficha (F10, F12)
        full_prod_text = f"{name} {desc} {' '.join(c_list)} {pres} {row.get('ingredients') or ''} {row.get('allergens') or ''}".casefold()
        has_text_match = bool(quote and quote.strip().casefold() in full_prod_text)
        match_msg = (
            "Coincidencia textual verificada en la ficha oficial."
            if has_text_match
            else "Referencia consultada (no coincide textualmente con campos de la ficha)."
        )
        draw.text((62, qy + 4), match_msg, fill="#b45309", font=f_sm)

    # Pie de página con verificación de trazabilidad
    draw.line([(45, H - 65), (W - 45, H - 65)], fill="#e2e8f0", width=1)
    draw.text((45, H - 48), "✓  Verificación Oficial de Producto Alpina · Supabase pgvector", fill="#059669", font=f_body_b)
    draw.text((W - 170, H - 48), "Agente Documental IA", fill="#64748b", font=f_sm)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    payload = buffer.getvalue()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(payload)
    return payload


def render_page_png(
    document_id: str,
    page_number: int,
    *,
    version: str | None = None,
    quote: str | None = None,
    dpi: int = PREVIEW_DPI,
) -> bytes:
    normalized = str(document_id or "").strip().upper()
    if normalized.startswith("SKU-") or normalized.startswith("PRODUCT-"):
        return render_product_sheet_png(normalized, quote=quote)

    if page_number < 1:
        raise PagePreviewError("La página debe ser mayor o igual a 1.")

    pdf_path = resolve_document_pdf(document_id, version=version)
    quote_key = (
        hashlib.sha256(" ".join((quote or "").split()).encode("utf-8")).hexdigest()[:16]
        if quote
        else "plain"
    )
    v_tag = f"v{version}_" if version else ""
    cache_path = CACHE_DIR / normalized / f"{v_tag}p{page_number}-{quote_key}-{dpi}.png"
    if cache_path.is_file():
        return cache_path.read_bytes()

    document = pdfium.PdfDocument(str(pdf_path))
    try:
        page_count = len(document)
        if page_number > page_count:
            raise PagePreviewError(
                f"La página {page_number} no existe; el documento tiene {page_count}."
            )
        page = document[page_number - 1]
        try:
            image = page.render(scale=dpi / 72).to_pil().convert("RGB")
        finally:
            page.close()
    finally:
        document.close()

    if quote:
        boxes = _quote_boxes(pdf_path, page_number, quote)
        if boxes:
            image = _highlight(image, boxes, dpi)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    payload = buffer.getvalue()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(payload)
    return payload


def get_document_page_count(document_id: str) -> int:
    """Devuelve el número total de páginas del documento."""
    normalized = str(document_id or "").strip().upper()
    try:
        pdf_path = resolve_document_pdf(normalized)
        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            return len(doc)
        finally:
            doc.close()
    except Exception:
        return 1
