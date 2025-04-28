"""OpenTelemetry integration."""

from importlib import metadata

from fastapi import FastAPI, Request
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from mockstack.config import Settings


def span_name_for(request: Request) -> str:
    """Get the span name for a request."""
    return f"{request.method.upper()} {request.url.path}"


def opentelemetry_provider(app: FastAPI, settings: Settings) -> None:
    """Initialize OpenTelemetry for the mockstack app."""
    if not settings.opentelemetry.enabled:
        return

    # Initialize OpenTelemetry
    distribution = metadata.distribution("mockstack")
    resource = Resource(
        attributes={
            "service.name": distribution.name,
            "service.version": distribution.version,
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(tracer_provider)

    # Set up OTLP exporter
    otlp_exporter = OTLPSpanExporter(endpoint=settings.opentelemetry.endpoint)
    span_processor = BatchSpanProcessor(otlp_exporter)
    tracer_provider.add_span_processor(span_processor)

    # Nb. we do not actually use the default FastAPIInstrumentor here
    # because we use custom tracing in various places.
    # FastAPIInstrumentor.instrument_app(app)
