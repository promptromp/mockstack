"""Unit tests for the proxyrules module."""

import gzip
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import yaml
from fastapi import Request, Response, status
from fastapi.responses import RedirectResponse
from httpx._decoders import SUPPORTED_DECODERS
from starlette.datastructures import URL, Headers, MutableHeaders
from starlette.requests import ClientDisconnect

from mockstack.constants import (
    RESULT_RULE_HEADER,
    RESULT_TYPE_HEADER,
    ProxyRulesRedirectVia,
)
from mockstack.rules import TemplateRuleResult, URLRuleResult
from mockstack.strategies.proxyrules import (
    ProxyRulesStrategy,
    Rule,
    UpstreamError,
    _header_safe,
    maybe_update_response_headers,
    strip_hop_by_hop,
    with_result_headers,
)


async def _empty_body_receive():
    """ASGI receive callable yielding an empty request body.

    ``ProxyRulesStrategy.apply`` now reads ``request.body()`` unconditionally, so
    requests built without a real ASGI ``receive`` channel need one to avoid
    Starlette's "Receive channel has not been made available" error.
    """
    return {"type": "http.request", "body": b"", "more_body": False}


def test_proxy_rules_strategy_load_rules(settings):
    """Test loading rules from the rules file."""
    strategy = ProxyRulesStrategy(settings)
    rules = strategy.load_rules()
    assert len(rules) > 0
    assert all(isinstance(rule, Rule) for rule in rules)


def test_load_rules_attaches_jinja_env(settings):
    strategy = ProxyRulesStrategy(settings)
    assert all(rule.env is strategy.env for rule in strategy.rules)


def test_proxy_rules_strategy_rule_for(settings, span):
    """Test finding a matching rule for a request."""
    strategy = ProxyRulesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/v1/projects/123",
            "query_string": b"",
            "headers": [],
        }
    )
    request.state.span = span
    rule = strategy.rule_for(request)
    assert rule is not None
    assert isinstance(rule, Rule)


def test_proxy_rules_strategy_rule_for_no_match(settings, span):
    """Test when no rule matches a request."""
    strategy = ProxyRulesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/nonexistent/path",
            "query_string": b"",
            "headers": [],
        }
    )
    request.state.span = span
    rule = strategy.rule_for(request)
    assert rule is None


@pytest.mark.asyncio
async def test_proxy_rules_strategy_apply(settings, span):
    """Test applying a rule to a request."""
    strategy = ProxyRulesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/v1/projects/123",
            "query_string": b"",
            "headers": [],
        },
        receive=_empty_body_receive,
    )
    request.state.span = span
    response = await strategy.apply(request)
    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == "/projects/123"


@pytest.mark.asyncio
async def test_proxy_rules_strategy_apply_with_fragment(settings, span):
    """Test applying a rule to a request with URL fragment."""
    strategy = ProxyRulesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/v1/projects/123",
            "query_string": b"",
            "headers": [],
        },
        receive=_empty_body_receive,
    )
    # Set URL with fragment (fragments are client-side only in HTTP, but we test the logic)
    request._url = URL("http://testserver/api/v1/projects/123#section")
    request.state.span = span
    response = await strategy.apply(request)
    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == "/projects/123%23section"


@pytest.mark.asyncio
async def test_proxy_rules_strategy_apply_no_match(settings, span):
    """Test applying strategy when no rule matches."""
    strategy = ProxyRulesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/nonexistent/path",
            "query_string": b"",
            "headers": [],
        },
        receive=_empty_body_receive,
    )
    request.state.span = span
    response = await strategy.apply(request)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_proxy_rules_strategy_apply_template(settings, span, tmp_path):
    """Test applying strategy with template rendering."""
    # Create a template file
    template_file = tmp_path / "template.json"
    template_file.write_text(
        '{"projects": "{{ projects }}", "name": "Project {{ projects }}"}'
    )

    # Create a rule that points to the template file
    rule_data = {
        "pattern": r"/api/v1/projects/(\d+)",
        "replacement": f"file:///{template_file}",
        "name": "test_template_rule",
    }

    # Mock the rule_for method to return our test rule
    strategy = ProxyRulesStrategy(settings)
    test_rule = Rule.from_dict(rule_data)

    with patch.object(strategy, "rule_for", return_value=test_rule):
        request = Request(
            scope={
                "type": "http",
                "method": "GET",
                "path": "/api/v1/projects/1234",
                "query_string": b"",
                "headers": [],
            },
            receive=_empty_body_receive,
        )
        request.state.span = span
        response = await strategy.apply(request)

        assert response.status_code == 200
        assert response.media_type == "application/json"
        assert response.body.decode() == '{"projects": "1234", "name": "Project 1234"}'


@pytest.mark.asyncio
async def test_apply_template_rejects_path_traversal(settings, span, tmp_path):
    """A rendered ``file://`` path containing ``..`` -- e.g. built in part from an
    unconstrained request value such as a header matched by ``.*`` -- must never be
    opened. It 404s without ever calling `open`, and the response body does not echo
    back the rejected path.
    """
    strategy = ProxyRulesStrategy(settings)
    rule = Rule.from_dict(
        {
            "pattern": r"^/x$",
            "replacement": f"file://{tmp_path}/fixtures/../../../etc/passwd",
        }
    )

    with (
        patch.object(strategy, "rule_for", return_value=rule),
        patch("builtins.open") as mock_open,
    ):
        request = Request(
            scope={
                "type": "http",
                "method": "GET",
                "path": "/x",
                "query_string": b"",
                "headers": [],
            },
            receive=_empty_body_receive,
        )
        request.state.span = span
        response = await strategy.apply(request)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_open.assert_not_called()
        assert "passwd" not in response.body.decode()
        assert response.headers[RESULT_TYPE_HEADER] == "error"
        assert json.loads(response.body) == {"error": "Template file not found."}


