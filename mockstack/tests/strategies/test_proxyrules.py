"""Unit tests for the proxyrules module."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import Request
from fastapi.responses import RedirectResponse

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


def test_proxy_rules_strategy_rule_for(settings):
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
    rule = strategy.rule_for(request)
    assert rule is not None
    assert isinstance(rule, Rule)


def test_proxy_rules_strategy_rule_for_no_match(settings):
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
    rule = strategy.rule_for(request)
    assert rule is None


@pytest.mark.asyncio
async def test_proxy_rules_strategy_apply(settings):
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
    response = await strategy.apply(request)
    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == "/projects/123"


@pytest.mark.asyncio
async def test_proxy_rules_strategy_apply_no_match(settings):
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
    response = await strategy.apply(request)
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.skip(reason="TODO: Fix this test")
async def test_proxy_rules_strategy_apply_reverse_proxy(settings_reverse_proxy):
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
        response = await strategy.apply(request)

        # Verify the response
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"
        assert response.body == b'{"message": "success"}'

        # Verify the reverse proxy was called with correct parameters
        mock_client.build_request.assert_called_once()
        mock_client.send.assert_called_once()
