"""Unit-tests for the rules module."""

import json
import re
from unittest.mock import patch

import pytest
from jinja2 import Environment, TemplateSyntaxError, UndefinedError
from starlette.datastructures import URL

from mockstack.rules import (
    MISSING,
    RESERVED_CONTEXT_KEYS,
    RequestPayload,
    Rule,
    TemplateRuleResult,
    URLRuleResult,
    lookup_path,
)


@pytest.mark.parametrize(
    "data,expected_method",
    [
        (
            {
                "pattern": r"/api/v1/projects/(\d+)",
                "replacement": r"/projects/\1",
                "method": "GET",
            },
            "GET",
        ),
        ({"pattern": r"/api/v1/projects/(\d+)", "replacement": r"/projects/\1"}, None),
    ],
    ids=["with-method", "without-method"],
)
def test_rule_from_dict(data, expected_method):
    """Test creating a Rule from a dictionary, with or without a method."""
    rule = Rule.from_dict(data)
    assert rule.pattern == data["pattern"]
    assert rule.replacement == data["replacement"]
    assert rule.method == expected_method


def test_rule_from_dict_with_predicates():
    """Every predicate is taken from the dictionary; header names are lower-cased."""
    rule = Rule.from_dict(
        {
            "pattern": "^/x$",
            "replacement": "file:///f.json",
            "headers": {"X-Request-Eval-Scenario": ".*"},
            "query": {"q": "a"},
            "body": "abc",
            "json": {"a.b": "1"},
        }
    )
    assert rule.headers == {"x-request-eval-scenario": ".*"}
    assert rule.query == {"q": "a"}
    assert rule.body == "abc"
    assert rule.json == {"a.b": "1"}


@pytest.mark.parametrize(
    "rule_method,path,method,expected",
    [
        (None, "/api/v1/projects/123", "GET", True),
        (None, "/api/v1/projects/123", "POST", True),
        (None, "/api/v1/projects/abc", "GET", False),
        (None, "/api/v1/users/123", "GET", False),
        ("GET", "/api/v1/projects/123", "GET", True),
        ("GET", "/api/v1/projects/123", "POST", False),
    ],
    ids=[
        "any-method-get",
        "any-method-post",
        "path-mismatch",
        "other-resource",
        "method-restricted-match",
        "method-restricted-mismatch",
    ],
)
def test_rule_matches(make_request, rule_method, path, method, expected):
    """A rule matches on its path pattern and, when it has one, its method."""
    rule = Rule(pattern=r"/api/v1/projects/\d+", replacement="", method=rule_method)
    assert rule.matches(make_request(path, method=method)) == expected


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
def test_rule_apply(make_request, pattern, replacement, path, fragment, expected_url):
    """Test the rule application logic."""
    rule = Rule(pattern=pattern, replacement=replacement)
    request = make_request(path)

    # If fragment is specified, we need to manually set the URL with the fragment
    # since fragments are not part of standard HTTP requests (they're client-side)
    if fragment:
        request._url = URL(f"http://testserver{path}#{fragment}")

    result = rule.apply(request)
    assert isinstance(result, URLRuleResult)
    assert result.get_result_type() == "url"
    assert result.url == expected_url


def test_rule_apply_template(make_request):
    """Test the rule application logic for template files."""
    rule = Rule(
        pattern=r"/api/v1/projects/(\d+)",
        replacement=r"file:///path/to/template.json",
    )
    result = rule.apply(make_request("/api/v1/projects/1234"))
    assert isinstance(result, TemplateRuleResult)
    assert result.get_result_type() == "template"
    assert result.template_path == "/path/to/template.json"
    assert result.template_context is not None
    # The context should contain the extracted project ID from the path
    assert "projects" in result.template_context
    assert result.template_context["projects"] == "1234"


@pytest.mark.parametrize(
    "raw,text,parsed",
    [
        (b'{"query": "SELECT 1"}', '{"query": "SELECT 1"}', {"query": "SELECT 1"}),
        (b'{"a": 1}', '{"a": 1}', {"a": 1}),
        (b"plain text", "plain text", None),
        (b"\xff\xfe", "\ufffd\ufffd", None),
    ],
    ids=["json-string", "json-number", "not-json", "invalid-utf8-does-not-raise"],
)
def test_request_payload_decodes_text_and_json(raw, text, parsed):
    """``text`` is the body decoded as UTF-8, invalid bytes replaced rather than raising;
    ``json`` is the parsed body, or None when it is not JSON."""
    payload = RequestPayload(raw)
    assert payload.raw == raw
    assert payload.text == text
    assert payload.json == parsed


