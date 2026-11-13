"""Dispute assistant: claim → dispute type (classifier) → policy → drafted reply (LLM).

The LLM is reached through an OpenAI-compatible API (/v1/chat/completions), so the same code works
with llama.cpp on a laptop, vLLM on a GPU, or a managed model behind a gateway. Only LLM_URL changes.

  POST /assist   {"text": "..."}
  GET  /healthz  process is alive (liveness)
  GET  /readyz   prompt and policies loaded (readiness): deliberately NOT the downstream services
  GET  /status   downstream health, for people and dashboards
  GET  /metrics  Prometheus metrics
"""

import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import Counter, Histogram, CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

APP_DIR = Path(os.environ.get("APP_DIR", Path(__file__).parent.parent))
CLASSIFIER_URL = os.environ.get("CLASSIFIER_URL", "http://classifier:8000")
LLM_URL = os.environ.get("LLM_URL", "http://llm:8080/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5-0.5b-instruct")
PROMPT_VERSION = os.environ.get("PROMPT_VERSION", "v1")
LLM_TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "30"))

REQUESTS = Counter("assist_requests_total", "Requests to /assist, by outcome", ["outcome"])
LATENCY = Histogram("assist_request_seconds", "End-to-end time of /assist",
                    buckets=(0.25, 0.5, 1, 2, 4, 8, 16, 32))
LLM_LATENCY = Histogram("assist_llm_seconds", "Time of the LLM call alone",
                        buckets=(0.25, 0.5, 1, 2, 4, 8, 16, 32))
TOKENS = Counter("assist_llm_tokens_total", "LLM tokens, by direction", ["direction"])
DISPUTE_TYPES = Counter("assist_dispute_type_total", "Classified dispute types", ["dispute_type"])


def load_prompt(version):
    return yaml.safe_load((APP_DIR / "prompts" / "draft_reply" / f"{version}.yaml").read_text(encoding="utf-8"))


def load_policies():
    return yaml.safe_load((APP_DIR / "policies.yaml").read_text(encoding="utf-8"))


@asynccontextmanager
async def lifespan(app):
    app.state.prompt = load_prompt(PROMPT_VERSION)
    app.state.policies = load_policies()
    # Tests replace this client with one backed by a fake transport.
    if not hasattr(app.state, "http"):
        app.state.http = httpx.AsyncClient()
    yield
    await app.state.http.aclose()


app = FastAPI(title="dispute assistant", lifespan=lifespan)


@app.get("/metrics")
def metrics():
    # A plain route: a mounted metrics app answers /metrics with a redirect to /metrics/.
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class AssistRequest(BaseModel):
    text: str = Field(min_length=5, max_length=2000)


@app.get("/healthz")
def healthz():
    return {"status": "alive"}


@app.get("/readyz")
def readyz(request: Request):
    # Only this pod's own readiness. If it also checked the LLM, one slow LLM would mark every
    # assistant pod unready and Kubernetes would remove them all from service (a cascading outage).
    state = request.app.state
    if not getattr(state, "prompt", None) or not getattr(state, "policies", None):
        raise HTTPException(503, "prompt or policies not loaded")
    return {"status": "ready", "prompt_version": state.prompt["version"]}


@app.get("/status")
async def status(request: Request):
    http = request.app.state.http
    result = {}
    for name, url in {"classifier": f"{CLASSIFIER_URL}/readyz", "llm": f"{LLM_URL.removesuffix('/v1')}/health"}.items():
        try:
            r = await http.get(url, timeout=2)
            result[name] = "up" if r.status_code == 200 else f"down ({r.status_code})"
        except httpx.HTTPError as e:
            result[name] = f"down ({type(e).__name__})"
    return result


@app.post("/assist")
async def assist(body: AssistRequest, request: Request):
    state = request.app.state
    start = time.perf_counter()
    try:
        # 1. Dispute type from the classic model
        r = await state.http.post(f"{CLASSIFIER_URL}/v1/classify", json={"texts": [body.text]}, timeout=5)
        r.raise_for_status()
        prediction = r.json()["predictions"][0]
        dispute_type = prediction["label"]
        DISPUTE_TYPES.labels(dispute_type).inc()

        # 2. Policy for that type, 3. prompt from the versioned template
        prompt = state.prompt
        messages = [
            {"role": "system", "content": prompt["system"]},
            {"role": "user", "content": prompt["user"].format(
                claim=body.text, dispute_type=dispute_type, policy=state.policies[dispute_type])},
        ]

        # 4. Draft from the LLM (OpenAI-compatible chat completions)
        llm_start = time.perf_counter()
        r = await state.http.post(f"{LLM_URL}/chat/completions", timeout=LLM_TIMEOUT_S, json={
            "model": LLM_MODEL, "messages": messages, **prompt["params"]})
        r.raise_for_status()
        llm_seconds = time.perf_counter() - llm_start
        LLM_LATENCY.observe(llm_seconds)
        completion = r.json()
        usage = completion.get("usage", {})
        TOKENS.labels("prompt").inc(usage.get("prompt_tokens", 0))
        TOKENS.labels("completion").inc(usage.get("completion_tokens", 0))
    except httpx.TimeoutException:
        REQUESTS.labels("timeout").inc()
        raise HTTPException(504, "a downstream service timed out")
    except (httpx.HTTPError, KeyError, IndexError) as e:
        REQUESTS.labels("error").inc()
        raise HTTPException(502, f"downstream error: {type(e).__name__}")

    total = time.perf_counter() - start
    LATENCY.observe(total)
    REQUESTS.labels("ok").inc()
    return {
        "dispute_type": dispute_type,
        "confidence": prediction["confidence"],
        "draft_reply": completion["choices"][0]["message"]["content"].strip(),
        # Lineage: which prompt and model produced this answer.
        "prompt_version": f"{prompt['name']}/{prompt['version']}",
        "llm_model": completion.get("model", LLM_MODEL),
        "tokens": {"prompt": usage.get("prompt_tokens"), "completion": usage.get("completion_tokens")},
        "timings_ms": {"total": round(total * 1000), "llm": round(llm_seconds * 1000)},
    }
