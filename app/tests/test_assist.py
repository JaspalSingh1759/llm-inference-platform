"""Tests the request path with fake classifier and LLM responses (no cluster or model needed)."""

import httpx
import pytest
from fastapi.testclient import TestClient

from assistant import main


def fake_backends(llm_status=200, llm_timeout=False):
    seen = {}

    def handler(request):
        if request.url.path == "/v1/classify":
            return httpx.Response(200, json={"predictions": [{"label": "duplicate_charge", "confidence": 0.97}]})
        if request.url.path == "/v1/chat/completions":
            if llm_timeout:
                raise httpx.ReadTimeout("slow model", request=request)
            seen["llm_body"] = request.read().decode()
            return httpx.Response(llm_status, json={
                "model": "qwen2.5-0.5b-instruct",
                "choices": [{"message": {"content": " We will place a temporary credit... "}}],
                "usage": {"prompt_tokens": 180, "completion_tokens": 40}})
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


@pytest.fixture
def client():
    def make(**kwargs):
        http, seen = fake_backends(**kwargs)
        main.app.state.http = http
        return TestClient(main.app), seen
    yield make
    del main.app.state.http


def test_assist_returns_type_draft_and_lineage(client):
    c, seen = client()
    with c:
        r = c.post("/assist", json={"text": "I was charged twice at BestElectro for $49.99"})
    assert r.status_code == 200
    body = r.json()
    assert body["dispute_type"] == "duplicate_charge"
    assert body["draft_reply"] == "We will place a temporary credit..."
    assert body["prompt_version"] == "draft_reply/v1"
    assert body["tokens"] == {"prompt": 180, "completion": 40}
    # The policy for the predicted type was put into the prompt.
    assert "temporary credit for the" in seen["llm_body"]


def test_llm_timeout_returns_504(client):
    c, _ = client(llm_timeout=True)
    with c:
        assert c.post("/assist", json={"text": "I was charged twice"}).status_code == 504


def test_llm_error_returns_502(client):
    c, _ = client(llm_status=500)
    with c:
        assert c.post("/assist", json={"text": "I was charged twice"}).status_code == 502


def test_readyz_does_not_depend_on_downstreams(client):
    c, _ = client(llm_status=500)
    with c:
        assert c.get("/readyz").status_code == 200


def test_rejects_too_short_text(client):
    c, _ = client()
    with c:
        assert c.post("/assist", json={"text": "hi"}).status_code == 422
