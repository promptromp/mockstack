"""OpenTelemetry integration."""

from importlib import metadata
from typing import List, Tuple

from fastapi import FastAPI, Request
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span
from starlette.responses import StreamingResponse, Response

from mockstack.config import Settings


def span_name_for(request: Request) -> str:
    """Get the span name for a request."""
    return f"{request.method.upper()} {request.url.path}"


def with_request_attributes(
    request: Request, span: Span, *, sensitive_headers: List[str] = []
) -> Span:
    """Add request attributes to the span."""
    span.set_attribute("http.method", request.method)
    span.set_attribute("http.url", str(request.url))
    span.set_attribute("http.scheme", request.url.scheme)
    if request.url.hostname:
        span.set_attribute("http.host", request.url.hostname)
    span.set_attribute("http.target", request.url.path)
    if request.url.port:
        span.set_attribute("http.server_port", request.url.port)

    # Client information
    if request.client:
        span.set_attribute("net.peer.ip", request.client.host)
        if request.client.port:
            span.set_attribute("net.peer.port", request.client.port)

    # Request headers (excluding sensitive headers)
    for header_name, header_value in request.headers.items():
        if header_name.lower() not in sensitive_headers:
            span.set_attribute(
                f"http.request.header.{header_name.lower()}", header_value
            )

    # Query parameters
    if request.query_params:
        for param_name, param_value in request.query_params.items():
            span.set_attribute(f"http.request.query.{param_name}", param_value)

    return span


def with_response_attributes(
    response: Response, span: Span, *, sensitive_headers: List[str] = []
) -> Span:
    """Add response attributes to the span."""
    # Response attributes
    span.set_attribute("http.status_code", response.status_code)
    span.set_attribute(
        "http.response_content_length", response.headers.get("content-length", 0)
    )

    # Response headers
    for header_name, header_value in response.headers.items():
        if header_name.lower() not in sensitive_headers:
            span.set_attribute(
                f"http.response.header.{header_name.lower()}", header_value
            )

    return span


async def with_response_body(
    response: StreamingResponse, span: Span
) -> Tuple[Response, Span]:
    """Add the response body to the span."""
    body = await extract_body(response)

    # for semantics of payload attribute naming see:
    # https://github.com/open-telemetry/oteps/pull/234
    span.set_attribute("http.response.body", body)

    # recreate response with the same body since when consuming it to log it above
    # we effectively "deplete" the iterator.
    _response = Response(
        content=body,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )

    return _response, span


async def extract_body(response: StreamingResponse) -> str:
    """Extract the body of a response."""

    async def read_response_body(response: StreamingResponse) -> bytes:
        """Helper function to read response body asynchronously into memory."""
        body = b""
        async for chunk in response.body_iterator:
            if isinstance(chunk, str):
                body += chunk.encode()
            else:
                body += chunk
        return body

    body = await read_response_body(response)

    return body.decode()


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