@pytest.mark.asyncio
async def test_apply_renders_request_json_from_body(settings, span, tmp_path):
    template_file = tmp_path / "sql.json"
    template_file.write_text('{"echo": {{ request_json.query | tojson }}}')
    strategy = ProxyRulesStrategy(settings)
    rule = Rule.from_dict(
        {
            "pattern": r"^/analytics/v2/sql$",
            "method": "POST",
            "replacement": f"file://{template_file}",
        }
    )
    body = b'{"query": "SELECT 1"}'

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/analytics/v2/sql",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
        },
        receive=receive,
    )
    request.state.span = span
    with patch.object(strategy, "rule_for", return_value=rule):
        response = await strategy.apply(request)
    assert response.status_code == 200
    assert response.body == b'{"echo": "SELECT 1"}'


def test_proxy_rules_strategy_get_content_type(settings):
    """Test content type detection based on file extension."""
    strategy = ProxyRulesStrategy(settings)

    # Test various file extensions
    assert strategy._get_content_type(Path("file.json")) == "application/json"
    assert strategy._get_content_type(Path("file.xml")) == "application/xml"
    assert strategy._get_content_type(Path("file.html")) == "text/html"
    assert strategy._get_content_type(Path("file.txt")) == "text/plain"
    assert strategy._get_content_type(Path("file.yaml")) == "application/x-yaml"
    assert strategy._get_content_type(Path("file.yml")) == "application/x-yaml"
    assert strategy._get_content_type(Path("file.unknown")) == "text/plain"


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("project.json", "application/json"),
        ("project.json.j2", "application/json"),
        ("project.xml.j2", "application/xml"),
        ("project.j2", "text/plain"),
        ("project", "text/plain"),
    ],
)
def test_get_content_type_strips_j2_suffix(settings, filename, expected):
    strategy = ProxyRulesStrategy(settings)
    assert strategy._get_content_type(Path(filename)) == expected


@pytest.mark.asyncio
@pytest.mark.skip(reason="TODO: Fix this test")
async def test_proxy_rules_strategy_apply_reverse_proxy(settings_reverse_proxy, span):
    """Test applying a rule to a request with reverse proxy enabled."""
    # Mock the httpx.AsyncClient to avoid making real HTTP requests
    mock_response = MagicMock()  # Use MagicMock for response to avoid async attributes
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({"content-type": "application/json"})
    mock_response.read = MagicMock(return_value=b'{"message": "success"}')

    mock_client = MagicMock()
    mock_client.send = AsyncMock(return_value=mock_response)
    mock_client.build_request.return_value = MagicMock()

    # Patch the httpx.AsyncClient to use our mock
    with patch("httpx.AsyncClient", return_value=mock_client):
        strategy = ProxyRulesStrategy(settings_reverse_proxy)
        request = Request(
            scope={
                "type": "http",
                "method": "GET",
                "path": "/api/v1/projects/123",
                "query_string": b"",
                "headers": [("host", "example.com")],
            }
        )
        request.state.span = span
        response = await strategy.apply(request)

        # Verify the response
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"
        assert response.body == b'{"message": "success"}'

        # Verify the reverse proxy was called with correct parameters
        mock_client.build_request.assert_called_once()
        mock_client.send.assert_called_once()


@pytest.mark.asyncio
async def test_proxy_rules_strategy_apply_permanent_redirect(settings, span):
    """Test applying a rule with permanent redirect."""
    settings.proxyrules_redirect_via = ProxyRulesRedirectVia.HTTP_PERMANENT_REDIRECT
    strategy = ProxyRulesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/v1/projects/123",
            "query_string": b"",
            "headers": [],
        },
        receive=_empty_body_receive,
    )
    request.state.span = span
    response = await strategy.apply(request)
    assert isinstance(response, RedirectResponse)
    assert response.status_code == status.HTTP_301_MOVED_PERMANENTLY
    assert response.headers["location"] == "/projects/123"


@pytest.mark.asyncio
async def test_proxy_rules_strategy_apply_invalid_redirect_via(settings, span):
    """An invalid redirect_via value is an internal failure: apply() answers it as a
    stamped 500 ``error`` rather than letting it propagate to Starlette's
    ServerErrorMiddleware as a bare, unstamped 500.
    """
    settings.proxyrules_redirect_via = "invalid"
    strategy = ProxyRulesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/v1/projects/123",
            "query_string": b"",
            "headers": [],
        },
        receive=_empty_body_receive,
    )
    request.state.span = span
    response = await strategy.apply(request)
    assert response.status_code == 500
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert RESULT_RULE_HEADER in response.headers
    assert json.loads(response.body) == {"error": "mockstack: internal error"}


@pytest.mark.asyncio
async def test_proxy_rules_strategy_apply_simulate_create(settings, span):
    """Test simulating resource creation when no rule matches."""
    settings.proxyrules_simulate_create_on_missing = True
    strategy = ProxyRulesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/nonexistent/path",
            "query_string": b"",
            "headers": [("content-type", "application/json")],
        }
    )
    request.state.span = span
    request.body = AsyncMock(return_value=b'{"name": "test"}')
    response = await strategy.apply(request)
    assert response.status_code == status.HTTP_201_CREATED
    assert response.headers[RESULT_TYPE_HEADER] == "create"
    assert RESULT_RULE_HEADER not in response.headers


