"""OpenTelemetry tracing: the tracer provider, its OTLP exporter and a span per request.

This module needs the optional ``opentelemetry`` extra, so only
``mockstack.telemetry.opentelemetry_provider`` imports it, when tracing is enabled.
"""

from importlib import metadata
from typing import cast

from fastapi import FastAPI, Request
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response, StreamingResponse

from mockstack.config import Settings
from mockstack.constants import SENSITIVE_HEADERS


def span_name_for(request: Request) -> str:
    """Get the span name for a request."""
    return f"{request.method.upper()} {request.url.path}"


def with_request_attributes(request: Request, span: Span, *, sensitive_headers: list[str] | None = None) -> Span:
    """Add request attributes to the span."""
    sensitive_headers = sensitive_headers or []
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
            span.set_attribute(f"http.request.header.{header_name.lower()}", header_value)

    # Query parameters
    if request.query_params:
        for param_name, param_value in request.query_params.items():
            span.set_attribute(f"http.request.query.{param_name}", param_value)

    return span


def with_response_attributes(response: Response, span: Span, *, sensitive_headers: list[str] | None = None) -> Span:
    """Add response attributes to the span."""
    sensitive_headers = sensitive_headers or []
    # Response attributes
    span.set_attribute("http.status_code", response.status_code)
    span.set_attribute("http.response_content_length", response.headers.get("content-length", 0))

    # Response headers
    for header_name, header_value in response.headers.items():
        if header_name.lower() not in sensitive_headers:
            span.set_attribute(f"http.response.header.{header_name.lower()}", header_value)

    return span


async def with_response_body(response: StreamingResponse, span: Span) -> tuple[Response, Span]:
    """Add the response body to the span.

    A body that is not UTF-8, such as an image, is recorded as ``<N bytes, not UTF-8>``.
    The response is rebuilt from the original bytes and headers either way.
    """
    body = await extract_body(response)

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = f"<{len(body)} bytes, not UTF-8>"

    # for semantics of payload attribute naming see:
    # https://github.com/open-telemetry/oteps/pull/234
    span.set_attribute("http.response.body", text)

    # recreate response with the same body since when consuming it to log it above
    # we effectively "deplete" the iterator.
    _response = Response(content=body, status_code=response.status_code)
    # Send the original headers item by item: a mapping would keep only one of several
    # Set-Cookie headers. An original Content-Length already describes these bytes (or,
    # for a HEAD, the body a GET would send); without one, keep the one Starlette just
    # set for them, if any (none on a 1xx, 204 or 304).
    original = list(response.raw_headers)
    has_length = any(name.lower() == b"content-length" for name, _ in original)
    _response.raw_headers = original if has_length else original + _response.raw_headers

    return _response, span


async def extract_body(response: StreamingResponse) -> bytes:
    """Read the body of a response into memory, as the bytes sent."""
    body = b""
    async for chunk in response.body_iterator:
        if isinstance(chunk, str):
            body += chunk.encode()
        else:
            body += chunk
    return body


def install(app: FastAPI, settings: Settings) -> None:
    """Export ``app``'s traces to the configured OTLP endpoint, with a span per request."""
    distribution = metadata.distribution("mockstack")
    resource = Resource(
        attributes={
            "service.name": distribution.name,
            "service.version": distribution.version,
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(tracer_provider)

    otlp_exporter = OTLPSpanExporter(endpoint=settings.opentelemetry.endpoint)
    tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

    # Added after ``middleware_provider``'s middlewares, so the span covers them too.
    @app.middleware("http")
    async def instrument_opentelemetry(request: Request, call_next: RequestResponseEndpoint) -> Response:
        tracer = trace.get_tracer(__name__)
        # With FastAPI's built-in tracing on, the span is a child of FastAPI's request span,
        # the current one, which has continued the caller's trace already. Otherwise the
        # span continues the caller's trace itself, from the headers alone: a span that is
        # merely current, such as an in-process caller's, does not decide the trace.
        ctx = None if settings.opentelemetry.fastapi_tracing else extract(request.headers)
        with tracer.start_as_current_span(span_name_for(request), context=ctx) as span:
            span = with_request_attributes(request, span, sensitive_headers=SENSITIVE_HEADERS)

            # Strategies add their own attributes to this span (``telemetry.current_span``).
            request.state.span = span

            response = await call_next(request)

            span = with_response_attributes(response, span, sensitive_headers=SENSITIVE_HEADERS)

            if settings.opentelemetry.capture_response_body:
                # call_next answers with Starlette's streaming response, whose body is an
                # async iterator just like StreamingResponse's.
                response, span = await with_response_body(cast(StreamingResponse, response), span)

            return response
