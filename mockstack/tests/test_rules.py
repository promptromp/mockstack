"""Unit-tests for the rules module."""

import pytest
from fastapi import Request
from starlette.datastructures import URL

from mockstack.rules import RequestPayload, Rule, TemplateRuleResult, URLRuleResult


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
    "pattern,replacement,path,fragment,expected_url",
    [
        (
            r"/api/v1/projects/(\d+)",
            r"/projects/\1",
            "/api/v1/projects/123",
            None,
            "/projects/123",
        ),
        (
            r"/api/v1/users/([^/]+)",
            r"/users/\1",
            "/api/v1/users/john",
            None,
            "/users/john",
        ),
        (
            r"/api/v1/projects/(\d+)",
            r"/projects/\1",
            "/api/v1/projects/123",
            "section",
            "/projects/123%23section",
        ),
        (
            r"/api/v1/users/([^/]+)",
            r"/users/\1",
            "/api/v1/users/john",
            "profile",
            "/users/john%23profile",
        ),
        (
            r"/api/v1/projects/(\d+)",
            r"/projects/\1",
            "/api/v1/projects/456",
            "top",
            "/projects/456%23top",
        ),
    ],
)
def test_rule_apply(pattern, replacement, path, fragment, expected_url):
    """Test the rule application logic."""
    rule = Rule(pattern=pattern, replacement=replacement)
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "headers": [],
    }
    request = Request(scope=scope)

    # If fragment is specified, we need to manually set the URL with the fragment
    # since fragments are not part of standard HTTP requests (they're client-side)
    if fragment:
        url_with_fragment = f"http://testserver{path}#{fragment}"
        request._url = URL(url_with_fragment)

    result = rule.apply(request)
    assert isinstance(result, URLRuleResult)
    assert result.get_result_type() == "url"
    assert result.url == expected_url


def test_rule_apply_template():
    """Test the rule application logic for template files."""
    rule = Rule(
        pattern=r"/api/v1/projects/(\d+)",
        replacement=r"file:///path/to/template.json",
    )
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/v1/projects/1234",
            "query_string": b"",
            "headers": [],
        }
    )
    result = rule.apply(request)
    assert isinstance(result, TemplateRuleResult)
    assert result.get_result_type() == "template"
    assert result.template_path == "/path/to/template.json"
    assert result.template_context is not None
    # The context should contain the extracted project ID from the path
    assert "projects" in result.template_context
    assert result.template_context["projects"] == "1234"


def test_request_payload_from_json_bytes():
    payload = RequestPayload.from_bytes(b'{"query": "SELECT 1"}')
    assert payload.text == '{"query": "SELECT 1"}'
    assert payload.json == {"query": "SELECT 1"}


def test_request_payload_from_non_json_bytes():
    payload = RequestPayload.from_bytes(b"plain text")
    assert payload.text == "plain text"
    assert payload.json is None


def test_request_payload_empty():
    assert RequestPayload.empty() == RequestPayload.from_bytes(b"")
    assert RequestPayload.empty().json is None
    assert RequestPayload.empty().text == ""


def test_request_payload_invalid_utf8_does_not_raise():
    payload = RequestPayload.from_bytes(b"\xff\xfe")
    assert "�" in payload.text
    assert payload.json is None


def test_rule_apply_template_context_includes_request_json():
    rule = Rule(
        pattern=r"^/analytics/v2/sql$", replacement="file:///tmp/x.json", method="POST"
    )
    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/analytics/v2/sql",
            "query_string": b"",
            "headers": [(b"x-request-eval-scenario", b"healthy")],
        }
    )
    payload = RequestPayload.from_bytes(b'{"query": "SELECT 1"}')
    result = rule.apply(request, payload)
    assert isinstance(result, TemplateRuleResult)
    assert result.template_context["request_json"] == {"query": "SELECT 1"}
    assert result.template_context["headers"]["x-request-eval-scenario"] == "healthy"


def test_rule_apply_without_payload_has_none_request_json():
    rule = Rule(pattern=r"^/x$", replacement="file:///tmp/x.json")
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/x",
            "query_string": b"",
            "headers": [],
        }
    )
    result = rule.apply(request)
    assert isinstance(result, TemplateRuleResult)
    assert result.template_context["request_json"] is None