@pytest.mark.asyncio
async def test_proxy_rules_strategy_apply_reverse_proxy_result_header(
    settings_reverse_proxy, span
):
    """apply() under reverse-proxy settings stamps X-Mockstack-Result: proxy."""
    strategy = ProxyRulesStrategy(settings_reverse_proxy)
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/v1/projects/123",
            "query_string": b"",
            "headers": [],
        },
        receive=_empty_body_receive,
    )
    request.state.span = span
    with patch.object(
        strategy,
        "reverse_proxy",
        AsyncMock(return_value=Response(content=b"{}", media_type="application/json")),
    ):
        response = await strategy.apply(request)
    assert response.headers[RESULT_TYPE_HEADER] == "proxy"


def test_proxy_rules_strategy_missing_rules_file(settings):
    """Test error when rules file is not set."""
    settings.proxyrules_rules_filename = None
    strategy = ProxyRulesStrategy(settings)
    with pytest.raises(ValueError, match="rules_filename is not set"):
        strategy.load_rules()


def test_proxy_rules_strategy_reverse_proxy_headers(settings):
    """Test reverse proxy headers modification."""
    strategy = ProxyRulesStrategy(settings)
    headers = Headers(
        {"host": "example.com", "user-agent": "test", "accept": "application/json"}
    )
    target_url = "https://api.target.com/path"

    modified_headers = strategy.reverse_proxy_headers(headers, target_url)
    assert modified_headers["host"] == "api.target.com"
    assert modified_headers["user-agent"] == "test"
    assert modified_headers["accept"] == "application/json"


def test_proxy_rules_strategy_update_opentelemetry(settings, span):
    """Test OpenTelemetry span updates."""
    strategy = ProxyRulesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/test",
            "query_string": b"",
            "headers": [],
        }
    )
    request.state.span = span

    rule = Rule(pattern="/test", replacement="/target", method="GET", name="test_rule")

    strategy.update_opentelemetry(request, rule, "/target")

    span.set_attribute.assert_any_call("mockstack.proxyrules.rule_name", "test_rule")
    span.set_attribute.assert_any_call("mockstack.proxyrules.rule_method", "GET")
    span.set_attribute.assert_any_call("mockstack.proxyrules.rule_pattern", "/test")
    span.set_attribute.assert_any_call(
        "mockstack.proxyrules.rule_replacement", "/target"
    )
    span.set_attribute.assert_any_call("mockstack.proxyrules.rewritten_url", "/target")


@pytest.mark.asyncio
async def test_proxy_rules_strategy_reverse_proxy(settings_reverse_proxy, span):
    """Test reverse proxy functionality."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({"content-type": "application/json"})
    mock_response.read = MagicMock(return_value=b'{"message": "success"}')

    mock_client = AsyncMock()
    mock_client.send = AsyncMock(return_value=mock_response)
    mock_client.build_request = MagicMock()

    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/test",
            "query_string": b"key=value",
            "headers": [
                (b"host", b"example.com"),
                (b"content-type", b"application/json"),
            ],
        }
    )
    request.body = AsyncMock(return_value=b'{"data": "test"}')

    strategy = ProxyRulesStrategy(settings_reverse_proxy)

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client_class.return_value = mock_client
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        response = await strategy.reverse_proxy(request, "https://api.target.com/test")

        # Verify response
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"
        assert response.body == b'{"message": "success"}'

        # Verify request building was called
        assert mock_client.build_request.call_count == 1
        call_args = mock_client.build_request.call_args
        assert call_args is not None
        args, kwargs = call_args

        # Verify method and URL
        assert args[0] == "POST"
        assert args[1] == "https://api.target.com/test"

        # Verify other arguments
        assert kwargs["content"] == b'{"data": "test"}'
        assert kwargs["params"] == request.url.query

        # Verify headers were passed (without checking exact format)
        assert "headers" in kwargs
        headers = kwargs["headers"]
        assert isinstance(headers, Headers)

        mock_client.send.assert_called_once()


def test_maybe_update_response_headers_updates_content_encoding():
    """Test maybe_update_response_headers updates content-encoding."""
    response_headers = httpx.Headers(
        {"content-encoding": "gzip", "content-type": "application/json"}
    )

    updated_headers = maybe_update_response_headers(
        response_headers=response_headers,
        content_length=100,
        status_code=200,
        request_method="GET",
    )

    assert updated_headers["content-encoding"] == "identity"
    assert updated_headers["content-type"] == "application/json"
    assert updated_headers["content-length"] == "100"


@pytest.mark.parametrize("status_code", [204, 304])
def test_maybe_update_response_headers_omits_content_length_for_204_304(status_code):
    """RFC 9110 §8.6: a server MUST NOT send Content-Length on a 204, and on a 304 the
    value must match what the 200 would have carried -- ``0`` would be a lie. Neither
    status should carry a content-length header at all.
    """
    response_headers = httpx.Headers(
        {"content-length": "1234", "content-type": "application/json"}
    )

    updated_headers = maybe_update_response_headers(
        response_headers=response_headers,
        content_length=0,
        status_code=status_code,
        request_method="GET",
    )

    assert "content-length" not in updated_headers


def test_maybe_update_response_headers_sets_content_length_for_200():
    """A normal 200 response still gets an accurate content-length."""
    response_headers = httpx.Headers({"content-type": "application/json"})

    updated_headers = maybe_update_response_headers(
        response_headers=response_headers,
        content_length=42,
        status_code=200,
        request_method="GET",
    )

    assert updated_headers["content-length"] == "42"


def test_reverse_proxy_headers_strips_hop_by_hop_and_length(settings):
    """Forwarded request headers must not carry framing headers; httpx recomputes them."""
    strategy = ProxyRulesStrategy(settings)
    headers = Headers(
        {
            "host": "example.com",
            "transfer-encoding": "chunked",
            "content-length": "5",
            "connection": "keep-alive",
            "x-request-eval-scenario": "healthy",
        }
    )
    out = strategy.reverse_proxy_headers(headers, "https://api.target.com/p")
    assert "transfer-encoding" not in out
    assert "content-length" not in out
    assert "connection" not in out
    assert out["x-request-eval-scenario"] == "healthy"
    assert out["host"] == "api.target.com"


def test_rule_for_prefers_stamped_fixture_then_falls_through(settings, tmp_path):
    rules_file = tmp_path / "rules.yml"
    rules_file.write_text(
        """
