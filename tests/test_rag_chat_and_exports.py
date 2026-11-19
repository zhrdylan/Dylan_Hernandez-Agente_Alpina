from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agent import graph, prompts
from app.agent.llm import LlmError, parse_json_content
from app.agent.validation import validate_answer_payload


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
    monkeypatch.setattr(graph, "create_report_record", generate)
    app = graph.build_graph(InMemorySaver(), retrieve_fn=retrieve)
    chat_id = str(uuid4())
    session_id = str(uuid4())

    initial = graph.ask(app, "Quiero un PDF", chat_id, session_id=session_id)
    assert initial["answer"] == prompts.REPORT_TOPIC_REQUEST
    assert not initial["generated_report"]
    report = graph.ask(app, QUESTION, chat_id, session_id=session_id)
    assert report["verified"] and report["generated_report"]["report_type"] == "pdf"

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
