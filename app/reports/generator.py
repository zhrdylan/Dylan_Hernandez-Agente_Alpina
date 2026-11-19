from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import REPORTS_DIR
from app.reports.excel import render_xlsx
from app.reports.pdf import render_pdf
from app.reports.spec import ReportSpec
from app.reports.word import render_docx

VALID_REPORT_TYPES = {"pdf", "xlsx", "docx"}


class ReportGenerationError(RuntimeError):
    pass


@dataclass(slots=True)
class ReportArtifact:
    report_id: str
    report_type: str
    title: str
    filename: str
    path: Path


def generate_report(
    spec: ReportSpec,
    report_type: str,
    *,
    output_root: Path = REPORTS_DIR,
) -> ReportArtifact:
    report_type = report_type.lower().strip()
    if report_type not in VALID_REPORT_TYPES:
        raise ReportGenerationError(
            f"Tipo de reporte inválido: {report_type!r}. Usa pdf o xlsx."
        )

    report_id = str(uuid.uuid4())
    output_dir = output_root / report_id
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"informe-{report_id}.{report_type}"
    path = output_dir / filename

    if report_type == "pdf":
        render_pdf(spec, path)
    elif report_type == "docx":
        render_docx(spec, path)
    else:
        render_xlsx(spec, path)

    if not path.is_file() or path.stat().st_size == 0:
        raise ReportGenerationError("El archivo de reporte no se generó correctamente.")

    return ReportArtifact(
        report_id=report_id,
        report_type=report_type,
        title=spec.title,
        filename=filename,
        path=path,
    )
