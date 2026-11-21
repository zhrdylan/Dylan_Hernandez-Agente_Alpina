from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import REPORTS_DIR
from app.reports.excel import render_xlsx
from app.reports.pdf import render_pdf
from app.reports.spec import ReportSpec
from app.reports.word import render_docx

REPORT_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
logger = logging.getLogger(__name__)


class ReportGenerationError(RuntimeError):
    pass


def report_filename(report_id: str, report_type: str) -> str:
    return f"informe-{uuid.UUID(report_id)}.{report_type}"


def report_storage_key(report_id: str, report_type: str) -> str:
    return f"reports/{uuid.UUID(report_id)}/{report_filename(report_id, report_type)}"


def local_report_path(report_id: str, report_type: str) -> Path | None:
    if report_type not in REPORT_MEDIA_TYPES:
        return None
    filename = report_filename(report_id, report_type)
    path = REPORTS_DIR.resolve() / str(uuid.UUID(report_id)) / filename
    return path if path.resolve() == path else None


@dataclass(slots=True)
class ReportArtifact:
    report_id: str
    report_type: str
    title: str
    filename: str
    path: Path

    def discard(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
            self.path.parent.rmdir()
        except OSError:
            logger.warning("No se pudo limpiar el archivo incompleto de informe %s", self.report_id)


def generate_report(
    spec: ReportSpec,
    report_type: str,
    *,
    output_root: Path = REPORTS_DIR,
) -> ReportArtifact:
    report_type = report_type.lower().strip()
    if report_type not in REPORT_MEDIA_TYPES:
        raise ReportGenerationError(
            f"Tipo de reporte inválido {report_type!r}. Usa pdf, docx o xlsx."
        )

    report_id = str(uuid.uuid4())
    output_dir = output_root / report_id
    output_dir.mkdir(parents=True)
    filename = report_filename(report_id, report_type)
    path = output_dir / filename

    artifact = ReportArtifact(
        report_id=report_id,
        report_type=report_type,
        title=spec.title,
        filename=filename,
        path=path,
    )
    try:
        if report_type == "pdf":
            render_pdf(spec, path)
        elif report_type == "docx":
            render_docx(spec, path)
        else:
            render_xlsx(spec, path)

        if not path.is_file() or path.stat().st_size == 0:
            raise ReportGenerationError("El archivo de reporte no se generó correctamente.")
    except Exception:
        artifact.discard()
        raise
    return artifact