rules:
  - name: projects-eval
    method: GET
    pattern: ^/projects/api/v1/project/(?P<id>[^/]+)$
    headers:
      x-request-eval-scenario: ".*"
    replacement: file:///fixtures/projects/project.json.j2
  - name: projects-passthrough
    pattern: ^/projects/(.*)
    replacement: https://projects.example/\\1
"""
    )
    settings = settings.model_copy(update={"proxyrules_rules_filename": rules_file})
    strategy = ProxyRulesStrategy(settings)

    def req(headers):
        return Request(
            scope={
                "type": "http",
                "method": "GET",
                "path": "/projects/api/v1/project/abc",
                "query_string": b"",
                "headers": headers,
            }
        )

    stamped = strategy.rule_for(req([(b"x-request-eval-scenario", b"healthy")]))
    unstamped = strategy.rule_for(req([]))
    assert stamped is not None and stamped.name == "projects-eval"
    assert unstamped is not None and unstamped.name == "projects-passthrough"


def test_maybe_update_response_headers_strips_transfer_encoding():
    """Upstream chunked responses are buffered, so transfer-encoding must go and content-length be set."""
    response_headers = httpx.Headers(
        {"transfer-encoding": "chunked", "content-type": "application/json"}
    )
    updated = maybe_update_response_headers(
        response_headers=response_headers,
        content_length=42,
        status_code=200,
        request_method="GET",
    )
    assert "transfer-encoding" not in updated
    assert updated["content-length"] == "42"
    assert updated["content-type"] == "application/json"


@pytest.mark.asyncio
async def test_template_response_carries_result_headers(settings, span, tmp_path):
    template_file = tmp_path / "t.json"
    template_file.write_text('{"ok": true}')
    strategy = ProxyRulesStrategy(settings)
    rule = Rule.from_dict(
        {"name": "t-rule", "pattern": r"^/t$", "replacement": f"file://{template_file}"}
    )
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/t",
            "query_string": b"",
            "headers": [],
        },
        receive=_empty_body_receive,
    )
    request.state.span = span
    with patch.object(strategy, "rule_for", return_value=rule):
        response = await strategy.apply(request)
    assert response.headers[RESULT_RULE_HEADER] == "t-rule"
    assert response.headers[RESULT_TYPE_HEADER] == "template"


@pytest.mark.asyncio
async def test_missing_rule_response_carries_result_headers(settings, span):
    strategy = ProxyRulesStrategy(settings)
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/nothing",
            "query_string": b"",
            "headers": [],
        },
        receive=_empty_body_receive,
    )
    request.state.span = span
    with patch.object(strategy, "rule_for", return_value=None):
        response = await strategy.apply(request)
    assert response.status_code == 404
    assert response.headers[RESULT_TYPE_HEADER] == "missing"
    assert RESULT_RULE_HEADER not in response.headers


@pytest.mark.asyncio
async def test_redirect_response_carries_result_headers(settings, span):
    strategy = ProxyRulesStrategy(settings)  # HTTP_TEMPORARY_REDIRECT in this fixture
    rule = Rule.from_dict(
        {"pattern": r"^/api/(.*)", "replacement": r"https://api.example/\1"}
    )
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/x",
            "query_string": b"",
            "headers": [],
        },
        receive=_empty_body_receive,
    )
    request.state.span = span
    with patch.object(strategy, "rule_for", return_value=rule):
        response = await strategy.apply(request)
    assert response.headers[RESULT_RULE_HEADER] == r"^/api/(.*)"
    assert response.headers[RESULT_TYPE_HEADER] == "redirect"


@pytest.mark.asyncio
async def test_non_latin1_rule_name_is_sanitized_in_result_header(
    settings, span, tmp_path
):
    """A rule name outside latin-1 must not crash header encoding (Starlette encodes
    header values as latin-1); it is escaped to plain ASCII instead."""
    template_file = tmp_path / "t.json"
    template_file.write_text('{"ok": true}')
    strategy = ProxyRulesStrategy(settings)
    rule = Rule.from_dict(
        {
            "name": "日本語ルール",
            "pattern": r"^/t$",
            "replacement": f"file://{template_file}",
        }
    )
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/t",
            "query_string": b"",
            "headers": [],
        },
        receive=_empty_body_receive,
    )
    request.state.span = span
    with patch.object(strategy, "rule_for", return_value=rule):
        response = await strategy.apply(request)
    assert response.status_code == 200
    header_value = response.headers[RESULT_RULE_HEADER]
    assert header_value != ""
    header_value.encode("ascii")  # must not raise


@pytest.mark.asyncio
async def test_rule_name_with_crlf_is_sanitized_in_result_header(
    settings, span, tmp_path
):
    """A rule name containing CR/LF must not leak them into the header value."""
    template_file = tmp_path / "t.json"
    template_file.write_text('{"ok": true}')
    strategy = ProxyRulesStrategy(settings)
    rule = Rule.from_dict(
        {
            "name": "bad\r\nname",
            "pattern": r"^/t$",
            "replacement": f"file://{template_file}",
        }
    )
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/t",
            "query_string": b"",
            "headers": [],
        },
        receive=_empty_body_receive,
    )
    request.state.span = span
    with patch.object(strategy, "rule_for", return_value=rule):
        response = await strategy.apply(request)
    header_value = response.headers[RESULT_RULE_HEADER]
    assert "\r" not in header_value
    assert "\n" not in header_value


def test_header_safe_strips_all_ascii_control_characters():
    """Other ASCII control characters (NUL, VT, DEL) survive `backslashreplace` just
    like a plain byte and h11 rejects them; they must be replaced with a space just
    like CR/LF, not merely the ones the earlier CR/LF-only test happened to cover.
    """
    value = "bad\x00name\x0bwith\x7fcontrol\r\nchars"
    safe = _header_safe(value)
    for ch in safe:
        assert ord(ch) >= 0x20 and ord(ch) != 0x7F
    safe.encode("ascii")  # must not raise


def _request_for(
    path="/x", *, method="GET", headers=None, body=b"", receive=None, span=None
):
    """Request with a real ASGI receive channel carrying ``body``."""

    async def _receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        scope={
            "type": "http",
            "method": method,
            "path": path,
            "query_string": b"",
            "headers": headers or [],
        },
        receive=receive or _receive,
    )
    if span is not None:
        request.state.span = span
    return request


@pytest.mark.asyncio
async def test_apply_stamps_502_on_upstream_connect_error(settings_reverse_proxy, span):
    """A connection failure inside the real reverse_proxy must not propagate to
    Starlette's ServerErrorMiddleware as a bare, unstamped 500 -- 'upstream
    unreachable' is the single most common eval failure and the one case the
    fail-loud mechanism must still cover.
    """
    strategy = ProxyRulesStrategy(settings_reverse_proxy)
    request = _request_for("/api/v1/projects/123", span=span)
    with patch.object(
        httpx.AsyncClient, "send", AsyncMock(side_effect=httpx.ConnectError("boom"))
    ):
        response = await strategy.apply(request)
    assert response.status_code == 502
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert RESULT_RULE_HEADER in response.headers
    assert json.loads(response.body) == {"error": "mockstack: upstream request failed"}


@pytest.mark.asyncio
async def test_apply_stamps_504_on_upstream_timeout(settings_reverse_proxy, span):
    strategy = ProxyRulesStrategy(settings_reverse_proxy)
    request = _request_for("/api/v1/projects/123", span=span)
    with patch.object(
        httpx.AsyncClient, "send", AsyncMock(side_effect=httpx.ReadTimeout("slow"))
    ):
        response = await strategy.apply(request)
    assert response.status_code == 504
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert RESULT_RULE_HEADER in response.headers
    assert json.loads(response.body) == {
        "error": "mockstack: upstream request timed out"
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc,status_code",
    [
        (httpx.ConnectTimeout("t"), 504),
        (httpx.ReadTimeout("t"), 504),
        (httpx.ConnectError("c"), 502),
        (httpx.RemoteProtocolError("p"), 502),
    ],
)
async def test_reverse_proxy_translates_httpx_errors(
    settings_reverse_proxy, exc, status_code
):
    strategy = ProxyRulesStrategy(settings_reverse_proxy)
    with (
        patch.object(httpx.AsyncClient, "send", AsyncMock(side_effect=exc)),
        pytest.raises(UpstreamError) as info,
    ):
        await strategy.reverse_proxy(_request_for("/x"), "http://upstream.invalid/x")
    assert info.value.status_code == status_code
    assert info.value.__cause__ is exc


@pytest.mark.asyncio
async def test_upstream_error_is_logged_as_warning_without_traceback(
    settings_reverse_proxy, span, caplog
):
    strategy = ProxyRulesStrategy(settings_reverse_proxy)
    with (
        patch.object(
            httpx.AsyncClient, "send", AsyncMock(side_effect=httpx.ConnectError("c"))
        ),
        caplog.at_level(logging.WARNING, logger="ProxyRulesStrategy"),
    ):
        await strategy.apply(_request_for("/api/v1/projects/123", span=span))
    records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert [r.levelname for r in records] == ["WARNING"]
    assert records[0].exc_info is None


@pytest.mark.asyncio
async def test_simulate_create_with_malformed_json_body_is_stamped_500(settings, span):
    """The create path parses the body with ``request.json()`` (create_mixin is out of
    scope here); a malformed body is an internal failure, answered as a stamped 500
    ``error`` with no rule header since no rule matched.
    """
    settings.proxyrules_simulate_create_on_missing = True
    strategy = ProxyRulesStrategy(settings)
    request = _request_for(
        "/nonexistent/path",
        method="POST",
        headers=[(b"content-type", b"application/json")],
        body=b'{"name": ',
        span=span,
    )
    response = await strategy.apply(request)
    assert response.status_code == 500
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert RESULT_RULE_HEADER not in response.headers
    assert json.loads(response.body) == {"error": "mockstack: internal error"}


@pytest.mark.asyncio
async def test_client_disconnect_propagates(settings, span):
    """A client that went away gets no answer; ClientDisconnect is not swallowed."""
    strategy = ProxyRulesStrategy(settings)

    async def disconnect():
        return {"type": "http.disconnect"}

    request = _request_for("/api/v1/projects/123", receive=disconnect, span=span)
    with pytest.raises(ClientDisconnect):
        await strategy.apply(request)


@pytest.mark.asyncio
async def test_missing_fixture_is_stamped_404_error_without_echoing_path(
    settings, span, tmp_path, caplog
):
    missing = tmp_path / "secret-scenario" / "project.json.j2"
    strategy = ProxyRulesStrategy(settings)
    rule = Rule.from_dict(
        {"name": "fixture-rule", "pattern": r"^/x$", "replacement": f"file://{missing}"}
    )
    with (
        patch.object(strategy, "rule_for", return_value=rule),
        caplog.at_level(logging.ERROR, logger="ProxyRulesStrategy"),
    ):
        response = await strategy.apply(_request_for("/x", span=span))
    assert response.status_code == 404
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert response.headers[RESULT_RULE_HEADER] == "fixture-rule"
    assert json.loads(response.body) == {"error": "Template file not found."}
    assert str(missing) in caplog.text


@pytest.mark.asyncio
async def test_fixture_render_failure_is_stamped_500_error(settings, span, tmp_path):
    template_file = tmp_path / "broken.json.j2"
    template_file.write_text('{"x": {{ oops }')
    strategy = ProxyRulesStrategy(settings)
    rule = Rule.from_dict(
        {
            "name": "broken-rule",
            "pattern": r"^/x$",
            "replacement": f"file://{template_file}",
        }
    )
    with patch.object(strategy, "rule_for", return_value=rule):
        response = await strategy.apply(_request_for("/x", span=span))
    assert response.status_code == 500
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert response.headers[RESULT_RULE_HEADER] == "broken-rule"


@pytest.mark.asyncio
async def test_undefined_variable_in_replacement_is_stamped_500_error(
    settings, span, caplog
):
    strategy = ProxyRulesStrategy(settings)
    rule = Rule.from_dict(
        {
            "name": "scenario-rule",
            "pattern": r"^/x$",
            "replacement": "file:///fixtures/{{ headers['x-request-eval-scenario'] }}/f.json",
        },
        env=strategy.env,
    )
    with (
        patch.object(strategy, "rule_for", return_value=rule),
        caplog.at_level(logging.ERROR, logger="ProxyRulesStrategy"),
    ):
        response = await strategy.apply(_request_for("/x", span=span))
    assert response.status_code == 500
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert response.headers[RESULT_RULE_HEADER] == "scenario-rule"
    assert json.loads(response.body) == {"error": "mockstack: internal error"}
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "scenario-rule" in errors[0].getMessage()
    assert errors[0].exc_info is not None


@pytest.mark.asyncio
async def test_unexpected_error_after_match_is_stamped_500_with_rule(settings, span):
    strategy = ProxyRulesStrategy(settings)
    rule = Rule.from_dict({"name": "boom-rule", "pattern": r"^/x$", "replacement": "u"})
    with (
        patch.object(strategy, "rule_for", return_value=rule),
        patch.object(rule, "apply", side_effect=RuntimeError("boom")),
    ):
        response = await strategy.apply(_request_for("/x", span=span))
    assert response.status_code == 500
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert response.headers[RESULT_RULE_HEADER] == "boom-rule"


@pytest.mark.asyncio
async def test_result_log_line_omits_template_context(settings, span, tmp_path, caplog):
    template_file = tmp_path / "t.json"
    template_file.write_text('{"ok": true}')
    strategy = ProxyRulesStrategy(settings)
    rule = Rule.from_dict(
        {"name": "t-rule", "pattern": r"^/t$", "replacement": f"file://{template_file}"}
    )
    request = _request_for(
        "/t",
        method="POST",
        headers=[(b"x-secret-token", b"hunter2")],
        body=b'{"query": "SELECT confidential"}',
        span=span,
    )
    with (
        patch.object(strategy, "rule_for", return_value=rule),
        caplog.at_level(logging.INFO, logger="ProxyRulesStrategy"),
    ):
        response = await strategy.apply(request)
    assert response.status_code == 200
    assert str(template_file) in caplog.text
    assert "template" in caplog.text
    assert "hunter2" not in caplog.text
    assert "confidential" not in caplog.text


@pytest.mark.asyncio
async def test_result_log_line_for_url_result_logs_target_url(settings, span, caplog):
    strategy = ProxyRulesStrategy(settings)
    rule = Rule.from_dict(
        {"name": "u-rule", "pattern": r"^/api/(.*)", "replacement": r"https://h/\1"}
    )
    request = _request_for(
        "/api/x", headers=[(b"x-secret-token", b"hunter2")], span=span
    )
    with (
        patch.object(strategy, "rule_for", return_value=rule),
        caplog.at_level(logging.INFO, logger="ProxyRulesStrategy"),
    ):
        await strategy.apply(request)
    assert "https://h/x" in caplog.text
    assert "hunter2" not in caplog.text


@pytest.mark.asyncio
async def test_handlers_stamp_their_own_result_type(settings, span, tmp_path):
    strategy = ProxyRulesStrategy(settings)  # HTTP_TEMPORARY_REDIRECT
    rule = Rule.from_dict({"name": "r", "pattern": r"^/x$", "replacement": "https://h"})
    request = _request_for("/x", span=span)

    redirect = await strategy.handle_url_result(
        request, rule, URLRuleResult(url="https://h/x")
    )
    assert redirect.headers[RESULT_TYPE_HEADER] == "redirect"
    assert redirect.headers[RESULT_RULE_HEADER] == "r"

    template_file = tmp_path / "t.json"
    template_file.write_text("{}")
    rendered = await strategy.handle_template_result(
        request,
        rule,
        TemplateRuleResult(template_path=str(template_file), template_context={}),
    )
    assert rendered.headers[RESULT_TYPE_HEADER] == "template"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("ok", "ok"),
        ("  bad\x00name\x7f ", "bad name"),
        ("\r\n\t", "unnamed"),
        ("", "unnamed"),
        ("日本", "\\u65e5\\u672c"),
    ],
)
def test_header_safe_strips_and_falls_back(value, expected):
    assert _header_safe(value) == expected


def test_with_result_headers_tolerates_non_string_rule_name():
    rule = Rule(pattern=r"^/x$", replacement="u")
    rule.name = 12345
    response = with_result_headers(Response(), rule=rule, result_type="proxy")
    assert response.headers[RESULT_RULE_HEADER] == "12345"


def test_with_result_headers_falls_back_when_name_sanitises_to_empty():
    rule = Rule(name="\r\n", pattern=r"^/x$", replacement="u")
    response = with_result_headers(Response(), rule=rule, result_type="proxy")
    assert response.headers[RESULT_RULE_HEADER] == "unnamed"


def _starlette_headers(items):
    return MutableHeaders(raw=[(k.lower().encode(), v.encode()) for k, v in items])


@pytest.mark.parametrize("factory", [_starlette_headers, httpx.Headers])
def test_strip_hop_by_hop_removes_connection_listed_headers(factory):
    headers = factory(
        [
            ("Connection", "keep-alive, X-Custom-Hop"),
            ("connection", "X-Second-Hop"),
            ("x-custom-hop", "1"),
            ("x-second-hop", "2"),
            ("keep-alive", "timeout=5"),
            ("transfer-encoding", "chunked"),
            ("content-type", "application/json"),
            ("x-kept", "yes"),
        ]
    )
    strip_hop_by_hop(headers)
    for name in (
        "connection",
        "x-custom-hop",
        "x-second-hop",
        "keep-alive",
        "transfer-encoding",
    ):
        assert name not in headers
    assert headers["content-type"] == "application/json"
    assert headers["x-kept"] == "yes"


def test_reverse_proxy_headers_strips_connection_listed_headers(settings):
    strategy = ProxyRulesStrategy(settings)
    headers = Headers(
        raw=[
            (b"host", b"example.com"),
            (b"connection", b"keep-alive, X-Custom-Hop"),
            (b"x-custom-hop", b"1"),
            (b"x-kept", b"yes"),
        ]
    )
    out = strategy.reverse_proxy_headers(headers, "https://api.target.com/p")
    assert "x-custom-hop" not in out
    assert "connection" not in out
    assert out["x-kept"] == "yes"


@pytest.mark.parametrize("upstream_length", ["1234", None])
def test_maybe_update_response_headers_preserves_head_content_length(upstream_length):
    """A HEAD response has no body, so the buffered length (0) says nothing; the
    upstream's Content-Length describes the GET representation and must survive."""
    raw = {"content-type": "application/json"}
    if upstream_length is not None:
        raw["content-length"] = upstream_length
    updated = maybe_update_response_headers(
        httpx.Headers(raw),
        content_length=0,
        status_code=200,
        request_method="HEAD",
    )
    assert updated.get("content-length") == upstream_length


