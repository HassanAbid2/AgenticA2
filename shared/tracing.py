"""Tracing: one trace id flows UI -> API -> graph -> MCP servers -> audit log.

OpenTelemetry spans go to a self-hosted Arize Phoenix (PHOENIX_COLLECTOR_ENDPOINT, docker compose);
OpenInference's LangChain instrumentor adds a span per graph node / LLM call with token counts, and a
MaskingExporter scrubs PII and secrets from span attributes before anything leaves the process.
Without a collector the trace id still exists (and is stored with runs, run events and audit rows).
"""

from __future__ import annotations

import logging
import os
import uuid
from contextvars import ContextVar

from shared.security import mask_pii

log = logging.getLogger("gigbid.tracing")
TRACE_ID: ContextVar[str] = ContextVar("trace_id", default="")
_tracer = None


class _MaskingExporter:
    def __init__(self, inner):
        self.inner = inner

    def export(self, spans):
        for s in spans:
            attrs = getattr(s, "_attributes", None)
            if attrs:
                try:
                    s._attributes = {k: mask_pii(v) if isinstance(v, str) else v for k, v in attrs.items()}
                except Exception:  # noqa: BLE001 - never fail export because of masking
                    pass
        return self.inner.export(spans)

    def shutdown(self):
        return self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000):
        return self.inner.force_flush(timeout_millis)


def setup_tracing(service: str):
    """Idempotent. Returns a tracer (no-op tracer when no collector is configured)."""
    global _tracer
    if _tracer is not None:
        return _tracer
    from opentelemetry import trace

    endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        res = Resource.create({"service.name": service, "openinference.project.name": os.getenv("PHOENIX_PROJECT", "gigbid")})
        provider = TracerProvider(resource=res)
        url = endpoint.rstrip("/") + ("" if endpoint.rstrip("/").endswith("/v1/traces") else "/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(_MaskingExporter(OTLPSpanExporter(endpoint=url))))
        trace.set_tracer_provider(provider)
        try:
            from openinference.instrumentation.langchain import LangChainInstrumentor

            LangChainInstrumentor().instrument(tracer_provider=provider)
        except Exception as e:  # noqa: BLE001
            log.warning("langchain instrumentation unavailable: %s", e)
    _tracer = trace.get_tracer(service)
    return _tracer


def new_trace_id() -> str:
    """Current OTel trace id if a span is active, else a fresh random id."""
    from opentelemetry import trace

    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx and ctx.trace_id else uuid.uuid4().hex


def trace_url(trace_id: str) -> str | None:
    base = os.getenv("PHOENIX_PUBLIC_URL")
    return f"{base.rstrip('/')}/redirects/traces/{trace_id}" if base and trace_id else None
