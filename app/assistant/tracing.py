"""OpenTelemetry tracing: one trace per request, one span per step (classify → policy → LLM).

Off unless OTEL_EXPORTER_OTLP_ENDPOINT is set (tests, and any environment without a collector).
Span attributes follow the OpenInference conventions, so Phoenix shows LLM spans with their messages
and token counts. Locally the claim and reply text go into the trace (TRACE_CONTENT=true, synthetic
data). In production they stay out until the guardrail masks personal details (P6).
"""

import json
import os

from opentelemetry import trace

TRACE_CONTENT = os.environ.get("TRACE_CONTENT", "false").lower() == "true"
tracer = trace.get_tracer("assistant")


def setup(app):
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Service name from OTEL_SERVICE_NAME; Phoenix groups traces by project.
    resource = Resource.create({"openinference.project.name": os.environ.get("PHOENIX_PROJECT", "dispute-assistant")})
    provider = TracerProvider(resource=resource)
    # Batched and sent in the background: if the collector is down, spans are dropped, requests aren't.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics,status",
                                       exclude_spans=["receive", "send"])   # ASGI internals: noise
    HTTPXClientInstrumentor().instrument()     # calls to the classifier and LLM carry the trace ID onwards


def current_trace_id():
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


def content(span, key, value):
    """Sets a text attribute only when content capture is on."""
    if TRACE_CONTENT:
        span.set_attribute(key, value)


def record_llm_call(span, model, messages, params, completion):
    span.set_attribute("openinference.span.kind", "LLM")
    span.set_attribute("llm.model_name", model)
    span.set_attribute("llm.invocation_parameters", json.dumps(params))
    usage = completion.get("usage", {})
    for key, name in (("prompt_tokens", "prompt"), ("completion_tokens", "completion"), ("total_tokens", "total")):
        if key in usage:
            span.set_attribute(f"llm.token_count.{name}", usage[key])
    for i, m in enumerate(messages):
        span.set_attribute(f"llm.input_messages.{i}.message.role", m["role"])
        content(span, f"llm.input_messages.{i}.message.content", m["content"])
    span.set_attribute("llm.output_messages.0.message.role", "assistant")
    content(span, "llm.output_messages.0.message.content", completion["choices"][0]["message"]["content"])