def test_request_payload_empty():
    assert RequestPayload.empty() == RequestPayload.from_bytes(b"")
    assert RequestPayload.empty().json is None
    assert RequestPayload.empty().text == ""


def test_rule_apply_template_context_includes_request_json(make_request):
    rule = Rule(
        pattern=r"^/analytics/v2/sql$", replacement="file:///tmp/x.json", method="POST"
    )
    request = make_request(
        "/analytics/v2/sql",
        method="POST",
        headers={"x-request-eval-scenario": "healthy"},
    )
    payload = RequestPayload.from_bytes(b'{"query": "SELECT 1"}')
    result = rule.apply(request, payload)
    assert isinstance(result, TemplateRuleResult)
    assert result.template_context["request_json"] == {"query": "SELECT 1"}
    assert result.template_context["headers"]["x-request-eval-scenario"] == "healthy"


def test_rule_apply_without_payload_has_none_request_json(make_request):
    rule = Rule(pattern=r"^/x$", replacement="file:///tmp/x.json")
    result = rule.apply(make_request("/x"))
    assert isinstance(result, TemplateRuleResult)
    assert result.template_context["request_json"] is None


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
def test_rule_matches_headers(make_request, rule_headers, request_headers, expected):
    rule = Rule(pattern=r"^/x$", replacement="", headers=rule_headers)
    assert rule.matches(make_request("/x", headers=request_headers)) is expected


@pytest.mark.parametrize(
    "rule_query,query_string,expected",
    [
        ({"scenario": ".*"}, b"scenario=healthy", True),
        ({"scenario": ".*"}, b"", False),
        ({"scenario": "healthy"}, b"scenario=healthy_aligned", False),
        ({"limit": r"\d+"}, b"limit=10&x=1", True),
        ({"status": "b"}, b"status=a&status=b", True),
        ({"status": "a"}, b"status=a&status=b", False),
    ],
    ids=[
        "any-value",
        "absent",
        "full-match-only",
        "among-other-parameters",
        "repeated-parameter-last-value-matches",
        "repeated-parameter-earlier-value-ignored",
    ],
)
def test_rule_matches_query(make_request, rule_query, query_string, expected):
    """A query predicate fully matches the parameter's value; for a repeated parameter
    (``?status=a&status=b``) that is the last one, as Starlette's ``QueryParams.get``
    returns."""
    rule = Rule(pattern=r"^/x$", replacement="", query=rule_query)
    assert rule.matches(make_request("/x", query=query_string)) is expected


def test_rule_without_predicates_matches_any_headers(make_request):
    rule = Rule(pattern=r"^/x$", replacement="")
    assert rule.matches(make_request("/x", headers={"anything": "goes"})) is True


@pytest.mark.parametrize(
    "data,path,expected",
    [
        ({"query": "SELECT 1"}, "query", "SELECT 1"),
        ({"filter": {"client": {"id": "c1"}}}, "filter.client.id", "c1"),
        ({"items": [{"name": "a"}, {"name": "b"}]}, "items.1.name", "b"),
        ({"n": 5}, "n", 5),
        # A present JSON null is None, which never equals the MISSING sentinel.
        ({"v": None}, "v", None),
    ],
    ids=[
        "top-level-scalar",
        "nested-dict-path",
        "list-index-path",
        "top-level-int",
        "present-none-value",
    ],
)
def test_lookup_path(data, path, expected):
    assert lookup_path(data, path) == expected


@pytest.mark.parametrize(
    "data,path",
    [
        ({"query": "x"}, "missing"),
        ({"items": []}, "items.0"),
        ({"items": ["a"]}, "items.x"),
        ("not a dict", "a"),
        (None, "a"),
    ],
)
def test_lookup_path_absent_returns_missing_sentinel(data, path):
    assert lookup_path(data, path) is MISSING


def _sql_payload(sql):
    return RequestPayload.from_bytes(
        json.dumps({"query": sql, "context": {"x": 1}}).encode()
    )


