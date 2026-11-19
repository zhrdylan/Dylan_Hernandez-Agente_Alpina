from __future__ import annotations

import io
from collections import Counter
from typing import Any, Iterable, Sequence

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

BLUE = "#0152D1"
BLUE_DARK = "#013FA8"
BLUE_LIGHT = "#EAF1FB"
RED = "#E30613"
GREEN = "#0A7D4F"
AMBER = "#B45309"
INK = "#0F223D"
MUTED = "#64748B"
GRID = "#E2E8F0"
PALETTE = [BLUE, GREEN, AMBER, RED, "#7C3AED", "#0891B2", "#DB2777"]

PNG_DPI = 200


def _figure(width: float = 7.2, height: float = 3.4) -> Figure:
    return Figure(figsize=(width, height), dpi=PNG_DPI, facecolor="white")


def _save(figure: Figure) -> bytes:
    buffer = io.BytesIO()
    figure.savefig(
        buffer,
        format="png",
        dpi=PNG_DPI,
        bbox_inches="tight",
        facecolor="white",
        edgecolor="none",
    )
    return buffer.getvalue()


def _style_axis(axis) -> None:
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_color(GRID)
    axis.spines["bottom"].set_color(GRID)
    axis.tick_params(colors=MUTED, labelsize=8)
    axis.grid(axis="y", color=GRID, linewidth=0.7, alpha=0.9)
    axis.set_axisbelow(True)


def _empty_chart(title: str, message: str = "Sin datos para graficar") -> bytes:
    figure = _figure(7.2, 2.4)
    axis = figure.add_subplot(1, 1, 1)
    axis.axis("off")
    axis.text(
        0.5,
        0.62,
        title,
        ha="center",
        va="center",
        fontsize=12,
        fontweight="bold",
        color=INK,
        transform=axis.transAxes,
    )
    axis.text(
        0.5,
        0.38,
        message,
        ha="center",
        va="center",
        fontsize=10,
        color=MUTED,
        transform=axis.transAxes,
    )
    canvas = FigureCanvasAgg(figure)
    canvas.draw()
    return _save(figure)


def _shorten(value: str, limit: int = 24) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def bar_chart_png(
    labels: Sequence[str],
    values: Sequence[float],
    title: str,
    *,
    ylabel: str | None = None,
    horizontal: bool = False,
    colors: Sequence[str] | None = None,
) -> bytes:
    pairs = [
        (str(label), float(value))
        for label, value in zip(labels, values)
        if value is not None
    ]
    if not pairs:
        return _empty_chart(title)

    labels = [_shorten(label) for label, _ in pairs]
    values = [value for _, value in pairs]
    palette = list(colors or [BLUE] * len(values))

    figure = _figure(7.4, max(2.8, 0.42 * len(values) + 1.8))
    axis = figure.add_subplot(1, 1, 1)
    _style_axis(axis)

    if horizontal:
        bars = axis.barh(labels[::-1], values[::-1], color=palette[::-1], height=0.62)
        axis.bar_label(
            bars,
            labels=[f"{value:,.0f}".replace(",", ".") for value in values[::-1]],
            padding=4,
            fontsize=8,
            color=INK,
        )
        axis.grid(axis="x", color=GRID, linewidth=0.7, alpha=0.9)
        axis.grid(axis="y", visible=False)
    else:
        bars = axis.bar(labels, values, color=palette, width=0.62)
        axis.bar_label(
            bars,
            labels=[f"{value:,.0f}".replace(",", ".") for value in values],
            padding=3,
            fontsize=8,
            color=INK,
        )

    if title:
        axis.set_title(
            title,
            loc="left",
            fontsize=12,
            fontweight="bold",
            color=INK,
            pad=12,
        )
    if ylabel:
        axis.set_ylabel(ylabel, fontsize=8.5, color=MUTED)
    axis.yaxis.set_major_locator(MaxNLocator(integer=True))
    axis.tick_params(axis="x", rotation=0 if horizontal else 18)
    return _save(figure)


