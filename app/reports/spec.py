from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from pydantic import BaseModel, Field


class ReportCitation(BaseModel):
    document_id: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=300)
    page: int = Field(ge=1)
    version: str = Field(default="", max_length=80)
    quote: str = Field(default="", max_length=2000)
    source_url: str | None = Field(default=None, max_length=1000)


class ReportTable(BaseModel):
    title: str = Field(default="", max_length=200)
    columns: list[str] = Field(min_length=1)
    rows: list[list[str]] = Field(default_factory=list)
    notes: str = Field(default="", max_length=1000)

    def iter_rows(self) -> Iterator[list[str]]:
        """Entrega filas alineadas con las columnas declaradas."""
        width = len(self.columns)
        for row in self.rows:
            yield row[:width] + [""] * max(0, width - len(row))

    def printable_parts(self) -> Iterator[ReportTable]:
        columns_per_page = 8
        if len(self.columns) <= columns_per_page:
            yield self
            return

        for start in range(1, len(self.columns), columns_per_page - 1):
            columns = [0, *range(start, min(start + columns_per_page - 1, len(self.columns)))]
            yield self.model_copy(update={
                "columns": [self.columns[i] for i in columns],
                "rows": [[row[i] if i < len(row) else "" for i in columns] for row in self.rows],
                "notes": self.notes if columns[-1] == len(self.columns) - 1 else "",
            })


class ReportSection(BaseModel):
    heading: str = Field(default="", max_length=200)
    body: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)
    table: ReportTable | None = None


class ReportSpec(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    subtitle: str = Field(default="", max_length=300)
    prepared_for: str = Field(default="Alpina", max_length=200)
    query: str = Field(default="", max_length=4000)
    verification_status: str = Field(default="", max_length=80)
    abstained: bool = False
    report_date: date = Field(default_factory=date.today)
    summary: str = Field(default="", max_length=5000)
    sections: list[ReportSection] = Field(default_factory=list)
    citations: list[ReportCitation] = Field(default_factory=list, max_length=100)
    footer: str = Field(
        default="Generado por el Agente de Alpina.",
        max_length=500,
    )