@pytest.mark.parametrize(
    "predicate,payload,expected",
    [
        ({"body": r"FROM\s+sales"}, _sql_payload("SELECT * FROM sales WHERE 1"), True),
        ({"body": r"FROM\s+sales"}, _sql_payload("SELECT * FROM users"), False),
        (
            {"json": {"query": r".*FROM sales.*"}},
            _sql_payload("SELECT a FROM sales"),
            True,
        ),
        ({"json": {"query": r"SELECT a"}}, _sql_payload("SELECT a FROM sales"), False),
        ({"json": {"context.x": "1"}}, _sql_payload("x"), True),
        ({"json": {"context.missing": ".*"}}, _sql_payload("x"), False),
        ({"json": {"query": ".*"}}, RequestPayload.empty(), False),
        ({"body": ".*"}, None, False),
        ({"body": ".*"}, RequestPayload.empty(), False),
        ({"body": ".*"}, RequestPayload.from_bytes(b"x"), True),
        ({"json": {"active": "true"}}, RequestPayload(b'{"active": true}'), True),
        ({"json": {"active": "True"}}, RequestPayload(b'{"active": true}'), False),
        ({"json": {"v": ".*"}}, RequestPayload(b'{"v": null}'), True),
        ({"json": {"v": "null"}}, RequestPayload(b'{"v": null}'), True),
        ({"json": {"v": "x"}}, RequestPayload(b'{"v": null}'), False),
        ({"json": {"absent": ".*"}}, RequestPayload(b'{"v": null}'), False),
        ({"json": {"n": r"1\.5"}}, RequestPayload(b'{"n": 1.5}'), True),
        ({"json": {"obj": r'\{"a":1\}'}}, RequestPayload(b'{"obj": {"a": 1}}'), True),
        (
            {"json": {"obj": r'\{"a":1,"b":2\}'}},
            RequestPayload(b'{"obj": {"b": 2, "a": 1}}'),
            True,
        ),
        ({"json": {"s": "abc"}}, RequestPayload(b'{"s": "abc"}'), True),
        ({"json": {"s": '"abc"'}}, RequestPayload(b'{"s": "abc"}'), False),
        # Objects are re-serialised with ensure_ascii=False: café, not caf\u00e9.
        (
            {"json": {"obj": r'\{"name":"café"\}'}},
            RequestPayload('{"obj": {"name": "café"}}'.encode()),
            True,
        ),
    ],
    ids=[
        "body-regex-matches",
        "body-regex-no-match",
        "json-field-regex-matches",
        "json-field-regex-not-full-match",
        "json-nested-dotted-path-matches",
        "json-nested-dotted-path-missing",
        "empty-payload-no-match",
        "none-payload-no-match",
        "empty-payload-body-predicate-no-match",
        "nonempty-body-predicate-matches",
        "json-bool-lowercase-matches",
        "json-bool-case-mismatch-no-match",
        "json-null-value-wildcard-matches",
        "json-null-value-literal-matches",
        "json-null-value-mismatch-no-match",
        "json-absent-field-no-match",
        "json-float-matches",
        "json-object-serialized-matches",
        "json-object-key-order-normalized",
        "json-string-matches",
        "json-string-quoted-value-no-match",
        "json-object-unicode-matches",
    ],
)
def test_rule_matches_body_predicates(make_request, predicate, payload, expected):
    rule = Rule(
        pattern=r"^/analytics/v2/sql$", replacement="", method="POST", **predicate
    )
    request = make_request("/analytics/v2/sql", method="POST")
    assert rule.matches(request, payload) is expected


def test_template_context_includes_regex_groups(make_request):
    rule = Rule(
        pattern=r"^/projects/api/v1/project/(?P<project_id>[^/]+)/section/(\d+)$",
        replacement="file:///f.json",
    )
    result = rule.apply(make_request("/projects/api/v1/project/proj-1/section/42"))
    assert isinstance(result, TemplateRuleResult)
    assert result.template_context["project_id"] == "proj-1"
    assert result.template_context["groups"] == ("proj-1", "42")


def test_replacement_rendered_with_headers_and_groups(make_request):
    rule = Rule(
        pattern=r"^/projects/api/v1/project/(?P<id>[^/]+)$",
        replacement="file:///fixtures/{{ headers['x-request-eval-scenario'] }}/projects/project.{{ id }}.json.j2",
        env=Environment(),
    )
    request = make_request(
        "/projects/api/v1/project/abc",
        headers={"x-request-eval-scenario": "healthy"},
    )
    result = rule.apply(request)
    assert isinstance(result, TemplateRuleResult)
    assert result.template_path == "/fixtures/healthy/projects/project.abc.json.j2"


