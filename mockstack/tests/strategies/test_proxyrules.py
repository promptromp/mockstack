"""Unit tests for the proxyrules module."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import Request, status
from fastapi.responses import RedirectResponse
from starlette.datastructures import Headers

from mockstack.constants import ProxyRulesRedirectVia
from mockstack.strategies.proxyrules import ProxyRulesStrategy, Rule


def test_rule_from_dict():
    """Test creating a Rule from a dictionary."""
    data = {
        "pattern": r"/api/v1/projects/(\d+)",
        "replacement": r"/projects/\1",
        "method": "GET",
    }
    rule = Rule.from_dict(data)
    assert rule.pattern == data["pattern"]
    assert rule.replacement == data["replacement"]
    assert rule.method == data["method"]


def test_rule_from_dict_without_method():
    """Test creating a Rule from a dictionary without a method."""
    data = {
        "pattern": r"/api/v1/projects/(\d+)",
        "replacement": r"/projects/\1",
    }
    rule = Rule.from_dict(data)
    assert rule.pattern == data["pattern"]
    assert rule.replacement == data["replacement"]
    assert rule.method is None


@pytest.mark.parametrize(
    "pattern,path,method,expected",
    [
        (r"/api/v1/projects/\d+", "/api/v1/projects/123", "GET", True),
        (r"/api/v1/projects/\d+", "/api/v1/projects/123", "POST", True),
        (r"/api/v1/projects/\d+", "/api/v1/projects/abc", "GET", False),
        (r"/api/v1/projects/\d+", "/api/v1/users/123", "GET", False),
        (r"/api/v1/projects/\d+", "/api/v1/projects/123", "POST", True),
    ],
)
def test_rule_matches(pattern, path, method, expected):
    """Test the rule matching logic."""
    rule = Rule(pattern=pattern, replacement="", method=None)
    request = Request(
        scope={
            "type": "http",
            "method": method,
            "path": path,
            "query_string": b"",
            "headers": [],
        }
    )
    assert rule.matches(request) == expected


@pytest.mark.parametrize(
    "pattern,path,method,expected",
    [
        (r"/api/v1/projects/\d+", "/api/v1/projects/123", "GET", True),
        (r"/api/v1/projects/\d+", "/api/v1/projects/123", "POST", False),
    ],
)
def test_rule_matches_with_method(pattern, path, method, expected):
    """Test the rule matching logic with method restriction."""
    rule = Rule(pattern=pattern, replacement="", method="GET")
    request = Request(
        scope={
            "type": "http",
            "method": method,
            "path": path,
            "query_string": b"",
            "headers": [],
        }
    )
    assert rule.matches(request) == expected


@pytest.mark.parametrize(
    "pattern,replacement,path,expected_url",
    [
        (
            r"/api/v1/projects/(\d+)",
            r"/projects/\1",
            "/api/v1/projects/123",
            "/projects/123",
        ),
        (
            r"/api/v1/users/([^/]+)",
            r"/users/\1",
            "/api/v1/users/john",
            "/users/john",
        ),
    ],
)
def test_rule_apply(pattern, replacement, path, expected_url):
    """Test the rule application logic."""
    rule = Rule(pattern=pattern, replacement=replacement)
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "headers": [],
        }
    )
    url = rule.apply(request)
    assert isinstance(url, str)
    assert url == expected_url


def test_proxy_rules_strategy_load_rules(settings):
    """Test loading rules from the rules file."""
    strategy = ProxyRulesStrategy(settings)
    rules = strategy.load_rules()
    assert len(rules) > 0
    assert all(isinstance(rule, Rule) for rule in rules)


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
        }
    )
    request.state.span = span
    response = await strategy.apply(request)
    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == "/projects/123"


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
        }
    )
    request.state.span = span
    response = await strategy.apply(request)
    assert response.status_code == 404


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
        }
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
        }
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
