"""Live tests for capturing response bodies in traces (``opentelemetry.capture_response_body``).

The tracing middleware reads the whole body to record it on the span, then sends a
rebuilt response. Over real sockets, that response must be the one mockstack sends with
capture off: the same status, body and headers, ``Content-Length`` included. The span
must have recorded the body.
"""

from unittest.mock import patch

import httpx
import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from mockstack.config import OpenTelemetrySettings


pytestmark = pytest.mark.slow

# Headers whose values differ from one response to the next.
VOLATILE_HEADERS = frozenset({"date", "x-process-time"})


@pytest.fixture(scope="module")
def servers(upstream, mockstack_server, tmp_path_factory):
    """Mockstack with capture off and on, over the same rules (the upstream, a template
    and a binary fixture), and the exporter that receives the traced server's spans."""
    fixtures = tmp_path_factory.mktemp("fixtures")
    (fixtures / "order.json.j2").write_text('{"id": {{ order_id | tojson }}}')
    (fixtures / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))
    rules = [
        {
            "name": "order",
            "pattern": "^/orders/(?P<order_id>[0-9]+)$",
            "replacement": f"file://{fixtures}/order.json.j2",
        },
        {"name": "logo", "pattern": "^/logo.png$", "replacement": f"file://{fixtures}/logo.png"},
        {"name": "upstream", "pattern": r"^/upstream/(.*)", "replacement": f"{upstream.base_url}/\\1"},
    ]
    off = mockstack_server(rules)
    # Spans go to memory, not to an OTLP collector, as each request ends. A process sets
    # its tracer provider only once: no other live test turns tracing on.
    exporter = InMemorySpanExporter()
    with (
        patch("mockstack.tracing.OTLPSpanExporter", return_value=exporter),
        patch("mockstack.tracing.BatchSpanProcessor", SimpleSpanProcessor),
    ):
        on = mockstack_server(rules, opentelemetry=OpenTelemetrySettings(enabled=True, capture_response_body=True))
    return off, on, exporter


def _framing(response: httpx.Response) -> tuple[int, bytes, list[tuple[str, str]]]:
    headers = [(name, value) for name, value in response.headers.multi_items() if name not in VOLATILE_HEADERS]
    return response.status_code, response.content, headers


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize(
    "path",
    [
        "/upstream/sized",
        # No Content-Length upstream, and so none on a proxied HEAD.
        "/upstream/unsized",
        # Decoded on the way through: a proxied HEAD drops the encoded length.
        "/upstream/gzipped",
        "/upstream/cookies",
        "/orders/1234",
        "/logo.png",
    ],
)
def test_capture_sends_the_response_unchanged(servers, method, path):
    off, on, exporter = servers

    expected = httpx.request(method, off.base_url + path)
    exporter.clear()
    captured = httpx.request(method, on.base_url + path)

    assert expected.status_code == 200
    assert _framing(captured) == _framing(expected)
    [span] = [span for span in exporter.get_finished_spans() if span.name == f"{method} {path}"]
    assert "http.response.body" in span.attributes
    if method == "GET":
        try:
            body = expected.content.decode("utf-8")
        except UnicodeDecodeError:
            body = f"<{len(expected.content)} bytes, not UTF-8>"
        assert span.attributes["http.response.body"] == body
