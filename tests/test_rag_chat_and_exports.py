from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent import graph, prompts, report_tools
from app.agent.llm import LlmError, parse_json_content
from app.agent.validation import validate_answer_payload
from app.core.markdown import render_markdown


QUESTION = "¿Qué dice la política de calidad sobre inocuidad?"
EVIDENCE = {
    "document_id": "N11",
    "document_title": "Política de calidad ficticia",
    "page_start": 1,
    "page_end": 1,
    "version": "prueba",
    "content": "La política establece una inspección mensual.",
}
PAYLOAD = {
    "answer": EVIDENCE["content"],
    "citations": [{"document_id": "N11", "page": 1, "quote": "una inspección mensual"}],
    "abstained": False,
}


def test_truncated_model_json_cannot_be_parsed_as_a_citation():
    with pytest.raises(LlmError):
        parse_json_content('{"answer": "Un hallazgo", "citations": [{"document_id": "N11"}')


def test_fragment_references_use_server_metadata_and_omit_an_inexact_quote():
    payload = {**PAYLOAD, "citations": [{"source": 1, "quote": "inspección que se hace mensualmente"}]}
    result = validate_answer_payload(payload, [EVIDENCE])
    assert not result["abstained"]
    assert result["citations"][0]["document_id"] == "N11"
    assert result["citations"][0]["page"] == 1
    assert result["citations"][0]["quote"] == ""

    payload["citations"] = [{"source": 2, "quote": ""}]
    assert validate_answer_payload(payload, [EVIDENCE])["abstained"]


def test_chat_distinguishes_model_failure_from_missing_evidence(monkeypatch):
    def provider_error(*args, **kwargs):
        raise LlmError("Groq: 429")

    monkeypatch.setattr(graph, "chat_json", provider_error)
    with_evidence = graph.build_graph(InMemorySaver(), retrieve_fn=lambda *_: [EVIDENCE])
    without_evidence = graph.build_graph(InMemorySaver(), retrieve_fn=lambda *_: [])

    failed = graph.ask(with_evidence, QUESTION, str(uuid4()))
    no_evidence = graph.ask(without_evidence, QUESTION, str(uuid4()))
    assert failed["answer"] == prompts.ANSWER_UNAVAILABLE
    assert no_evidence["answer"] == prompts.ABSTENTION
    assert all(result["abstained"] and not result["verified"] for result in (failed, no_evidence))


def test_chat_distinguishes_retrieval_failure_from_missing_evidence():
    def fail_retrieval(*args):
        raise RuntimeError("Error de prueba en recuperación")

    app = graph.build_graph(InMemorySaver(), retrieve_fn=fail_retrieval)
    result = graph.ask(app, QUESTION, str(uuid4()))
    assert result["answer"] == prompts.RETRIEVAL_UNAVAILABLE
    assert result["abstained"] and not result["verified"]


def test_out_of_scope_keeps_accumulated_issues(monkeypatch):
    monkeypatch.setattr(graph, "chat_json", lambda *args, **kwargs: {"category": "out_of_scope"})
    result = graph.supervisor_node({
        "messages": [HumanMessage(content="¿Cuándo lloverá en Bogotá?")],
        "issues": ["Observación anterior"],
    })
    assert result["category"] == "guardrail"
    assert result["issues"] == ["Observación anterior", "Solicitud fuera del alcance documental."]


def test_report_without_tool_messages_returns_a_recoverable_answer():
    result = graph.finish_report_node({"answer": "Contenido para el informe", "report_tool_messages": []})
    assert result["generated_report"] is None
    assert result["report_tool"] is None
    assert prompts.REPORT_UNAVAILABLE in result["answer"]


