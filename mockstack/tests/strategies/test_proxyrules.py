"""Unit tests for the proxyrules module."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import Request, status
from fastapi.responses import RedirectResponse
from starlette.datastructures import Headers

from mockstack.constants import ProxyRulesRedirectVia
from mockstack.strategies.proxyrules import (
    ProxyRulesStrategy,
    Rule,
    maybe_update_response_headers,
)


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
            }
        )
        request.state.span = span
        response = await strategy.apply(request)

        assert response.status_code == 200
        assert response.media_type == "application/json"
        assert response.body.decode() == '{"projects": "1234", "name": "Project 1234"}'


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

    def test_maybe_update_response_headers_updates_content_encoding():
        """Test maybe_update_response_headers updates content-encoding."""
        headers = Headers(
            {"content-encoding": "gzip", "content-type": "application/json"}
        )
        request_headers = Headers({"accept-encoding": "gzip"})

        updated_headers = maybe_update_response_headers(headers, request_headers)

        assert updated_headers["content-encoding"] == "identity"
        assert updated_headers["content-type"] == "application/json"
        assert updated_headers["accept-encoding"] == "gzip"
