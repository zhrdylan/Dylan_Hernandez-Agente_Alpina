from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from urllib.parse import unquote

from markdown_it.tree import SyntaxTreeNode

from app.agent.prompts import REPORT_UNAVAILABLE
from app.core.markdown import escape_inline, markdown_tree, plain_markdown, spreadsheet_rows, unwrap_markdown
from app.reports.spec import ReportCitation, ReportSection, ReportTable


REFERENCE_HEADING = re.compile(
    r"^(?:fuentes?(?:\s+oficiales?|\s+documentales?)?(?:\s+(?:citadas?|consultadas?))?"
    r"|referencias(?:\s+(?:documentales|bibliogr[aá]ficas))?|bibliograf[ií]a"
    r"|citas(?:\s+(?:documentales|oficiales))?|documentos\s+(?:citados|consultados)"
    r"|evidencias?\s+documentales(?:\s+y\s+citas\s+oficiales)?)"
    r"(?:\s+y\s+(?:fuentes|referencias))?\s*(?::.*)?$",
    re.IGNORECASE,
)
REFERENCE_MARKER = re.compile(
    r"【[^】\n]+】|\[(?:\^[-\w]+|(?:fuentes?|citas?|documentos?)\s+[^\]\n]+"
    r"|\d{1,3}(?:\s*[,;]\s*\d{1,3})*)\](?:\([^\n)]*\))?",
    re.IGNORECASE,
)
FILE_EXTENSION = r"\.(?:pdf|docx?|xlsx?)\b"
FILE_REFERENCE = re.compile(
    rf"""(?:\b(?:archivo|fichero)\s+[^,\n;.!?]{{1,160}}|["“\x60][^"”\x60\n]+|"""
    rf"""[^\s<>()\[\]"“”\x60|,;]+){FILE_EXTENSION}["”\x60]?(?:[?#][^\s<>()\[\]|,;]+)?""",
    re.IGNORECASE,
)
SOURCE_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\n]+)\)")
DOCUMENT_URL = re.compile(r"(?:https?://[^\s<>\[\]()]*)?/api/documents/[^\s<>\[\]()]+", re.IGNORECASE)
REGULATION_NAME = re.compile(
    r"\b(?:resoluci[oó]n|ley|decreto|circular)\s+\d+(?:\s+de\s+\d{4})?\b",
    re.IGNORECASE,
)


def _source_cleaner(citations: list[ReportCitation]) -> Callable[[str], str]:
    urls = {citation.source_url for citation in citations if citation.source_url}
    titles = {
        citation.title: name[0] if (name := REGULATION_NAME.search(citation.title)) else ""
        for citation in citations
        if not citation.document_id.upper().startswith("SKU-") and len(citation.title) >= 4
    }
    document_ids = {citation.document_id for citation in citations if not citation.document_id.upper().startswith("SKU-")}
    ids = "|".join(re.escape(doc_id) for doc_id in sorted(document_ids, key=len, reverse=True))
    id_re = re.compile(
        rf"\b(?:{ids})\b"
        r"(?:[ \t]*[,·;–-]?[ \t]*(?:p\.|p[aá]gs?\.?|p[aá]ginas?)\s*\d+(?:\s*[-–]\s*\d+)?)?",
        re.IGNORECASE,
    ) if ids else None

    def clean(text: str) -> str:
        original = text.strip()
        if REFERENCE_HEADING.fullmatch(plain_markdown(original).strip()):
            return ""

        def remove_source_link(match: re.Match[str]) -> str:
            label, destination = match.groups()
            destination = unquote(destination)
            if "/api/documents/" in destination or re.search(FILE_EXTENSION, destination, re.IGNORECASE) or any(
                url in destination for url in urls
            ):
                return name[0] if (name := REGULATION_NAME.search(plain_markdown(label))) else ""
            return match[0]

        text = SOURCE_LINK.sub(remove_source_link, REFERENCE_MARKER.sub("", text))
        for url in urls:
            text = text.replace(url, "")
        for title, replacement in sorted(titles.items(), key=lambda item: len(item[0]), reverse=True):
            text = re.sub(
                rf"(?<!\w){re.escape(title)}(?:{FILE_EXTENSION})?(?!\w)",
                replacement,
                text,
                flags=re.IGNORECASE,
            )
        text = FILE_REFERENCE.sub("", DOCUMENT_URL.sub("", text))
        if id_re:
            text = id_re.sub("", text)
        text = re.sub(r"\(\s*[,;·\s]*\)|\[\s*\]|<\s*>", "", text)
        text = re.sub(
            r"\b(?:seg[uú]n|de acuerdo con)\s+(?:(?:el|la)\s+)?"
            r"(?:(?:documento|archivo|informe)\s+)?\s*(?=[,:])[, :]+",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"[ \t]+([,.;:!?])", r"\1", text)
        text = text.strip()
        return "" if text != original and not re.search(r"\w", text) else text

    return clean


