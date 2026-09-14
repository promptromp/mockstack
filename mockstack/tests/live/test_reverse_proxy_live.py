"""Live reverse-proxy tests."""

import json

import httpx
import pytest

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def proxy(upstream, mockstack_server):
    return mockstack_server(
        [
            {
                "name": "upstream-passthrough",
                "pattern": r"^/upstream/(.*)",
                "replacement": f"{upstream.base_url}/\\1",
            },
            {
                "name": "unreachable-passthrough",
                "pattern": r"^/unreachable/(.*)",
                "replacement": r"http://127.0.0.1:1/\1",
            },
        ]
    )


def test_each_test_starts_without_recorded_upstream_calls(upstream):
    """The session-wide upstream's calls are cleared before every live test, and server
    readiness is not probed over HTTP, so no test sees another test's requests or a
    readiness probe as a spurious first entry.
    """
    assert upstream.calls == []


def test_fixed_length_body_is_forwarded(proxy, upstream):
    big = {"query": "SELECT 1", "pad": "x" * 200_000}
    r = httpx.post(f"{proxy.base_url}/upstream/api/v1/thing?a=1", json=big)
    assert r.status_code == 200
    assert r.headers["x-mockstack-result"] == "proxy"
    assert len(upstream.calls) == 1
    assert json.loads(upstream.calls[-1]["body"]) == big
    assert upstream.calls[-1]["query"] == {"a": "1"}
    assert "x-mockstack-rule" not in upstream.calls[-1]["headers"]


def test_upstream_unreachable_returns_stamped_502(proxy):
    """A passthrough rule whose replacement points at a port nothing listens on must
    not surface as a bare, unstamped 500 from Starlette's ServerErrorMiddleware --
    'upstream unreachable' is the single most common eval failure and apply() must
    stamp it with the strategy's own X-Mockstack-* headers instead.
    """
    r = httpx.get(f"{proxy.base_url}/unreachable/api/v1/thing")
    assert r.status_code == 502
    assert r.headers["x-mockstack-result"] == "error"
    assert r.headers["x-mockstack-rule"] == "unreachable-passthrough"
    assert r.json() == {"error": "mockstack: upstream request failed"}


def test_repeated_set_cookie_headers_survive_reverse_proxy(proxy):
    r = httpx.get(f"{proxy.base_url}/upstream/cookies")
    assert r.status_code == 200
    assert r.headers["x-mockstack-result"] == "proxy"
    cookies = r.headers.get_list("set-cookie")
    assert len(cookies) == 2
    assert cookies[0].startswith("first=1")
    assert cookies[1].startswith("second=2")


def test_head_is_proxied_with_upstream_content_length(proxy, upstream):
    """HEAD must reach the strategy (not a router 405) and keep the upstream's
    Content-Length, which matches what the same GET returns."""
    r = httpx.head(f"{proxy.base_url}/upstream/sized")
    assert r.status_code == 200
    assert r.headers["x-mockstack-result"] == "proxy"
    assert r.headers["content-length"] == "1234"
    assert r.content == b""

    get = httpx.get(f"{proxy.base_url}/upstream/sized")
    assert get.headers["content-length"] == "1234"
    assert len(get.content) == 1234


def test_options_is_proxied(proxy, upstream):
    r = httpx.options(f"{proxy.base_url}/upstream/api/v1/thing")
    assert r.status_code == 200
    assert r.headers["x-mockstack-result"] == "proxy"
    assert upstream.calls[-1]["method"] == "OPTIONS"
    assert upstream.calls[-1]["path"] == "/api/v1/thing"


def test_proxied_response_has_single_date_and_server_headers(proxy, upstream):
    """uvicorn adds its own date/server headers to every response; the upstream's must
    not be forwarded on top of them."""
    r = httpx.get(f"{proxy.base_url}/upstream/api/v1/thing")
    assert r.status_code == 200
    assert r.headers["x-mockstack-result"] == "proxy"
    assert len(r.headers.get_list("date")) == 1
    assert len(r.headers.get_list("server")) == 1


def test_chunked_request_body_is_forwarded(proxy, upstream):
    def gen():
        for _ in range(10):
            yield b'{"chunk":"' + b"y" * 10_000 + b'"}\n'

    r = httpx.post(
        f"{proxy.base_url}/upstream/api/v1/chunked",
        content=gen(),
        headers={"content-type": "application/octet-stream"},
    )
    assert r.status_code == 200
    assert r.headers["x-mockstack-result"] == "proxy"
    assert len(upstream.calls[-1]["body"]) == 10 * (
        len('{"chunk":"') + 10_000 + len('"}\n')
    )
    assert "transfer-encoding" not in upstream.calls[-1]["headers"]
    assert "x-mockstack-rule" not in upstream.calls[-1]["headers"]