@pytest.mark.parametrize(
    "replacement",
    [r"https://projects.example/\1", "https://projects.example/{{ groups[0] }}"],
    ids=["backreference", "jinja-positional-group"],
)
def test_replacement_rewrites_captured_path(make_request, replacement):
    """A regex backreference still works alongside Jinja replacements, and a Jinja
    replacement reaches positional groups through ``groups``."""
    rule = Rule(pattern=r"^/projects/(.*)$", replacement=replacement, env=Environment())
    result = rule.apply(make_request("/projects/api/v1/project/abc"))
    assert isinstance(result, URLRuleResult)
    assert result.url == "https://projects.example/api/v1/project/abc"


@pytest.mark.parametrize(
    "replacement",
    [r"https://projects.example/\1", "https://projects.example/{{ groups[0] }}"],
    ids=["backreference", "jinja-positional-group"],
)
def test_request_path_text_is_never_evaluated_as_template(make_request, replacement):
    """Jinja delimiters in the request path are never evaluated. A plain backreference
    replacement is never treated as a template: the decision to render is made on the
    operator-authored ``replacement``, never on substituted request data. In a Jinja
    replacement the captured group text reaches the template only as a context value,
    which Jinja renders literally rather than re-parsing as template source.
    """
    rule = Rule(pattern=r"^/projects/(.*)$", replacement=replacement, env=Environment())
    result = rule.apply(make_request("/projects/{{ 7*7 }}"))
    assert isinstance(result, URLRuleResult)
    assert "49" not in result.url
    assert "{{ 7*7 }}" in result.url


def test_replacement_url_rendered_from_request_json(make_request):
    rule = Rule(
        pattern=r"^/route$",
        replacement="https://{{ request_json.region }}.example/v1",
        method="POST",
        env=Environment(),
    )
    payload = RequestPayload.from_bytes(b'{"region": "eu"}')
    result = rule.apply(make_request("/route", method="POST"), payload)
    assert isinstance(result, URLRuleResult)
    assert result.url == "https://eu.example/v1"


def test_replacement_without_env_is_not_rendered(make_request):
    rule = Rule(pattern=r"^/x$", replacement="file:///f/{{ id }}.json")
    result = rule.apply(make_request("/x"))
    assert isinstance(result, TemplateRuleResult)
    assert result.template_path == "/f/{{ id }}.json"


def test_template_context_groups_key_not_clobbered_by_heuristic_identifier(
    make_request,
):
    """A path like `/groups/42` yields a heuristic identifier keyed `groups` (the
    filefixtures-style inference treats `42` as an id nested under the `groups`
    path segment); the mandated `groups` tuple of positional regex groups must win.
    """
    rule = Rule(
        pattern=r"^/groups/(\d+)$",
        replacement="file:///f.json",
    )
    result = rule.apply(make_request("/groups/42"))
    assert isinstance(result, TemplateRuleResult)
    assert result.template_context["groups"] == ("42",)


# --- load-time validation and compilation -------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [(2024, "2024"), (None, None)],
    ids=["int-coerced-to-str", "none-stays-none"],
)
def test_rule_name_is_coerced_to_str(name, expected):
    """YAML parses ``name: 2024`` as an int; the rule name must still be a string."""
    rule = Rule.from_dict({"name": name, "pattern": "^/x$", "replacement": "u"})
    assert rule.name == expected


def test_predicate_values_are_coerced_to_str(make_request):
    """YAML parses unquoted ``1``/``true`` as int/bool; predicates must still work."""
    rule = Rule.from_dict(
        {
            "pattern": "^/x$",
            "replacement": "u",
            "headers": {"X-Version": 2},
            "query": {"limit": 10},
            "json": {"active": True},
            "body": 123,
        }
    )
    assert rule.headers == {"x-version": "2"}
    assert rule.query == {"limit": "10"}
    assert rule.json == {"active": "True"}
    assert rule.body == "123"
    request = make_request("/x", headers={"x-version": "2"}, query=b"limit=10")
    assert rule.matches(request, RequestPayload(b'{"active": "True", "n": 123}'))