def donut_chart_png(
    labels: Sequence[str],
    values: Sequence[float],
    title: str,
    *,
    colors: Sequence[str] | None = None,
) -> bytes:
    pairs = [
        (str(label), float(value))
        for label, value in zip(labels, values)
        if value is not None and float(value) > 0
    ]
    if not pairs:
        return _empty_chart(title)

    labels = [label for label, _ in pairs]
    values = [value for _, value in pairs]
    total = sum(values)
    palette = list(colors or PALETTE[: len(values)])

    figure = _figure(5.6, 3.6)
    axis = figure.add_subplot(1, 1, 1)
    wedges, _ = axis.pie(
        values,
        colors=palette,
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.38, "edgecolor": "white", "linewidth": 1.4},
    )
    axis.text(
        0,
        0.08,
        f"{total:,.0f}".replace(",", "."),
        ha="center",
        va="center",
        fontsize=20,
        fontweight="bold",
        color=INK,
    )
    axis.text(
        0,
        -0.17,
        "registros",
        ha="center",
        va="center",
        fontsize=8.5,
        color=MUTED,
    )
    axis.legend(
        wedges,
        [f"{label} ({value:,.0f})".replace(",", ".") for label, value in zip(labels, values)],
        loc="center left",
        bbox_to_anchor=(1.0, 0.5),
        frameon=False,
        fontsize=8,
        labelcolor=INK,
    )
    if title:
        axis.set_title(
            title,
            loc="left",
            fontsize=12,
            fontweight="bold",
            color=INK,
            pad=10,
        )
    axis.set_aspect("equal")
    return _save(figure)


def citations_chart_png(
    citations: Iterable[Any],
    *,
    title: str = "Citas por documento",
) -> bytes:
    citation_list = list(citations or [])
    counts = Counter()
    for citation in citation_list:
        if isinstance(citation, dict):
            document_id = citation.get("document_id")
        else:
            document_id = getattr(citation, "document_id", None)
        if document_id:
            counts[str(document_id)] += 1

    if not counts:
        return _empty_chart(title)

    if len(counts) == 1:
        page_counts = Counter()
        for citation in citation_list:
            document_id = (
                citation.get("document_id")
                if isinstance(citation, dict)
                else getattr(citation, "document_id", None)
            )
            page = (
                citation.get("page")
                if isinstance(citation, dict)
                else getattr(citation, "page", None)
            )
            if document_id and page:
                page_counts[(str(document_id), int(page))] += 1
        ordered = sorted(
            page_counts.items(),
            key=lambda item: (-item[1], item[0][1]),
        )[:10]
        labels = [f"{document} p.{page}" for (document, page), _ in ordered]
        values = [count for _, count in ordered]
    else:
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10]
        labels = [item[0] for item in ordered]
        values = [item[1] for item in ordered]

    return bar_chart_png(
        labels,
        values,
        title,
        ylabel="Citas",
        horizontal=len(labels) > 4,
        colors=[BLUE] * len(labels),
    )


def verification_chart_png(
    status: str,
    citations_count: int = 0,
    *,
    title: str = "Estado de verificación",
) -> bytes:
    normalized = (status or "Sin verificar").strip()
    color = GREEN if normalized.lower() in {"verificado", "citas ok", "citas validadas"} else AMBER
    return donut_chart_png(
        [normalized],
        [max(1, int(citations_count or 1))],
        title,
        colors=[color],
    )


def financial_performance_chart_png(
    labels: list[str] | None = None,
    values: list[float] | None = None,
    title: str = "Desempeño Financiero",
) -> bytes | None:
    """Gráfico de barras de desempeño financiero sustentado en datos reales del turno (R03)."""
    if not labels or not values or len(labels) != len(values):
        return None
    bar_colors = [BLUE, "#64748B", GREEN, "#0891B2", "#0284C7", "#10B981"] * 3

    figure = _figure(7.8, 3.6)
    axis = figure.add_subplot(1, 1, 1)
    _style_axis(axis)

    bars = axis.bar(labels, values, color=bar_colors, width=0.55, edgecolor="none", zorder=3)
    axis.set_title(title, loc="left", fontsize=11, fontweight="bold", color=INK, pad=12)
    axis.set_ylabel("Miles de Millones COP ($)", fontsize=8.5, color=MUTED)
    axis.tick_params(axis="x", labelsize=8, rotation=12)

    for bar, val in zip(bars, values):
        height = bar.get_height()
        axis.annotate(
            f"${val:,.0f} B".replace(",", "."),
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
            fontweight="bold",
            color=INK,
        )

    figure.tight_layout()
    canvas = FigureCanvasAgg(figure)
    canvas.draw()
    return _save(figure)

