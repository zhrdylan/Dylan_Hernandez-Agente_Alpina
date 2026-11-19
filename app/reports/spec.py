from __future__ import annotations

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
    columns: list[str] = Field(min_length=1, max_length=12)
    rows: list[list[str]] = Field(default_factory=list, max_length=200)
    notes: str = Field(default="", max_length=1000)


class ReportSection(BaseModel):
    heading: str = Field(min_length=1, max_length=200)
    body: list[str] = Field(default_factory=list, max_length=50)
    bullets: list[str] = Field(default_factory=list, max_length=50)
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
    sections: list[ReportSection] = Field(default_factory=list, max_length=20)
    citations: list[ReportCitation] = Field(default_factory=list, max_length=100)
    footer: str = Field(
        default=(
            "Documento generado por el Agente Documental de Alpina. "
            "Información trazable y sujeta a verificación documental."
        ),
        max_length=500,
    )