# httpx only decodes the codings in SUPPORTED_DECODERS (br / zstd only when brotli /
# zstandard are installed) and silently skips the rest.
BROTLI_DECODED = "br" in SUPPORTED_DECODERS
ZSTD_DECODED = "zstd" in SUPPORTED_DECODERS


@pytest.mark.parametrize(
    "encoding,expected",
    [
        ("gzip", "identity"),
        ("GZIP", "identity"),
        (" Deflate ", "identity"),
        ("gzip, deflate", "identity"),
        ("identity", "identity"),
        ("br", "identity" if BROTLI_DECODED else "br"),
        ("zstd", "identity" if ZSTD_DECODED else "zstd"),
        ("gzip, br", "identity" if BROTLI_DECODED else "br"),
        ("gzip, compress", "compress"),
        ("compress", "compress"),
        ("Compress", "Compress"),
        ("dcb", "dcb"),
        ("dcz", "dcz"),
        ("x-custom", "x-custom"),
    ],
)
def test_maybe_update_response_headers_relabels_only_decoded_encodings(
    encoding, expected
):
    """Only codings httpx actually decoded may be removed from Content-Encoding; a
    coding it skipped must stay, or the client gets an encoded body labelled
    ``identity``. When nothing was decoded the value is left exactly as sent."""
    updated = maybe_update_response_headers(
        httpx.Headers({"content-encoding": encoding}),
        content_length=3,
        status_code=200,
        request_method="GET",
    )
    assert updated["content-encoding"] == expected


