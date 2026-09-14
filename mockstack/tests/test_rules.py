"""Unit-tests for the rules module."""

import json

import pytest
from fastapi import Request
from jinja2 import Environment
from starlette.datastructures import URL

from mockstack.rules import (
    RequestPayload,
    Rule,
    TemplateRuleResult,
    URLRuleResult,
    lookup_path,
)


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
        pattern=r"^/druid/v2/sql$", replacement="file:///tmp/x.json", method="POST"
    )
    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/druid/v2/sql",
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


def _request(path="/x", method="GET", headers=None, query=b""):
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request(
        scope={
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query,
            "headers": raw_headers,
        }
    )


@pytest.mark.parametrize(
    "rule_headers,request_headers,expected",
    [
        (
            {"x-request-eval-scenario": ".*"},
            {"X-Request-Eval-Scenario": "healthy"},
            True,
        ),
        ({"x-request-eval-scenario": ".*"}, {}, False),
        (
            {"x-request-eval-scenario": "healthy"},
            {"x-request-eval-scenario": "healthy"},
            True,
        ),
        (
            {"x-request-eval-scenario": "healthy"},
            {"x-request-eval-scenario": "healthy_aligned"},
            False,
        ),
        (
            {"X-Request-Eval-Scenario": "h.*"},
            {"x-request-eval-scenario": "healthy"},
            True,
        ),
        ({"a": ".*", "b": "1"}, {"a": "x"}, False),
        ({"a": ".*", "b": "1"}, {"a": "x", "b": "1"}, True),
    ],
)
def test_rule_matches_headers(rule_headers, request_headers, expected):
    rule = Rule(pattern=r"^/x$", replacement="", headers=rule_headers)
    assert rule.matches(_request(headers=request_headers)) is expected


@pytest.mark.parametrize(
    "rule_query,query_string,expected",
    [
        ({"scenario": ".*"}, b"scenario=healthy", True),
        ({"scenario": ".*"}, b"", False),
        ({"scenario": "healthy"}, b"scenario=healthy_aligned", False),
        ({"limit": r"\d+"}, b"limit=10&x=1", True),
    ],
)
def test_rule_matches_query(rule_query, query_string, expected):
    rule = Rule(pattern=r"^/x$", replacement="", query=rule_query)
    assert rule.matches(_request(query=query_string)) is expected


def test_rule_from_dict_with_predicates():
    rule = Rule.from_dict(
        {
            "pattern": "^/x$",
            "replacement": "file:///f.json",
            "headers": {"X-Request-Eval-Scenario": ".*"},
            "query": {"q": "a"},
        }
    )
    assert rule.headers == {"x-request-eval-scenario": ".*"}
    assert rule.query == {"q": "a"}


def test_rule_without_predicates_matches_any_headers():
    rule = Rule(pattern=r"^/x$", replacement="")
    assert rule.matches(_request(headers={"anything": "goes"})) is True


@pytest.mark.parametrize(
    "data,path,expected",
    [
        ({"query": "SELECT 1"}, "query", "SELECT 1"),
        ({"filter": {"client": {"id": "c1"}}}, "filter.client.id", "c1"),
        ({"items": [{"name": "a"}, {"name": "b"}]}, "items.1.name", "b"),
        ({"n": 5}, "n", 5),
        ({"query": "x"}, "missing", None),
        ({"items": []}, "items.0", None),
        ("not a dict", "a", None),
        (None, "a", None),
    ],
)
def test_lookup_path(data, path, expected):
    assert lookup_path(data, path) == expected


def _druid(sql):
    return RequestPayload.from_bytes(
        json.dumps({"query": sql, "context": {"x": 1}}).encode()
    )


@pytest.mark.parametrize(
    "predicate,payload,expected",
    [
        ({"body": r"FROM\s+pricing"}, _druid("SELECT * FROM pricing WHERE 1"), True),
        ({"body": r"FROM\s+pricing"}, _druid("SELECT * FROM users"), False),
        (
            {"json": {"query": r".*FROM pricing.*"}},
            _druid("SELECT a FROM pricing"),
            True,
        ),
        ({"json": {"query": r"SELECT a"}}, _druid("SELECT a FROM pricing"), False),
        ({"json": {"context.x": "1"}}, _druid("x"), True),
        ({"json": {"context.missing": ".*"}}, _druid("x"), False),
        ({"json": {"query": ".*"}}, RequestPayload.empty(), False),
        ({"body": ".*"}, None, False),
        ({"body": ".*"}, RequestPayload.empty(), False),
        ({"body": ".*"}, RequestPayload.from_bytes(b"x"), True),
    ],
)
def test_rule_matches_body_predicates(predicate, payload, expected):
    rule = Rule(pattern=r"^/druid/v2/sql$", replacement="", method="POST", **predicate)
    request = _request(path="/druid/v2/sql", method="POST")
    assert rule.matches(request, payload) is expected


def test_rule_from_dict_with_body_predicates():
    rule = Rule.from_dict(
        {"pattern": "^/x$", "replacement": "u", "body": "abc", "json": {"a.b": "1"}}
    )
    assert rule.body == "abc"
    assert rule.json == {"a.b": "1"}


def test_template_context_includes_regex_groups():
    rule = Rule(
        pattern=r"^/juvenal/api/v2/project/(?P<project_id>[^/]+)/section/(\d+)$",
        replacement="file:///f.json",
    )
    request = _request(path="/juvenal/api/v2/project/proj-1/section/42")
    result = rule.apply(request)
    assert isinstance(result, TemplateRuleResult)
    assert result.template_context["project_id"] == "proj-1"
    assert result.template_context["groups"] == ("proj-1", "42")


def test_replacement_rendered_with_headers_and_groups():
    rule = Rule(
        pattern=r"^/juvenal/api/v2/project/(?P<id>[^/]+)$",
        replacement="file:///fixtures/{{ headers['x-request-eval-scenario'] }}/juvenal/project.{{ id }}.json.j2",
        env=Environment(),
    )
    request = _request(
        path="/juvenal/api/v2/project/abc",
        headers={"x-request-eval-scenario": "healthy"},
    )
    result = rule.apply(request)
    assert isinstance(result, TemplateRuleResult)
    assert result.template_path == "/fixtures/healthy/juvenal/project.abc.json.j2"


def test_replacement_backreference_still_works():
    rule = Rule(
        pattern=r"^/juvenal/(.*)",
        replacement=r"https://juvenal.example/\1",
        env=Environment(),
    )
    result = rule.apply(_request(path="/juvenal/api/v2/project/abc"))
    assert isinstance(result, URLRuleResult)
    assert result.url == "https://juvenal.example/api/v2/project/abc"


def test_replacement_url_rendered_from_request_json():
    rule = Rule(
        pattern=r"^/route$",
        replacement="https://{{ request_json.region }}.example/v1",
        method="POST",
        env=Environment(),
    )
    payload = RequestPayload.from_bytes(b'{"region": "eu"}')
    result = rule.apply(_request(path="/route", method="POST"), payload)
    assert isinstance(result, URLRuleResult)
    assert result.url == "https://eu.example/v1"


def test_replacement_without_env_is_not_rendered():
    rule = Rule(pattern=r"^/x$", replacement="file:///f/{{ id }}.json")
    result = rule.apply(_request(path="/x"))
    assert isinstance(result, TemplateRuleResult)
    assert result.template_path == "/f/{{ id }}.json"
