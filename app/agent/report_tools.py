from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from app.agent.progress import record_progress
from app.agent.prompts import REPORT_UNAVAILABLE
from app.reports.service import create_report_record

logger = logging.getLogger(__name__)


def _generate(runtime: ToolRuntime, report_type: str) -> tuple[str, dict[str, Any]]:
    state = runtime.state
    request = state.get("report_request") or {}
    supplied = bool(request.get("content"))
    if request.get("report_type") != report_type or state.get("abstained") or not (state.get("verified") or supplied):
        raise ValueError("El turno no está habilitado para generar este informe.")

    record_progress(state.get("chat_id", ""), "report", "running")
    previous = state.get("last_verified") or {}
    report = create_report_record(
        chat_id=state.get("chat_id") or "",
        session_id=state.get("session_id"),
        question=request.get("topic") or previous.get("question") or "",
        answer=state["answer"],
        citations=state.get("citations") or [],
        report_type=report_type,
        verification_status="Datos del usuario" if supplied else "Citas OK",
        category=state.get("category") or "",
        user_provided=supplied,
    )
    return "Archivo disponible.", report


@tool(response_format="content_and_artifact")
def generar_pdf(runtime: ToolRuntime) -> tuple[str, dict[str, Any]]:
    """Genera un PDF descargable con el informe preparado para el turno."""
    return _generate(runtime, "pdf")


@tool(response_format="content_and_artifact")
def generar_word(runtime: ToolRuntime) -> tuple[str, dict[str, Any]]:
    """Genera un documento Word editable con el informe preparado para el turno."""
    return _generate(runtime, "docx")


@tool(response_format="content_and_artifact")
def generar_excel(runtime: ToolRuntime) -> tuple[str, dict[str, Any]]:
    """Genera un libro Excel con los datos y secciones preparados para el turno."""
    return _generate(runtime, "xlsx")


REPORT_TOOLS = {"pdf": generar_pdf, "docx": generar_word, "xlsx": generar_excel}


def handle_report_error(error: Exception) -> str:
    logger.error("Fallo al ejecutar la herramienta de informes", exc_info=error)
    return REPORT_UNAVAILABLE