def test_head_drops_content_length_when_encoding_was_relabelled():
    """On HEAD the upstream Content-Length is the *encoded* length; once the coding is
    relabelled (a GET would be decoded) that length is wrong, so it is dropped."""
    updated = maybe_update_response_headers(
        httpx.Headers({"content-encoding": "gzip", "content-length": "1234"}),
        content_length=0,
        status_code=200,
        request_method="HEAD",
    )
    assert updated["content-encoding"] == "identity"
    assert "content-length" not in updated


@pytest.mark.parametrize("encoding", ["compress", "identity"])
def test_head_keeps_content_length_when_encoding_was_not_decoded(encoding):
    """Nothing decoded (or only the no-op ``identity``): the upstream length stands."""
    updated = maybe_update_response_headers(
        httpx.Headers({"content-encoding": encoding, "content-length": "1234"}),
        content_length=0,
        status_code=200,
        request_method="HEAD",
    )
    assert updated["content-encoding"] == encoding
    assert updated["content-length"] == "1234"


@pytest.mark.asyncio
async def test_reverse_proxy_gzip_body_is_decoded_and_relabelled(
    settings_reverse_proxy,
):
    raw = b'{"ok":true}'
    upstream = httpx.Response(
        200,
        headers={"content-type": "application/json", "content-encoding": "gzip"},
        content=gzip.compress(raw),
    )
    strategy = ProxyRulesStrategy(settings_reverse_proxy)
    with patch.object(httpx.AsyncClient, "send", AsyncMock(return_value=upstream)):
        response = await strategy.reverse_proxy(
            _request_for("/x"), "http://upstream.invalid/x"
        )
    assert response.body == raw
    assert response.headers["content-encoding"] == "identity"
    assert response.headers["content-length"] == str(len(raw))


