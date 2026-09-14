"""Unit tests for the proxyrules module."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import Request, Response, status
from fastapi.responses import RedirectResponse
from starlette.datastructures import URL, Headers

from mockstack.constants import (
    RESULT_RULE_HEADER,
    RESULT_TYPE_HEADER,
    ProxyRulesRedirectVia,
)
from mockstack.strategies.proxyrules import (
    ProxyRulesStrategy,
    Rule,
    maybe_update_response_headers,
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
    """Test applying a rule with invalid redirect_via value."""
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
    with pytest.raises(ValueError, match="Invalid redirect via value"):
        await strategy.apply(request)


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


def test_proxy_rules_strategy_reverse_proxy_headers():
    """Test reverse proxy headers modification."""
    settings = MagicMock()
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
    mock_response.headers = {"content-type": "application/json"}
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
    )

    assert updated_headers["content-encoding"] == "identity"
    assert updated_headers["content-type"] == "application/json"
    assert updated_headers["content-length"] == "100"


def test_reverse_proxy_headers_strips_hop_by_hop_and_length():
    """Forwarded request headers must not carry framing headers; httpx recomputes them."""
    strategy = ProxyRulesStrategy(MagicMock())
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
  - name: projects-project-eval
    method: GET
    pattern: ^/projects/api/v2/project/(?P<id>[^/]+)$
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
                "path": "/projects/api/v2/project/abc",
                "query_string": b"",
                "headers": headers,
            }
        )

    stamped = strategy.rule_for(req([(b"x-request-eval-scenario", b"healthy")]))
    unstamped = strategy.rule_for(req([]))
    assert stamped is not None and stamped.name == "projects-project-eval"
    assert unstamped is not None and unstamped.name == "projects-passthrough"


def test_maybe_update_response_headers_strips_transfer_encoding():
    """Upstream chunked responses are buffered, so transfer-encoding must go and content-length be set."""
    response_headers = httpx.Headers(
        {"transfer-encoding": "chunked", "content-type": "application/json"}
    )
    updated = maybe_update_response_headers(
        response_headers=response_headers, content_length=42
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
