"""Live reverse-proxy tests."""

import json

import httpx
import pytest

from mockstack.tests.live.conftest import proxyrules_settings, write_rules

pytestmark = pytest.mark.slow


@pytest.fixture
def proxy(tmp_path, upstream, mockstack_server):
    rules = write_rules(
        tmp_path,
        [
            {
                "name": "upstream-passthrough",
                "pattern": r"^/upstream/(.*)",
                "replacement": f"{upstream.base_url}/\\1",
            }
        ],
    )
    return mockstack_server(proxyrules_settings(rules))


def test_readiness_probe_is_not_recorded(upstream):
    """The `_serve()` readiness poll hits `/__ready` before tests run; it must not
    be recorded as a call, otherwise every test would see it as a spurious first entry.
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


def test_upstream_unreachable_returns_stamped_502(tmp_path, mockstack_server):
    """A passthrough rule whose replacement points at a port nothing listens on must
    not surface as a bare, unstamped 500 from Starlette's ServerErrorMiddleware --
    'upstream unreachable' is the single most common eval failure and apply() must
    stamp it with the strategy's own X-Mockstack-* headers instead.
    """
    rules = write_rules(
        tmp_path,
        [
            {
                "name": "unreachable-passthrough",
                "pattern": r"^/upstream/(.*)",
                "replacement": r"http://127.0.0.1:1/\1",
            }
        ],
    )
    server = mockstack_server(proxyrules_settings(rules))
    r = httpx.get(f"{server.base_url}/upstream/api/v1/thing")
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
