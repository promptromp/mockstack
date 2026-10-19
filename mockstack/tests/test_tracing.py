"""Unit tests for the tracing module, which needs the ``opentelemetry`` extra."""

import json
import os
import subprocess
import sys
import textwrap
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from starlette.responses import Response, StreamingResponse

from mockstack.config import OpenTelemetrySettings
from mockstack.main import create_app
from mockstack.tests.test_cli import TERMINAL_ENV_VARS
from mockstack.tracing import (
    extract_body,
    install,
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


@patch("mockstack.tracing.OTLPSpanExporter")
@patch("mockstack.tracing.BatchSpanProcessor")
@patch("mockstack.tracing.TracerProvider")
@patch("mockstack.tracing.trace")
@patch("mockstack.tracing.metadata")
def test_install_exports_to_the_endpoint(
    mock_metadata,
    mock_trace,
    mock_tracer_provider,
    mock_batch_processor,
    mock_otlp_exporter,
    make_settings,
    templates_dir,
):
    """``install`` sets a tracer provider that exports to the configured endpoint."""
    settings = make_settings(
        strategy="filefixtures",
        templates_dir=templates_dir,
        opentelemetry=OpenTelemetrySettings(enabled=True, endpoint="http://localhost:4317"),
    )
    mock_dist = MagicMock()
    mock_dist.name = "mockstack"
    mock_dist.version = "1.0.0"
    mock_metadata.distribution.return_value = mock_dist

    install(FastAPI(), settings)

    mock_tracer_provider.assert_called_once()
    provider = mock_tracer_provider.return_value
    mock_trace.set_tracer_provider.assert_called_once_with(provider)
    mock_otlp_exporter.assert_called_once_with(endpoint="http://localhost:4317")
    mock_batch_processor.assert_called_once_with(mock_otlp_exporter.return_value)
    provider.add_span_processor.assert_called_once_with(mock_batch_processor.return_value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("strategy", "capture_response_body", "strategy_attributes"),
    [
        ("filefixtures", False, {"mockstack.filefixtures.template_name": "api-v1-projects.j2"}),
        ("filefixtures", True, {"mockstack.filefixtures.template_name": "api-v1-projects.j2"}),
        (
            "proxyrules",
            False,
            {"mockstack.proxyrules.rule_name": "projects", "mockstack.proxyrules.result_type": "template"},
        ),
    ],
)
async def test_enabled_app_traces_each_request(
    make_settings, write_template, write_rules, tmp_path, strategy, capture_response_body, strategy_attributes
):
    """With tracing enabled, each request gets a span that the strategy adds to."""
    template = write_template("api-v1-projects.j2", '{"id": "1234"}')
    rules = write_rules(
        [{"name": "projects", "pattern": "/api/v1/projects/1234", "replacement": f"file:///{template}"}]
    )
    span = MagicMock()
    settings = make_settings(
        strategy=strategy,
        templates_dir=tmp_path,
        proxyrules_rules_filename=rules,
        opentelemetry=OpenTelemetrySettings(enabled=True, capture_response_body=capture_response_body),
    )
    with (
        patch("mockstack.tracing.trace") as mock_trace,
        patch("mockstack.tracing.OTLPSpanExporter"),
        patch("mockstack.tracing.BatchSpanProcessor"),
        patch("mockstack.tracing.TracerProvider"),
    ):
        mock_trace.get_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = span
        app = create_app(settings)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/v1/projects/1234")

    assert response.status_code == 200
    mock_trace.get_tracer.return_value.start_as_current_span.assert_called_once()
    assert mock_trace.get_tracer.return_value.start_as_current_span.call_args.args[0] == "GET /api/v1/projects/1234"
    attributes = {call.args[0]: call.args[1] for call in span.set_attribute.call_args_list}
    assert attributes["http.status_code"] == 200
    assert strategy_attributes.items() <= attributes.items()
    assert ("http.response.body" in attributes) is capture_response_body


MOCKSTACK_SPAN = "GET /api/v1/projects/1234"
FASTAPI_SPAN = "GET /{full_path}"
# The parent of the top span: none for a new trace, or the caller's span for a request
# whose traceparent header continues the caller's trace.
TOP = "top"


@pytest.mark.parametrize("traceparent", [False, True], ids=["new-trace", "continued-trace"])
@pytest.mark.parametrize(
    ("opentelemetry", "spans"),
    [
        ({"enabled": True}, [(MOCKSTACK_SPAN, TOP)]),
        ({"enabled": True, "fastapi_tracing": True}, [(FASTAPI_SPAN, TOP), (MOCKSTACK_SPAN, FASTAPI_SPAN)]),
        (
            {"enabled": True, "fastapi_tracing": True, "fastapi_operation_spans": True},
            [
                (FASTAPI_SPAN, TOP),
                (MOCKSTACK_SPAN, FASTAPI_SPAN),
                ("fastapi.dependencies", MOCKSTACK_SPAN),
                ("fastapi.endpoint", MOCKSTACK_SPAN),
            ],
        ),
        # Operation spans are part of FastAPI's tracing, and FastAPI's tracing uses the
        # tracer provider that mockstack's tracing sets: alone, each records nothing.
        ({"enabled": True, "fastapi_operation_spans": True}, [(MOCKSTACK_SPAN, TOP)]),
        ({"fastapi_tracing": True}, []),
    ],
    ids=["mockstack-only", "fastapi-tracing", "fastapi-operation-spans", "operation-spans-alone", "no-provider"],
)
def test_traced_request_spans(tmp_path, opentelemetry, spans, traceparent):
    """A traced request is exported as mockstack's span, inside FastAPI's own request span
    when FastAPI's built-in tracing is turned on, as one trace that continues the caller's.
    ``FASTAPI_OTEL_AUTO_CONFIGURE`` is ignored: it would make FastAPI add exporters at
    startup, which then fails without the packages FastAPI's own extra installs.

    Runs in a fresh interpreter, since a process can set its tracer provider only once.
    """
    (tmp_path / "api-v1-projects.j2").write_text('{"id": "1234"}')
    script = textwrap.dedent(
        f"""
        import asyncio
        import json
        import sys
        from unittest.mock import patch

        import httpx
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        from mockstack.config import Settings
        from mockstack.main import create_app

        CALLER_TRACE, CALLER_SPAN = 0x0AF7651916CD43DD8448EB211C80319C, 0xB7AD6B7169203331

        exporter = InMemorySpanExporter()
        with (
            patch("mockstack.tracing.OTLPSpanExporter", return_value=exporter),
            patch("mockstack.tracing.BatchSpanProcessor", SimpleSpanProcessor),
        ):
            app = create_app(Settings(templates_dir={str(tmp_path)!r}, opentelemetry=json.loads(sys.argv[1])))

        async def lifespan():
            events = iter([{{"type": "lifespan.startup"}}, {{"type": "lifespan.shutdown"}}])
            sent = []

            async def receive():
                return next(events)

            async def send(message):
                sent.append(message["type"])

            await app({{"type": "lifespan", "asgi": {{"version": "3.0"}}, "state": {{}}}}, receive, send)
            return sent

        async def get():
            headers = {{"traceparent": f"00-{{CALLER_TRACE:032x}}-{{CALLER_SPAN:016x}}-01"}} if sys.argv[2] else {{}}
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return (await client.get("/api/v1/projects/1234", headers=headers)).status_code

        assert asyncio.run(lifespan()) == ["lifespan.startup.complete", "lifespan.shutdown.complete"]
        assert asyncio.run(get()) == 200
        finished = exporter.get_finished_spans()
        names = {{span.context.span_id: span.name for span in finished}}

        def parent(span):
            if span.parent is None:
                return None
            if (span.parent.trace_id, span.parent.span_id) == (CALLER_TRACE, CALLER_SPAN):
                return "caller"
            return names.get(span.parent.span_id, "unexported")

        print(json.dumps(sorted(([span.name, parent(span)] for span in finished), key=lambda pair: pair[0])))
        """
    )
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith("MOCKSTACK__") and name not in TERMINAL_ENV_VARS
    }
    # S603: runs this interpreter on the script above, with no untrusted input.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script, json.dumps(opentelemetry), "1" if traceparent else ""],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={**env, "FASTAPI_OTEL_AUTO_CONFIGURE": "true"},
        check=False,
    )

    top = "caller" if traceparent else None
    expected = sorted(([name, top if parent == TOP else parent] for name, parent in spans), key=lambda pair: pair[0])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == expected