@pytest.mark.asyncio
async def test_reverse_proxy_undecoded_body_keeps_its_encoding(settings_reverse_proxy):
    encoded = b"\x1f\x9d-lzw-compressed-bytes"
    upstream = httpx.Response(
        200, headers={"content-encoding": "compress"}, content=encoded
    )
    strategy = ProxyRulesStrategy(settings_reverse_proxy)
    with patch.object(httpx.AsyncClient, "send", AsyncMock(return_value=upstream)):
        response = await strategy.reverse_proxy(
            _request_for("/x"), "http://upstream.invalid/x"
        )
    assert response.body == encoded
    assert response.headers["content-encoding"] == "compress"
    assert response.headers["content-length"] == str(len(encoded))


def test_maybe_update_response_headers_strips_connection_listed_headers():
    updated = maybe_update_response_headers(
        httpx.Headers({"connection": "x-upstream-hop", "x-upstream-hop": "1"}),
        content_length=0,
        status_code=200,
        request_method="GET",
    )
    assert "x-upstream-hop" not in updated
    assert "connection" not in updated


@pytest.mark.asyncio
async def test_reverse_proxy_preserves_repeated_response_headers(
    settings_reverse_proxy,
):
    body = b'{"ok":true}'
    upstream = httpx.Response(
        200,
        headers=[
            ("content-type", "application/json"),
            ("set-cookie", "first=1; Path=/"),
            ("set-cookie", "second=2; Path=/"),
        ],
        content=body,
    )
    strategy = ProxyRulesStrategy(settings_reverse_proxy)
    with patch.object(httpx.AsyncClient, "send", AsyncMock(return_value=upstream)):
        response = await strategy.reverse_proxy(
            _request_for("/x"), "http://upstream.invalid/x"
        )
    assert [v for k, v in response.raw_headers if k == b"set-cookie"] == [
        b"first=1; Path=/",
        b"second=2; Path=/",
    ]
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-length"] == str(len(body))
    assert response.body == body


