from __future__ import annotations

import re
from collections.abc import Iterator
from html import escape

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode


# El HTML de los mensajes se muestra en el chat. Se permiten enlaces Markdown,
# pero se desactivan HTML crudo e imágenes remotas.
_MARKDOWN = MarkdownIt("js-default", {"breaks": True}).disable("image")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_MARKDOWN_FENCE = re.compile(
    r"[ \t]*(~{3,}|\x60{3,})[ \t]*(?:markdown|md)[ \t]*\r?\n(.*?)\r?\n\1[ \t]*",
    re.IGNORECASE | re.DOTALL,
)


def unwrap_markdown(text: str) -> str:
    match = _MARKDOWN_FENCE.fullmatch(text.strip())
    return match[2] if match else text


def render_markdown(text: str) -> str:
    text = _CONTROL_CHARACTERS.sub("", text)
    if "\t" in text and (rows := spreadsheet_rows(text)):
        header = "".join(f"<th>{escape(cell)}</th>" for cell in rows[0])
        body = "".join(
            "<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>"
            for row in rows[1:]
        )
        return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"
    return _MARKDOWN.render(text)


def markdown_tree(text: str) -> SyntaxTreeNode:
    return SyntaxTreeNode(_MARKDOWN.parse(_CONTROL_CHARACTERS.sub("", text)))


def inline_runs(text: str) -> Iterator[tuple[str, set[str]]]:
    styles: list[str] = []
    for token in _MARKDOWN.parseInline(_CONTROL_CHARACTERS.sub("", text))[0].children or []:
        if token.type in {"strong_open", "em_open", "s_open"}:
            styles.append(token.tag)
        elif token.type in {"strong_close", "em_close", "s_close"}:
            styles.pop()
        elif token.type == "text":
            yield token.content, set(styles)
        elif token.type == "code_inline":
            yield token.content, {*styles, "code"}
        elif token.type in {"softbreak", "hardbreak"}:
            yield "\n", set()


def plain_markdown(text: str) -> str:
    return "".join(value for value, _ in inline_runs(text))


def escape_inline(text: str) -> str:
    return re.sub(r"([\\\x60*_~<>&\[\]])", r"\\\1", text)


def spreadsheet_rows(text: str) -> list[list[str]]:
    """Lee texto tabulado como el que se obtiene al copiar celdas de Excel."""
    rows = [[cell.strip() for cell in line.split("\t")] for line in text.splitlines() if line.strip()]
    if len(rows) < 2 or len(rows[0]) < 2 or not all(len(row) == len(rows[0]) for row in rows):
        return []
    return rows
