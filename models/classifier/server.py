"""Serves the B2 dispute-type classifier (scikit-learn) over HTTP.

The model is not in the image: an init container downloads a published version from the model store
into MODEL_DIR (see fetch_model.py). The model file is a joblib pickle, and pickles can run code when
loaded, so the server checks the file's SHA-256 against metadata.json before loading it, and refuses a
framework this image can't run. Either way it stays "not ready" instead of serving.

  POST /v1/classify  {"texts": ["..."]}  →  {"predictions": [{"label": ..., "confidence": ...}], "model": {...}}
  GET  /healthz      process is alive
  GET  /readyz       model loaded and verified
"""

import hashlib
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import joblib
from fastapi import FastAPI, HTTPException, Response
from prometheus_client import Counter, Histogram, CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/model"))
# This image has scikit-learn only. A PyTorch champion needs an image with PyTorch (P5: a KServe runtime per framework).
SUPPORTED_FRAMEWORKS = {"scikit-learn"}

PREDICTIONS = Counter("classifier_predictions_total", "Predictions made, by label", ["label"])
LATENCY = Histogram("classifier_request_seconds", "Time to classify one request")


class ModelError(RuntimeError):
    pass


def load_verified(model_dir):
    """Loads model.joblib only if its checksum matches metadata.json and this image supports its framework."""
    metadata = json.loads((model_dir / "metadata.json").read_text(encoding="utf-8"))
    framework = metadata.get("framework", "scikit-learn")   # B2 models predate the field; they are scikit-learn
    if framework not in SUPPORTED_FRAMEWORKS:
        raise ModelError(f"framework {framework!r} is not supported by this image (supports {sorted(SUPPORTED_FRAMEWORKS)})")
    model_file = model_dir / "model.joblib"
    actual = hashlib.sha256(model_file.read_bytes()).hexdigest()
    if actual != metadata["file_sha256"]:
        raise ModelError(f"checksum mismatch for {model_file}: expected {metadata['file_sha256'][:12]}…, got {actual[:12]}…")
    return joblib.load(model_file), metadata


@asynccontextmanager
async def lifespan(app):
    app.state.model, app.state.metadata, app.state.error = None, None, None
    try:
        app.state.model, app.state.metadata = load_verified(MODEL_DIR)
    except (ModelError, OSError, KeyError) as e:
        app.state.error = str(e)  # stays "not ready"; the reason shows in /readyz and the logs
        print(f"model NOT loaded: {e}", flush=True)
    yield


app = FastAPI(title="dispute classifier", lifespan=lifespan)

# Tracing (P3), only when a collector is configured. The assistant sends the trace ID with each call,
# so this service's time appears inside the same trace.
if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _provider = TracerProvider(resource=Resource.create(
        {"openinference.project.name": os.environ.get("PHOENIX_PROJECT", "dispute-assistant")}))
    _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(_provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics", exclude_spans=["receive", "send"])


@app.get("/metrics")
def metrics():
    # A plain route: a mounted metrics app answers /metrics with a redirect to /metrics/.
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class ClassifyRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=64)


@app.get("/healthz")
def healthz():
    return {"status": "alive"}


@app.get("/readyz")
def readyz():
    if app.state.model is None:
        raise HTTPException(503, detail=app.state.error or "model not loaded")
    return {"status": "ready"}


@app.post("/v1/classify")
def classify(req: ClassifyRequest):
    if app.state.model is None:
        raise HTTPException(503, detail="model not loaded")
    with LATENCY.time():
        probabilities = app.state.model.predict_proba(req.texts)
    classes = app.state.model.classes_
    predictions = []
    for row in probabilities:
        best = row.argmax()
        predictions.append({"label": str(classes[best]), "confidence": round(float(row[best]), 4)})
        PREDICTIONS.labels(str(classes[best])).inc()
    m = app.state.metadata
    return {"predictions": predictions,
            "model": {"name": m["model"], "version": m.get("registry", {}).get("version"),
                      "framework": m.get("framework", "scikit-learn"),
                      "dataset_version": m["dataset"]["version"], "code_commit": m["code_commit"]}}