def test_report_follows_requested_topic_and_reuses_cited_answer(monkeypatch):
    retrieval_calls = []
    reports = []

    def retrieve(query, filters):
        retrieval_calls.append(query)
        return [EVIDENCE]

    def generate(**kwargs):
        reports.append(kwargs)
        return {"report_type": kwargs["report_type"]}

    monkeypatch.setattr(graph, "chat_json", lambda *args, **kwargs: PAYLOAD)
    monkeypatch.setattr(report_tools, "create_report_record", generate)
    app = graph.build_graph(InMemorySaver(), retrieve_fn=retrieve)
    chat_id = str(uuid4())
    session_id = str(uuid4())

    initial = graph.ask(app, "Quiero un PDF", chat_id, session_id=session_id)
    assert initial["answer"] == prompts.REPORT_TOPIC_REQUEST
    assert not initial["generated_report"]
    report = graph.ask(app, QUESTION, chat_id, session_id=session_id)
    assert report["verified"] and report["generated_report"]["report_type"] == "pdf"
    assert report["report_tool"] == "generar_pdf"

    for request, fmt in [("Pásamelo a Word", "docx"), ("Dame la respuesta en Excel", "xlsx")]:
        exported = graph.ask(app, request, chat_id, session_id=session_id)
        assert exported["generated_report"]["report_type"] == fmt
        assert exported["citations"] == report["citations"]

    declined = graph.ask(app, "Quiero un Word con código en Python", chat_id, session_id=session_id)
    assert declined["category"] == "guardrail"
    assert not declined["generated_report"]
    assert retrieval_calls == [QUESTION]
    assert len(reports) == 3
    assert all(item["question"] == QUESTION and item["session_id"] == session_id for item in reports)


def test_chat_markdown_preserves_prose_lists_and_tables():
    html = render_markdown(
        "## Resultados\nPárrafo inicial.\n\n"
        "3. Primer paso\n   - Paso secundario\n\n"
        "Producto | Cantidad\n--- | ---:\nAvena \\| Alpina | **12**\n\n"
        "> Nota *relevante*.\n\n"
        "<em>Texto literal</em>\n\n"
        "~~~text\nlínea uno\n\nlínea tres\n~~~"
    )
    assert "<h2>Resultados</h2>\n<p>Párrafo inicial.</p>" in html
    assert '<ol start="3">\n<li>Primer paso\n<ul>' in html
    assert "<td>Avena | Alpina</td>" in html
    assert '<td style="text-align:right"><strong>12</strong></td>' in html
    assert "<blockquote>" in html and "<em>relevante</em>" in html
    assert "&lt;em&gt;Texto literal&lt;/em&gt;" in html
    assert "línea uno\n\nlínea tres" in html


def test_detailed_report_expands_previous_question_with_broader_evidence(monkeypatch):
    retrieved = []
    model_calls = []

    def retrieve(query, filters):
        retrieved.append((query, filters.coverage))
        return [EVIDENCE] * 9

    def model(_model, _system, prompt, **options):
        model_calls.append((prompt, options))
        return {
            "answer": "~~~markdown\n## Inspecciones\n\nLa política establece una inspección mensual.\n~~~",
            "citations": [{"source": 1, "quote": "inspección mensual"}],
            "abstained": False,
        }

    monkeypatch.setattr(graph, "chat_json", model)
    monkeypatch.setattr(report_tools, "create_report_record", lambda **_: {"report_type": "docx"})
    app = graph.build_graph(InMemorySaver(), retrieve_fn=retrieve)
    chat_id = str(uuid4())
    first = graph.ask(app, QUESTION, chat_id)
    assert first["verified"] and first["report_tool"] is None
    assert first["answer"].startswith("## Inspecciones")
    assert "<h2>Inspecciones</h2>" in render_markdown(first["answer"])

    report = graph.ask(app, "Genera un informe detallado en Word de lo anterior", chat_id)
    assert report["report_tool"] == "generar_word"
    assert retrieved == [(QUESTION, False), (QUESTION, True)]
    prompt, options = model_calls[-1]
    assert "[FUENTE 9]" in prompt and QUESTION in prompt
    assert options["max_tokens"] > model_calls[0][1]["max_tokens"]
