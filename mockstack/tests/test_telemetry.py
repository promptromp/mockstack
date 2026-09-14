"""Unit tests for the telemetry module."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.responses import Response, StreamingResponse

from mockstack.config import OpenTelemetrySettings
from mockstack.telemetry import (
    extract_body,
    opentelemetry_provider,
    span_name_for,
    with_request_attributes,
    with_response_attributes,
    with_response_body,
)


def test_span_name_for(make_request):
    """Test span name generation."""
    assert span_name_for(make_request("/test/path")) == "GET /test/path"


def test_with_request_attributes(make_request):
    """Test adding request attributes to span."""
    request = make_request(
        "/test/path",
        method="POST",
        query=b"key=value&other=123",
        headers={
            "user-agent": "test-client",
            "authorization": "Bearer token",
            "content-type": "application/json",
            "host": "example.com:8443",  # Required for URL construction
        },
        scheme="https",
        client=("127.0.0.1", 12345),
        server=("example.com", 8443),
    )

    span = MagicMock()
    sensitive_headers = ["authorization"]

    with_request_attributes(request, span, sensitive_headers=sensitive_headers)

    # Verify basic request attributes
    span.set_attribute.assert_any_call("http.method", "POST")
    span.set_attribute.assert_any_call("http.url", "https://example.com:8443/test/path?key=value&other=123")
    span.set_attribute.assert_any_call("http.scheme", "https")
    span.set_attribute.assert_any_call("http.host", "example.com")
    span.set_attribute.assert_any_call("http.target", "/test/path")
    span.set_attribute.assert_any_call("http.server_port", 8443)

    # Verify client information
    span.set_attribute.assert_any_call("net.peer.ip", "127.0.0.1")
    span.set_attribute.assert_any_call("net.peer.port", 12345)

    # Verify headers (excluding sensitive)
    span.set_attribute.assert_any_call("http.request.header.user-agent", "test-client")
    span.set_attribute.assert_any_call("http.request.header.content-type", "application/json")

    # Verify query parameters
    span.set_attribute.assert_any_call("http.request.query.key", "value")
    span.set_attribute.assert_any_call("http.request.query.other", "123")

    # Verify sensitive headers are not included
    for args in span.set_attribute.call_args_list:
        assert not any("authorization" in str(arg) for arg in args[0])


def test_with_response_attributes():
    """Test adding response attributes to span."""
    response = Response(
        content="test content",
        status_code=200,
        headers={
            "content-type": "text/plain",
            "content-length": "11",
            "x-secret": "sensitive",
        },
    )
    span = MagicMock()
    sensitive_headers = ["x-secret"]

    with_response_attributes(response, span, sensitive_headers=sensitive_headers)

    # Verify response attributes
    span.set_attribute.assert_any_call("http.status_code", 200)
    span.set_attribute.assert_any_call("http.response_content_length", "11")

    # Verify headers (excluding sensitive)
    span.set_attribute.assert_any_call("http.response.header.content-type", "text/plain")
    span.set_attribute.assert_any_call("http.response.header.content-length", "11")

    # Verify sensitive headers are not included
    for args in span.set_attribute.call_args_list:
        assert not any("x-secret" in str(arg) for arg in args[0])


@pytest.mark.asyncio
async def test_with_response_body():
    """Test adding response body to span."""
    body_content = b"test response body"
    response = StreamingResponse(
        content=iter([body_content]),
        status_code=200,
        headers={"content-type": "text/plain"},
    )
    span = MagicMock()

    new_response, _ = await with_response_body(response, span)

    # Verify response body was added to span
    span.set_attribute.assert_called_once_with("http.response.body", body_content.decode())

    # Verify new response has same properties
    assert new_response.status_code == 200
    assert new_response.headers["content-type"] == "text/plain"
    assert new_response.body == body_content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "chunks",
    [[b"part1", b"part2", b"part3"], ["part1", "part2", "part3"]],
    ids=["bytes", "str"],
)
async def test_extract_body(chunks):
    """Test extracting body from a streaming response of bytes or str chunks."""
    body = await extract_body(StreamingResponse(content=iter(chunks)))
    assert body == "part1part2part3"


def test_opentelemetry_provider_disabled(settings_filefixtures):
    """Test OpenTelemetry provider when disabled."""
    # Should not raise any errors and return None
    assert opentelemetry_provider(FastAPI(), settings_filefixtures) is None


@patch("mockstack.telemetry.OTLPSpanExporter")
@patch("mockstack.telemetry.BatchSpanProcessor")
@patch("mockstack.telemetry.TracerProvider")
@patch("mockstack.telemetry.trace")
@patch("mockstack.telemetry.metadata")
def test_opentelemetry_provider_enabled(
    mock_metadata,
    mock_trace,
    mock_tracer_provider,
    mock_batch_processor,
    mock_otlp_exporter,
    make_settings,
    templates_dir,
):
    """Test OpenTelemetry provider when enabled."""
    settings = make_settings(
        strategy="filefixtures",
        templates_dir=templates_dir,
        opentelemetry=OpenTelemetrySettings(
            enabled=True,
            endpoint="http://localhost:4317",
        ),
    )

    # Mock distribution metadata
    mock_dist = MagicMock()
    mock_dist.name = "mockstack"
    mock_dist.version = "1.0.0"
    mock_metadata.distribution.return_value = mock_dist

    # Mock provider instance
    mock_provider_instance = MagicMock()
    mock_tracer_provider.return_value = mock_provider_instance

    opentelemetry_provider(FastAPI(), settings)

    # Verify tracer provider setup
    mock_tracer_provider.assert_called_once()
    mock_trace.set_tracer_provider.assert_called_once_with(mock_provider_instance)

    # Verify exporter setup
    mock_otlp_exporter.assert_called_once_with(endpoint="http://localhost:4317")
    mock_batch_processor.assert_called_once_with(mock_otlp_exporter.return_value)
    mock_provider_instance.add_span_processor.assert_called_once_with(mock_batch_processor.return_value)