@pytest.mark.parametrize("field", ["headers", "query", "json"])
def test_predicate_without_value_is_rejected_at_load(field):
    """``x-foo:`` with no value parses as None; that is a rules-file mistake."""
    with pytest.raises(ValueError, match=r"rule 'r1': predicate 'x-foo' has no value"):
        Rule.from_dict(
            {
                "name": "r1",
                "pattern": "^/x$",
                "replacement": "u",
                field: {"x-foo": None},
            }
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("pattern", "^/x/(unclosed$"),
        ("headers", {"x-foo": "(unclosed"}),
        ("query", {"q": "[unclosed"}),
        ("json", {"a.b": "*bad"}),
        ("body", "(unclosed"),
    ],
)
def test_invalid_regex_is_rejected_at_construction(field, value):
    data = {"pattern": "^/x$", "replacement": "u", field: value}
    with pytest.raises(re.error):
        Rule.from_dict(data)


@pytest.mark.parametrize("key", sorted(RESERVED_CONTEXT_KEYS))
def test_named_group_shadowing_reserved_context_key_is_rejected(key):
    with pytest.raises(
        ValueError,
        match=rf"rule 'r1': named group '{key}' shadows a reserved template variable",
    ):
        Rule(name="r1", pattern=rf"^/x/(?P<{key}>[^/]+)$", replacement="u")


def test_reserved_context_keys():
    assert RESERVED_CONTEXT_KEYS == frozenset(
        {"query", "headers", "path", "method", "request_json", "groups"}
    )


@pytest.mark.parametrize(
    "replacement",
    [
        r"file:///fixtures/{{ headers['x-scenario'] }}/\1.json",
        r"file:///fixtures/{{ id }}/\g<id>.json",
        r"https://{{ id }}.example/\9",
        r"https://x/\1/{{ id }}",
    ],
)
def test_template_replacement_with_backreference_is_rejected_at_load(replacement):
    with pytest.raises(ValueError, match="backreference"):
        Rule(
            name="r1",
            pattern=r"^/x/(?P<id>[^/]+)$",
            replacement=replacement,
            env=Environment(),
        )


def test_backreference_with_jinja_delimiters_is_allowed_without_env(make_request):
    """Without an environment the replacement is never a template, so re.sub runs and
    backreferences expand as usual; nothing to reject."""
    rule = Rule(pattern=r"^/x/([^/]+)$", replacement=r"https://h/\1/{{ id }}")
    result = rule.apply(make_request("/x/abc"))
    assert isinstance(result, URLRuleResult)
    assert result.url == "https://h/abc/{{ id }}"


def test_template_replacement_syntax_error_is_raised_at_load():
    with pytest.raises(TemplateSyntaxError):
        Rule(pattern=r"^/x$", replacement="file:///f/{{ id .json", env=Environment())


def test_template_replacement_is_compiled_once_at_load(make_request):
    env = Environment()
    rule = Rule(
        pattern=r"^/x/(?P<id>[^/]+)$",
        replacement="file:///f/{{ id }}.json",
        env=env,
    )
    with patch.object(Environment, "from_string", side_effect=AssertionError):
        result = rule.apply(make_request("/x/abc"))
    assert isinstance(result, TemplateRuleResult)
    assert result.template_path == "/f/abc.json"


def test_template_replacement_uses_strict_undefined(make_request):
    """A missing header in a rendered replacement must fail loudly, not render ''."""
    rule = Rule(
        pattern=r"^/x$",
        replacement="file:///fixtures/{{ headers['x-missing'] }}/f.json",
        env=Environment(),
    )
    with pytest.raises(UndefinedError):
        rule.apply(make_request("/x"))


def test_strict_undefined_does_not_leak_into_the_shared_environment():
    env = Environment()
    Rule(pattern=r"^/x$", replacement="file:///{{ id }}", env=env)
    assert env.from_string("[{{ nope }}]").render() == "[]"


def test_method_comparison_is_case_insensitive_but_attribute_is_preserved(
    make_request,
):
    rule = Rule(pattern=r"^/x$", replacement="u", method="get")
    assert rule.method == "get"
    assert rule.matches(make_request("/x", method="GET"))
    assert not rule.matches(make_request("/x", method="POST"))


def test_match_returns_the_path_match(make_request):
    rule = Rule(pattern=r"^/x/(?P<id>[^/]+)$", replacement="u")
    match = rule.match(make_request("/x/abc"))
    assert match is not None and match.group("id") == "abc"
    assert rule.match(make_request("/y")) is None