@pytest.mark.asyncio
async def test_reverse_proxy_head_keeps_upstream_content_length(
    settings_reverse_proxy,
):
    upstream = httpx.Response(
        200,
        headers=[("content-type", "application/json"), ("content-length", "1234")],
    )
    strategy = ProxyRulesStrategy(settings_reverse_proxy)
    with patch.object(httpx.AsyncClient, "send", AsyncMock(return_value=upstream)):
        response = await strategy.reverse_proxy(
            _request_for("/x", method="HEAD"), "http://upstream.invalid/x"
        )
    assert response.headers["content-length"] == "1234"
    assert response.body == b""


@pytest.mark.parametrize(
    "rule,message",
    [
        (
            {"name": "bad-regex", "pattern": "^/x/(unclosed$", "replacement": "u"},
            r"rule 'bad-regex': invalid regex '\^/x/\(unclosed\$'",
        ),
        (
            {
                "name": "bad-header",
                "pattern": "^/x$",
                "headers": {"x-scenario": "[a-z"},
                "replacement": "u",
            },
            r"rule 'bad-header': invalid regex '\[a-z'",
        ),
        (
            {
                "name": "shadowing",
                "pattern": r"^/x/(?P<headers>[^/]+)$",
                "replacement": "u",
            },
            r"rule 'shadowing': named group 'headers' shadows a reserved template",
        ),
        (
            {
                "name": "bad-template",
                "pattern": "^/x$",
                "replacement": "file:///{{ id .j",
            },
            r"rule 'bad-template': invalid replacement template",
        ),
        (
            {
                "name": 2024,
                "pattern": "^/x$",
                "headers": {"x-foo": None},
                "replacement": "u",
            },
            r"rule '2024': predicate 'x-foo' has no value",
        ),
    ],
    ids=[
        "invalid-regex",
        "invalid-predicate-regex",
        "reserved-group",
        "template-syntax",
        "predicate-without-value",
    ],
)
def test_invalid_rules_file_fails_at_startup_with_rule_name(
    settings, tmp_path, rule, message
):
    """A bad rules file fails when the strategy is built (startup), naming the rule."""
    rules_file = tmp_path / "rules.yml"
    rules_file.write_text(yaml.safe_dump({"rules": [rule]}))
    bad = settings.model_copy(update={"proxyrules_rules_filename": rules_file})
    with pytest.raises(ValueError, match=message):
        ProxyRulesStrategy(bad)