def _list_items(block: SyntaxTreeNode, clean: Callable[[str], str], depth: int = 0) -> Iterator[str]:
    start = int(block.attrs.get("start", 1))
    for index, item in enumerate(block.children, start=start):
        paragraphs = [clean(p.children[0].content) for p in item.children if p.type == "paragraph"]
        text = "\n".join(filter(None, paragraphs))
        if text:
            marker = f"{index}. " if block.type == "ordered_list" else ("• " if depth else "")
            yield ("  " * depth) + marker + text
        for nested in item.children:
            if nested.type in {"ordered_list", "bullet_list"}:
                yield from _list_items(nested, clean, depth + 1)


def _table(block: SyntaxTreeNode, clean: Callable[[str], str]) -> ReportTable | None:
    rows = [
        [clean(cell.children[0].content) for cell in row.children]
        for group in block.children
        for row in group.children
    ]
    if not rows:
        return None
    columns, *data = rows
    return ReportTable(columns=columns, rows=data)


def report_sections(
    answer: str, citations: list[ReportCitation] | None = None,
) -> list[ReportSection]:
    """Convierte la respuesta en bloques imprimibles en su orden original."""
    answer = answer.removesuffix(f"\n\n{REPORT_UNAVAILABLE}")
    if citations:
        answer = unwrap_markdown(answer)
    if not citations and "\t" in answer and (rows := spreadsheet_rows(answer)):
        columns, *data = [[escape_inline(cell) for cell in row] for row in rows]
        return [ReportSection(table=ReportTable(columns=columns, rows=data))]

    def unchanged(text: str) -> str:
        return text

    clean = _source_cleaner(citations) if citations else unchanged
    sections: list[ReportSection] = []
    section = ReportSection()
    source_level: int | None = None

    def flush() -> None:
        nonlocal section
        if section.heading or section.body or section.bullets or section.table:
            sections.append(section)
        section = ReportSection()

    for block in markdown_tree(answer).children:
        if block.type == "heading":
            level = int(block.tag[1:])
            if source_level is not None and level > source_level:
                continue
            heading = plain_markdown(block.children[0].content).strip()
            if citations and REFERENCE_HEADING.fullmatch(heading):
                source_level = level
                continue
            source_level = None
            flush()
            section.heading = clean(heading)[:200]
        elif source_level is not None:
            continue
        elif block.type == "paragraph":
            lines = block.children[0].content.splitlines()
            if citations and lines and REFERENCE_HEADING.fullmatch(plain_markdown(lines[0]).strip()):
                source_level = 6
                continue
            paragraph = clean("\n".join(
                line for line in lines if not (citations and REFERENCE_HEADING.fullmatch(plain_markdown(line).strip()))
            ))
            if plain_markdown(paragraph).strip():
                if section.bullets or section.table:
                    flush()
                section.body.append(paragraph)
        elif block.type in {"bullet_list", "ordered_list"}:
            if section.table or (block.type == "ordered_list" and section.bullets):
                flush()
            items = list(_list_items(block, clean))
            (section.bullets if block.type == "bullet_list" else section.body).extend(items)
        elif block.type == "table":
            if section.table:
                flush()
            section.table = _table(block, clean)
        elif block.type in {"fence", "code_block", "blockquote"}:
            if section.bullets or section.table:
                flush()
            if block.type == "blockquote":
                section.body.extend(
                    text for node in block.walk() if node.type == "inline" and (text := clean(node.content))
                )
            else:
                # Escapar delimitadores para conservar el contenido literal al escribir los archivos.
                literal = escape_inline(clean(block.content))
                if literal:
                    section.body.append(literal)
    flush()
    return sections
