"""Unit-tests for the rules module."""

import pytest
from fastapi import Request

from mockstack.rules import Rule, TemplateRuleResult, URLRuleResult


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
