"""OpenTelemetry integration."""

from importlib import metadata

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from mockstack.config import Settings


def opentelemetry_provider(app: FastAPI, settings: Settings) -> None:
    """Initialize OpenTelemetry for the fastapi app."""
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

    trace.set_tracer_provider(TracerProvider(resource=resource))

    # Set up OTLP exporter
    otlp_exporter = OTLPSpanExporter(endpoint=settings.opentelemetry.endpoint)
    span_processor = BatchSpanProcessor(otlp_exporter)
    trace.get_tracer_provider().add_span_processor(span_processor)

    # Instrument FastAPI with OpenTelemetry
    FastAPIInstrumentor.instrument_app(app)