def test_apply_runs_path_regex_once(make_request):
    rule = Rule(
        pattern=r"^/x/(?P<id>[^/]+)$",
        replacement="file:///f/{{ id }}.json",
        env=Environment(),
    )
    with patch.object(rule, "match", wraps=rule.match) as spy:
        rule.apply(make_request("/x/abc"))
    assert spy.call_count == 1


# --- template context precedence -----------------------------------------------------


def test_reserved_context_keys_win_over_inferred_identifiers(make_request):
    """``/projects/headers/42`` infers an identifier keyed ``headers``; the reserved
    ``headers`` dict must still win."""
    rule = Rule(pattern=r"^/projects/.*$", replacement="file:///f.json")
    result = rule.apply(
        make_request("/projects/headers/42", headers={"x-scenario": "healthy"})
    )
    assert isinstance(result, TemplateRuleResult)
    assert result.template_context["headers"] == {"x-scenario": "healthy"}


def test_named_groups_override_inferred_identifiers(make_request):
    rule = Rule(pattern=r"^/projects/(?P<projects>\d)\d*$", replacement="file:///f")
    result = rule.apply(make_request("/projects/42"))
    assert isinstance(result, TemplateRuleResult)
    assert result.template_context["projects"] == "4"


def test_unmatched_optional_named_group_is_absent_from_context(make_request):
    rule = Rule(pattern=r"^/p(?:/(?P<id>\d+))?$", replacement="file:///f.json")
    result = rule.apply(make_request("/p"))
    assert isinstance(result, TemplateRuleResult)
    assert "id" not in result.template_context
    assert result.template_context["groups"] == (None,)


def test_unmatched_optional_named_group_fails_loudly_in_template_replacement(
    make_request,
):
    rule = Rule(
        pattern=r"^/p(?:/(?P<id>\d+))?$",
        replacement="file:///f/{{ id }}.json",
        env=Environment(),
    )
    with pytest.raises(UndefinedError):
        rule.apply(make_request("/p"))


def test_regex_replacement_does_not_build_template_context(make_request):
    rule = Rule(pattern=r"^/projects/(.*)$", replacement=r"https://h/\1")
    request = make_request("/projects/42")
    with patch(
        "mockstack.rules.parse_template_name_segments_and_identifiers",
        side_effect=AssertionError,
    ):
        result = rule.apply(request)
    assert isinstance(result, URLRuleResult)
    assert result.url == "https://h/42"


# --- lazy, robust payload ------------------------------------------------------------


def test_request_payload_is_parsed_lazily():
    with patch("mockstack.rules.json.loads", side_effect=AssertionError):
        payload = RequestPayload.from_bytes(b'{"a": 1}')
    assert payload.json == {"a": 1}


def test_request_payload_deeply_nested_json_does_not_raise():
    depth = 100_000
    payload = RequestPayload(b"[" * depth + b"]" * depth)
    assert payload.json is None


def test_request_payload_equality_is_field_based():
    a = RequestPayload(b'{"a": 1}')
    b = RequestPayload.from_bytes(b'{"a": 1}')
    assert a.json == {"a": 1}  # populate the cache on one side only
    assert a == b
    assert hash(a) == hash(b)
    assert RequestPayload.empty() == RequestPayload(b"")


def test_backreference_like_text_inside_jinja_expression_is_accepted(make_request):
    """Only literal template text is scanned for backreferences; ``\\1`` inside a Jinja
    string literal is an argument to ``replace``, not a regex backreference."""
    rule = Rule(
        pattern=r"^/x/(?P<id>[^/]+)$",
        replacement=r"file:///f/{{ path | replace('\\1', 'x') }}.json",
        env=Environment(),
    )
    result = rule.apply(make_request("/x/abc"))
    assert isinstance(result, TemplateRuleResult)
    assert result.template_path == "/f//x/abc.json"


def test_backreference_like_text_inside_jinja_comment_is_accepted(make_request):
    rule = Rule(
        pattern=r"^/x/(?P<id>[^/]+)$",
        replacement=r"{# \1 #}{{ id }}",
        env=Environment(),
    )
    result = rule.apply(make_request("/x/abc"))
    assert isinstance(result, URLRuleResult)
    assert result.url == "abc"
