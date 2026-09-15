"""Unit tests for the proxyrules module."""

import gzip
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
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


# Target URL for tests that call reverse_proxy directly; nothing is sent there, since
# those tests patch httpx.AsyncClient.send (see `upstream_send`).
UPSTREAM_URL = "http://upstream.invalid/x"

# The shared rules file's first rule rewrites this path to "/projects/123".
PROJECT_PATH = "/api/v1/projects/123"


@pytest.fixture
def reverse_proxy_strategy(settings_reverse_proxy):
    """A strategy on the shared rules file, in reverse-proxy mode."""
    return ProxyRulesStrategy(settings_reverse_proxy)


# --- loading rules -------------------------------------------------------------------


def test_proxy_rules_strategy_load_rules(proxyrules_strategy):
    """Test loading rules from the rules file."""
    rules = proxyrules_strategy().load_rules()
    assert len(rules) > 0
    assert all(isinstance(rule, Rule) for rule in rules)


def test_load_rules_attaches_jinja_env(proxyrules_strategy):
    strategy = proxyrules_strategy()
    assert all(rule.env is strategy.env for rule in strategy.rules)


def test_proxy_rules_strategy_missing_rules_file(proxyrules_strategy):
    """Test error when rules file is not set."""
    strategy = proxyrules_strategy(proxyrules_rules_filename=None)
    with pytest.raises(ValueError, match="rules_filename is not set"):
        strategy.load_rules()


@pytest.mark.parametrize(
    ("rule", "message"),
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
        (
            {
                "name": "bad-status",
                "pattern": "^/x$",
                "replacement": "file:///f.json",
                "status": 700,
            },
            r"rule 'bad-status': status must be an integer from 200 to 599",
        ),
        (
            {
                "name": "headers-on-url",
                "pattern": "^/x$",
                "replacement": "https://upstream.example/x",
                "response_headers": {"x-a": "1"},
            },
            r"rule 'headers-on-url': status and response_headers only apply to file:/// fixtures",
        ),
    ],
    ids=[
        "invalid-regex",
        "invalid-predicate-regex",
        "reserved-group",
        "template-syntax",
        "predicate-without-value",
        "invalid-status",
        "response-headers-on-url",
    ],
)
def test_invalid_rules_file_fails_at_startup_with_rule_name(proxyrules_strategy, rule, message):
    """A bad rules file fails when the strategy is built (startup), naming the rule."""
    with pytest.raises(ValueError, match=message):
        proxyrules_strategy(rules=[rule])


# --- matching ------------------------------------------------------------------------


def test_proxy_rules_strategy_rule_for(proxyrules_strategy, traced_request):
    """Test finding a matching rule for a request."""
    rule = proxyrules_strategy().rule_for(traced_request(PROJECT_PATH))
    assert rule is not None
    assert isinstance(rule, Rule)


def test_proxy_rules_strategy_rule_for_no_match(proxyrules_strategy, traced_request):
    """Test when no rule matches a request."""
    assert proxyrules_strategy().rule_for(traced_request("/nonexistent/path")) is None


def test_rule_for_prefers_stamped_fixture_then_falls_through(proxyrules_strategy, traced_request):
    strategy = proxyrules_strategy(
        rules=[
            {
                "name": "projects-eval",
                "method": "GET",
                "pattern": r"^/projects/api/v1/project/(?P<id>[^/]+)$",
                "headers": {"x-request-eval-scenario": ".*"},
                "replacement": "file:///fixtures/projects/project.json.j2",
            },
            {
                "name": "projects-passthrough",
                "pattern": r"^/projects/(.*)",
                "replacement": r"https://projects.example/\1",
            },
        ]
    )
    path = "/projects/api/v1/project/abc"
    stamped = strategy.rule_for(traced_request(path, headers={"x-request-eval-scenario": "healthy"}))
    unstamped = strategy.rule_for(traced_request(path))
    assert stamped is not None
    assert stamped.name == "projects-eval"
    assert unstamped is not None
    assert unstamped.name == "projects-passthrough"


# --- apply: redirects, missing rules, simulated creates ------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("redirect_via", "status_code"),
    [
        (
            ProxyRulesRedirectVia.HTTP_TEMPORARY_REDIRECT,
            status.HTTP_307_TEMPORARY_REDIRECT,
        ),
        (
            ProxyRulesRedirectVia.HTTP_PERMANENT_REDIRECT,
            status.HTTP_301_MOVED_PERMANENTLY,
        ),
    ],
    ids=["307", "301"],
)
async def test_proxy_rules_strategy_apply_redirects(proxyrules_strategy, traced_request, redirect_via, status_code):
    """A matching rule redirects to the rewritten path, temporarily or permanently."""
    strategy = proxyrules_strategy(proxyrules_redirect_via=redirect_via)
    response = await strategy.apply(traced_request(PROJECT_PATH))
    assert isinstance(response, RedirectResponse)
    assert response.status_code == status_code
    assert response.headers["location"] == "/projects/123"


@pytest.mark.asyncio
async def test_proxy_rules_strategy_apply_with_fragment(proxyrules_strategy, traced_request):
    """Test applying a rule to a request with URL fragment."""
    request = traced_request(PROJECT_PATH)
    # Set URL with fragment (fragments are client-side only in HTTP, but we test the logic)
    request._url = URL("http://testserver/api/v1/projects/123#section")
    response = await proxyrules_strategy().apply(request)
    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == "/projects/123%23section"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("redirect_via", "status_code"),
    [
        (ProxyRulesRedirectVia.HTTP_TEMPORARY_REDIRECT, 307),
        (ProxyRulesRedirectVia.HTTP_PERMANENT_REDIRECT, 301),
    ],
    ids=["307", "301"],
)
@pytest.mark.parametrize(
    ("replacement", "query_string", "expected_location"),
    [
        (
            r"https://api.example/\1",
            b"status=open",
            "https://api.example/projects/123?status=open",
        ),
        (
            r"https://api.example/\1?source=mockstack",
            b"status=open&page=2",
            "https://api.example/projects/123?source=mockstack&status=open&page=2",
        ),
        (
            r"https://api.example/\1?",
            b"status=open",
            "https://api.example/projects/123?status=open",
        ),
        (
            r"https://api.example/\1#top",
            b"status=open",
            "https://api.example/projects/123?status=open#top",
        ),
        (
            r"https://api.example/\1",
            b"",
            "https://api.example/projects/123",
        ),
    ],
    ids=[
        "query-appended",
        "merged-with-existing-query",
        "target-ending-in-question-mark",
        "query-before-target-fragment",
        "no-query-no-trailing-question-mark",
    ],
)
async def test_redirect_location_keeps_query_string(
    apply_rule,
    traced_request,
    redirect_via,
    status_code,
    replacement,
    query_string,
    expected_location,
):
    """The replacement is resolved from the path only; redirect modes must carry the
    original query string over to ``Location`` (reverse proxy forwards it as params)."""
    response = await apply_rule(
        {
            "name": "redirect-rule",
            "pattern": r"^/api/v1/(.*)$",
            "replacement": replacement,
        },
        traced_request(PROJECT_PATH, query=query_string),
        proxyrules_redirect_via=redirect_via,
    )
    assert response.status_code == status_code
    assert response.headers["location"] == expected_location
    assert response.headers[RESULT_TYPE_HEADER] == "redirect"


@pytest.mark.asyncio
async def test_redirect_response_carries_result_headers(apply_rule, traced_request):
    response = await apply_rule(
        {"pattern": r"^/api/(.*)", "replacement": r"https://api.example/\1"},
        traced_request("/api/x"),
    )
    assert response.headers[RESULT_RULE_HEADER] == r"^/api/(.*)"
    assert response.headers[RESULT_TYPE_HEADER] == "redirect"


@pytest.mark.asyncio
async def test_redirect_result_span_attribute_is_redirect(apply_rule, traced_request, span_attributes):
    """A 307 redirect result sets the span's ``result_type`` to ``redirect``, the same
    as the response's stamped header."""
    await apply_rule(
        {"pattern": r"^/api/(.*)", "replacement": r"https://api.example/\1"},
        traced_request("/api/x"),
        proxyrules_redirect_via=ProxyRulesRedirectVia.HTTP_TEMPORARY_REDIRECT,
    )
    assert span_attributes()["mockstack.proxyrules.result_type"] == "redirect"


@pytest.mark.asyncio
async def test_proxy_rules_strategy_apply_no_match(proxyrules_strategy, traced_request):
    """A request no rule matches is a 404 stamped ``missing``, with no rule header."""
    response = await proxyrules_strategy().apply(traced_request("/nonexistent/path"))
    assert response.status_code == 404
    assert response.headers[RESULT_TYPE_HEADER] == "missing"
    assert RESULT_RULE_HEADER not in response.headers


@pytest.mark.asyncio
async def test_proxy_rules_strategy_apply_invalid_redirect_via(proxyrules_strategy, traced_request):
    """An invalid redirect_via value is an internal failure: apply() answers it as a
    stamped 500 ``error`` rather than letting it propagate to Starlette's
    ServerErrorMiddleware as a bare, unstamped 500.
    """
    strategy = proxyrules_strategy(proxyrules_redirect_via="invalid")
    response = await strategy.apply(traced_request(PROJECT_PATH))
    assert response.status_code == 500
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert RESULT_RULE_HEADER in response.headers
    assert json.loads(response.body) == {"error": "mockstack: internal error"}


@pytest.mark.asyncio
async def test_proxy_rules_strategy_apply_simulate_create(proxyrules_strategy, traced_request):
    """Test simulating resource creation when no rule matches."""
    strategy = proxyrules_strategy(proxyrules_simulate_create_on_missing=True)
    request = traced_request(
        "/nonexistent/path",
        method="POST",
        headers={"content-type": "application/json"},
        body=b'{"name": "test"}',
    )
    response = await strategy.apply(request)
    assert response.status_code == status.HTTP_201_CREATED
    assert response.headers[RESULT_TYPE_HEADER] == "create"
    assert RESULT_RULE_HEADER not in response.headers


@pytest.mark.asyncio
async def test_simulate_create_with_malformed_json_body_is_stamped_500(proxyrules_strategy, traced_request):
    """The create path parses the body with ``request.json()`` (create_mixin is out of
    scope here); a malformed body is an internal failure, answered as a stamped 500
    ``error`` with no rule header since no rule matched.
    """
    strategy = proxyrules_strategy(proxyrules_simulate_create_on_missing=True)
    request = traced_request(
        "/nonexistent/path",
        method="POST",
        headers={"content-type": "application/json"},
        body=b'{"name": ',
    )
    response = await strategy.apply(request)
    assert response.status_code == 500
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert RESULT_RULE_HEADER not in response.headers
    assert json.loads(response.body) == {"error": "mockstack: internal error"}


@pytest.mark.asyncio
async def test_client_disconnect_propagates(proxyrules_strategy, make_request, span):
    """A client that went away gets no answer; ClientDisconnect is not swallowed."""

    async def disconnect():
        return {"type": "http.disconnect"}

    request = Request(make_request(PROJECT_PATH).scope, receive=disconnect)
    request.state.span = span
    with pytest.raises(ClientDisconnect):
        await proxyrules_strategy().apply(request)


# --- apply: templates ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_proxy_rules_strategy_apply_template(apply_rule, traced_request, write_template):
    """Test applying strategy with template rendering."""
    template_file = write_template(
        "template.json",
        '{"projects": "{{ projects }}", "name": "Project {{ projects }}"}',
    )
    response = await apply_rule(
        {
            "pattern": r"/api/v1/projects/(\d+)",
            "replacement": f"file:///{template_file}",
            "name": "test_template_rule",
        },
        traced_request("/api/v1/projects/1234"),
    )
    assert response.status_code == 200
    assert response.media_type == "application/json"
    assert response.body.decode() == '{"projects": "1234", "name": "Project 1234"}'


@pytest.mark.asyncio
async def test_apply_template_rejects_path_traversal(proxyrules_strategy, traced_request, tmp_path):
    """A rendered ``file://`` path containing ``..`` -- e.g. built in part from an
    unconstrained request value such as a header matched by ``.*`` -- must never be
    opened. It 404s without ever calling `open`, and the response body does not echo
    back the rejected path.
    """
    strategy = proxyrules_strategy(
        rules=[
            {
                "pattern": r"^/x$",
                "replacement": f"file://{tmp_path}/fixtures/../../../etc/passwd",
            }
        ]
    )
    with patch("builtins.open") as mock_open:
        response = await strategy.apply(traced_request("/x"))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    mock_open.assert_not_called()
    assert "passwd" not in response.body.decode()
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert json.loads(response.body) == {"error": "Template file not found."}


@pytest.mark.asyncio
async def test_apply_renders_request_json_from_body(apply_rule, traced_request, write_template):
    template_file = write_template("sql.json", '{"echo": {{ request_json.query | tojson }}}')
    response = await apply_rule(
        {
            "pattern": r"^/analytics/v2/sql$",
            "method": "POST",
            "replacement": f"file://{template_file}",
        },
        traced_request(
            "/analytics/v2/sql",
            method="POST",
            headers={"content-type": "application/json"},
            body=b'{"query": "SELECT 1"}',
        ),
    )
    assert response.status_code == 200
    assert response.body == b'{"echo": "SELECT 1"}'


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("file.json", "application/json"),
        ("file.xml", "application/xml"),
        ("file.html", "text/html"),
        ("file.txt", "text/plain"),
        ("file.yaml", "application/x-yaml"),
        ("file.yml", "application/x-yaml"),
        ("file.unknown", "text/plain"),
        ("project.json", "application/json"),
        ("project.json.j2", "application/json"),
        ("project.xml.j2", "application/xml"),
        ("project.j2", "text/plain"),
        ("project", "text/plain"),
    ],
)
def test_proxy_rules_strategy_get_content_type(proxyrules_strategy, filename, expected):
    """The content type follows the file extension, ignoring a trailing ``.j2``."""
    assert proxyrules_strategy()._get_content_type(Path(filename)) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("t-rule", "t-rule"),
        ("日本語ルール", "\\u65e5\\u672c\\u8a9e\\u30eb\\u30fc\\u30eb"),
        ("bad\r\nname", "bad  name"),
    ],
    ids=["plain", "non-latin1-escaped", "crlf-replaced"],
)
async def test_template_response_carries_result_headers(apply_rule, traced_request, write_template, name, expected):
    """A rendered fixture is stamped ``template`` with its rule's name. Starlette encodes
    header values as latin-1 and CR/LF must not leak into a header, so a name outside
    latin-1 is escaped to plain ASCII and control characters become spaces, rather than
    crashing header encoding."""
    template_file = write_template("t.json", '{"ok": true}')
    response = await apply_rule(
        {"name": name, "pattern": r"^/t$", "replacement": f"file://{template_file}"},
        traced_request("/t"),
    )
    assert response.status_code == 200
    assert response.headers[RESULT_TYPE_HEADER] == "template"
    assert response.headers[RESULT_RULE_HEADER] == expected


@pytest.mark.asyncio
async def test_missing_fixture_is_stamped_404_error_without_echoing_path(apply_rule, tmp_path, caplog):
    missing = tmp_path / "secret-scenario" / "project.json.j2"
    with caplog.at_level(logging.ERROR, logger="ProxyRulesStrategy"):
        response = await apply_rule(
            {
                "name": "fixture-rule",
                "pattern": r"^/x$",
                "replacement": f"file://{missing}",
            }
        )
    assert response.status_code == 404
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert response.headers[RESULT_RULE_HEADER] == "fixture-rule"
    assert json.loads(response.body) == {"error": "Template file not found."}
    assert str(missing) in caplog.text


@pytest.mark.asyncio
async def test_missing_fixture_span_attributes_describe_the_rule(apply_rule, tmp_path, span_attributes):
    """A missing-fixture 404, like every other error naming a rule, carries that rule's
    shared attributes and ``result_type = "error"`` -- not only the response headers."""
    missing = tmp_path / "secret-scenario" / "project.json.j2"
    response = await apply_rule(
        {
            "name": "fixture-rule",
            "pattern": r"^/x$",
            "replacement": f"file://{missing}",
        }
    )
    assert response.status_code == 404
    attributes = span_attributes()
    assert attributes["mockstack.proxyrules.rule_name"] == "fixture-rule"
    assert attributes["mockstack.proxyrules.rule_pattern"] == r"^/x$"
    assert attributes["mockstack.proxyrules.result_type"] == "error"


@pytest.mark.asyncio
async def test_fixture_render_failure_is_stamped_500_error(apply_rule, write_template, caplog):
    """A fixture that fails to render is a stamped 500 ``error``, logged once at ERROR
    with the traceback and the fixture path."""
    template_file = write_template("broken.json.j2", '{"x": {{ oops }')
    with caplog.at_level(logging.ERROR, logger="ProxyRulesStrategy"):
        response = await apply_rule(
            {
                "name": "broken-rule",
                "pattern": r"^/x$",
                "replacement": f"file://{template_file}",
            }
        )
    assert response.status_code == 500
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert response.headers[RESULT_RULE_HEADER] == "broken-rule"
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].exc_info is not None
    assert str(template_file) in errors[0].getMessage()


@pytest.mark.asyncio
async def test_undefined_variable_in_replacement_is_stamped_500_error(apply_rule, caplog):
    with caplog.at_level(logging.ERROR, logger="ProxyRulesStrategy"):
        response = await apply_rule(
            {
                "name": "scenario-rule",
                "pattern": r"^/x$",
                "replacement": "file:///fixtures/{{ headers['x-request-eval-scenario'] }}/f.json",
            }
        )
    assert response.status_code == 500
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert response.headers[RESULT_RULE_HEADER] == "scenario-rule"
    assert json.loads(response.body) == {"error": "mockstack: internal error"}
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "scenario-rule" in errors[0].getMessage()
    assert errors[0].exc_info is not None


@pytest.mark.asyncio
async def test_unexpected_error_after_match_is_stamped_500_with_rule(proxyrules_strategy, traced_request):
    strategy = proxyrules_strategy(rules=[{"name": "boom-rule", "pattern": r"^/x$", "replacement": "u"}])
    [rule] = strategy.rules
    with patch.object(rule, "apply", side_effect=RuntimeError("boom")):
        response = await strategy.apply(traced_request("/x"))
    assert response.status_code == 500
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert response.headers[RESULT_RULE_HEADER] == "boom-rule"


@pytest.mark.asyncio
async def test_result_log_line_omits_template_context(apply_rule, traced_request, write_template, caplog):
    template_file = write_template("t.json", '{"ok": true}')
    request = traced_request(
        "/t",
        method="POST",
        headers={"x-secret-token": "hunter2"},
        body=b'{"query": "SELECT confidential"}',
    )
    with caplog.at_level(logging.INFO, logger="ProxyRulesStrategy"):
        response = await apply_rule(
            {
                "name": "t-rule",
                "pattern": r"^/t$",
                "replacement": f"file://{template_file}",
            },
            request,
        )
    assert response.status_code == 200
    assert str(template_file) in caplog.text
    assert "template" in caplog.text
    assert "hunter2" not in caplog.text
    assert "confidential" not in caplog.text


@pytest.mark.asyncio
async def test_result_log_line_for_url_result_logs_target_url(apply_rule, traced_request, caplog):
    request = traced_request("/api/x", headers={"x-secret-token": "hunter2"})
    with caplog.at_level(logging.INFO, logger="ProxyRulesStrategy"):
        await apply_rule(
            {
                "name": "u-rule",
                "pattern": r"^/api/(.*)",
                "replacement": r"https://h/\1",
            },
            request,
        )
    assert "https://h/x" in caplog.text
    assert "hunter2" not in caplog.text


@pytest.mark.asyncio
async def test_handlers_stamp_their_own_result_type(proxyrules_strategy, traced_request, write_template):
    strategy = proxyrules_strategy()  # HTTP_TEMPORARY_REDIRECT
    rule = Rule.from_dict({"name": "r", "pattern": r"^/x$", "replacement": "https://h"})
    request = traced_request("/x")

    redirect = await strategy.handle_url_result(request, rule, URLRuleResult(url="https://h/x"))
    assert redirect.headers[RESULT_TYPE_HEADER] == "redirect"
    assert redirect.headers[RESULT_RULE_HEADER] == "r"

    template_file = write_template("t.json", "{}")
    rendered = await strategy.handle_template_result(
        request,
        rule,
        TemplateRuleResult(template_path=str(template_file), template_context={}),
    )
    assert rendered.headers[RESULT_TYPE_HEADER] == "template"


# --- utf-8 file reads ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rules_and_fixture_files_are_read_as_utf8(proxyrules_strategy, traced_request, write_template):
    """Both ``open()`` calls the strategy makes -- for the rules file and for a matched
    fixture file -- must request UTF-8 explicitly, independent of the machine's locale.
    """
    template_file = write_template("t.json", '{"ok": true}')
    with patch("mockstack.strategies.proxyrules.open", wraps=open, create=True) as mock_open:
        strategy = proxyrules_strategy(rules=[{"pattern": r"^/x$", "replacement": f"file://{template_file}"}])
        response = await strategy.apply(traced_request("/x"))

    assert response.status_code == 200
    # One open() for the rules file (at construction) and one for the fixture (at apply).
    assert len(mock_open.call_args_list) >= 2
    for call in mock_open.call_args_list:
        assert call.kwargs.get("encoding") == "utf-8", call


# Non-ASCII text to prove file reads survive a non-UTF-8 locale: Latin-1 range
# ("Zoë Müller") and beyond it ("日本"), matching the problem this regression test covers.
_NON_ASCII_RULE_NAME = "Zoë Müller"
_NON_ASCII_FIXTURE_BODY = "Zoë Müller 日本"

# Candidate non-UTF-8 locales to probe for, in preference order. CI Linux images often
# ship none of these (they are skipped there); macOS ships several.
_LATIN1_LOCALE_CANDIDATES = (
    "en_US.ISO8859-1",
    "en_US.ISO-8859-1",
    "de_DE.ISO8859-1",
    "C.ISO-8859-1",
)


def _preferred_encoding_under(locale_name: str) -> str | None:
    """The ``locale.getpreferredencoding`` a fresh interpreter reports under
    ``LC_ALL=locale_name`` and ``PYTHONUTF8=0``, or ``None`` if the locale is not
    installed on this machine (a subprocess that fails to set it)."""
    completed = subprocess.run(
        [sys.executable, "-c", "import locale; print(locale.getpreferredencoding(False))"],
        env={**os.environ, "LC_ALL": locale_name, "PYTHONUTF8": "0"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _find_non_utf8_locale() -> str | None:
    for candidate in _LATIN1_LOCALE_CANDIDATES:
        encoding = _preferred_encoding_under(candidate)
        if encoding is not None and encoding.lower().replace("-", "") != "utf8":
            return candidate
    return None


# The subprocess script: reads the rules file and fixture it names (both written as
# UTF-8 by the test, outside this locale), applies one request through the strategy
# directly, and writes the raw response body bytes to stdout -- never text, so nothing
# non-Latin-1 is ever printed through the subprocess's (possibly Latin-1) stdout.
_LOCALE_REGRESSION_SCRIPT = """
import asyncio
import sys
from types import SimpleNamespace

from starlette.requests import Request

from mockstack.config import Settings
from mockstack.strategies.proxyrules import ProxyRulesStrategy

rules_path = sys.argv[1]

settings = Settings(
    strategy="proxyrules",
    proxyrules_rules_filename=rules_path,
    proxyrules_redirect_via="reverse_proxy",
    _env_file=None,
)
strategy = ProxyRulesStrategy(settings)


async def main() -> None:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/x",
            "query_string": b"",
            "headers": [],
        },
        receive=receive,
    )
    request.state.span = SimpleNamespace(set_attribute=lambda *a, **kw: None)
    response = await strategy.apply(request)
    sys.stdout.buffer.write(bytes([response.status_code % 256]))
    sys.stdout.buffer.write(response.body)


asyncio.run(main())
"""


def test_locale_regression_utf8_replay_byte_identical(tmp_path):
    """Regression test for the bug this fix addresses: under a non-UTF-8 locale, a
    fixture recorded/written as UTF-8 must still replay byte-identically, not mojibake.
    """
    locale_name = _find_non_utf8_locale()
    if locale_name is None:
        pytest.skip("no non-UTF-8 locale available on this machine to probe")

    fixture_file = tmp_path / "fixture.txt"
    fixture_file.write_text(_NON_ASCII_FIXTURE_BODY, encoding="utf-8")

    rules_file = tmp_path / "rules.yml"
    rules_file.write_text(
        f"rules:\n  - name: {_NON_ASCII_RULE_NAME!r}\n    pattern: ^/x$\n    replacement: file://{fixture_file}\n",
        encoding="utf-8",
    )

    script_file = tmp_path / "locale_regression.py"
    script_file.write_text(_LOCALE_REGRESSION_SCRIPT, encoding="utf-8")

    # sys.executable running a script this test just wrote to tmp_path: trusted inputs.
    completed = subprocess.run(  # noqa: S603
        [sys.executable, str(script_file), str(rules_file)],
        env={**os.environ, "LC_ALL": locale_name, "PYTHONUTF8": "0"},
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, ascii(completed.stderr)

    status_byte, body = completed.stdout[:1], completed.stdout[1:]
    assert status_byte == bytes([status.HTTP_200_OK % 256]), ascii(completed.stdout)
    assert body == _NON_ASCII_FIXTURE_BODY.encode("utf-8"), (ascii(body), locale_name)


# --- apply: reverse proxy ------------------------------------------------------------


@pytest.mark.asyncio
async def test_proxy_rules_strategy_apply_reverse_proxy(apply_rule, traced_request, upstream_send):
    """In reverse-proxy mode apply() sends the request to the rewritten URL and answers
    with the upstream's response, stamped ``proxy``."""
    upstream_send.return_value = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=b'{"message": "success"}',
    )
    response = await apply_rule(
        {
            "name": "api-passthrough",
            "pattern": r"^/api/(.*)",
            "replacement": r"https://api.example/\1",
        },
        traced_request(PROJECT_PATH),
        proxyrules_redirect_via=ProxyRulesRedirectVia.REVERSE_PROXY,
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.body == b'{"message": "success"}'
    assert response.headers[RESULT_TYPE_HEADER] == "proxy"
    assert response.headers[RESULT_RULE_HEADER] == "api-passthrough"
    upstream_send.assert_awaited_once()
    assert upstream_send.call_args.args[0].url == "https://api.example/v1/projects/123"


@pytest.mark.asyncio
async def test_reverse_proxy_result_span_attribute_is_proxy(apply_rule, traced_request, upstream_send, span_attributes):
    """A plain reverse-proxy URL result (record mode off) sets the span's
    ``result_type`` to ``proxy``, the same as the response's stamped header."""
    upstream_send.return_value = httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}")
    await apply_rule(
        {
            "name": "api-passthrough",
            "pattern": r"^/api/(.*)",
            "replacement": r"https://api.example/\1",
        },
        traced_request(PROJECT_PATH),
        proxyrules_redirect_via=ProxyRulesRedirectVia.REVERSE_PROXY,
    )
    assert span_attributes()["mockstack.proxyrules.result_type"] == "proxy"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code", "message"),
    [
        (httpx.ConnectError("boom"), 502, "mockstack: upstream request failed"),
        (httpx.ReadTimeout("slow"), 504, "mockstack: upstream request timed out"),
    ],
    ids=["connect-error-502", "timeout-504"],
)
async def test_apply_stamps_upstream_failures(
    reverse_proxy_strategy, traced_request, upstream_send, error, status_code, message
):
    """A connection failure or timeout inside the real reverse_proxy must not propagate
    to Starlette's ServerErrorMiddleware as a bare, unstamped 500 -- 'upstream
    unreachable' is the single most common eval failure and the one case the fail-loud
    mechanism must still cover.
    """
    upstream_send.side_effect = error
    response = await reverse_proxy_strategy.apply(traced_request(PROJECT_PATH))
    assert response.status_code == status_code
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert RESULT_RULE_HEADER in response.headers
    assert json.loads(response.body) == {"error": message}


@pytest.mark.asyncio
async def test_upstream_failure_span_attributes_overwrite_proxy_with_error(
    reverse_proxy_strategy, traced_request, upstream_send, span_attributes
):
    """``update_opentelemetry`` sets ``result_type`` to ``proxy`` before the request is
    sent; once the send fails, the error helper in ``apply``'s ``UpstreamError`` handler
    must overwrite it with ``error`` -- span attributes are last-write-wins, like a real
    span -- while still describing the rule that was stamped."""
    upstream_send.side_effect = httpx.ConnectError("boom")
    response = await reverse_proxy_strategy.apply(traced_request(PROJECT_PATH))
    assert response.status_code == 502
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    attributes = span_attributes()
    assert attributes["mockstack.proxyrules.result_type"] == "error"
    assert attributes["mockstack.proxyrules.rule_method"] == "GET"
    assert attributes["mockstack.proxyrules.rule_pattern"] == r"/api/v1/projects/(\d+)"


@pytest.mark.asyncio
async def test_upstream_error_is_logged_as_warning_without_traceback(
    reverse_proxy_strategy, traced_request, upstream_send, caplog
):
    upstream_send.side_effect = httpx.ConnectError("c")
    with caplog.at_level(logging.WARNING, logger="ProxyRulesStrategy"):
        await reverse_proxy_strategy.apply(traced_request(PROJECT_PATH))
    records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert [r.levelname for r in records] == ["WARNING"]
    assert records[0].exc_info is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target",
    ["/target", "http://example.com:abc/"],
    ids=["relative-url-unsupported-protocol", "invalid-url"],
)
async def test_invalid_upstream_url_is_internal_error(apply_rule, caplog, target):
    """A replacement that is not a usable absolute URL is a rules-file mistake, not an
    upstream failure: a stamped 500 ``error``, logged at ERROR with the rule name and
    the target URL (not a 502 at WARNING)."""
    with caplog.at_level(logging.WARNING, logger="ProxyRulesStrategy"):
        response = await apply_rule(
            {"name": "bad-target", "pattern": r"^/x$", "replacement": target},
            proxyrules_redirect_via=ProxyRulesRedirectVia.REVERSE_PROXY,
        )
    assert response.status_code == 500
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert response.headers[RESULT_RULE_HEADER] == "bad-target"
    assert json.loads(response.body) == {"error": "mockstack: internal error"}
    records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert [r.levelname for r in records] == ["ERROR"]
    assert "bad-target" in records[0].getMessage()
    assert target in records[0].getMessage()


@pytest.mark.asyncio
async def test_proxy_rules_strategy_reverse_proxy(reverse_proxy_strategy, make_request, upstream_send):
    """reverse_proxy sends the method, body and query string to the target URL, with
    the target's host, and answers with the upstream's response."""
    upstream_send.return_value = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=b'{"message": "success"}',
    )
    request = make_request(
        "/test",
        method="POST",
        headers={"host": "example.com", "content-type": "application/json"},
        query=b"key=value",
        body=b'{"data": "test"}',
    )

    response = await reverse_proxy_strategy.reverse_proxy(request, "https://api.target.com/test")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.body == b'{"message": "success"}'

    upstream_send.assert_awaited_once()
    sent = upstream_send.call_args.args[0]
    assert sent.method == "POST"
    assert sent.url == "https://api.target.com/test?key=value"
    assert sent.content == b'{"data": "test"}'
    assert sent.headers["host"] == "api.target.com"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "status_code"),
    [
        (httpx.ConnectTimeout("t"), 504),
        (httpx.ReadTimeout("t"), 504),
        (httpx.ConnectError("c"), 502),
        (httpx.RemoteProtocolError("p"), 502),
    ],
)
async def test_reverse_proxy_translates_httpx_errors(
    reverse_proxy_strategy, make_request, upstream_send, exc, status_code
):
    upstream_send.side_effect = exc
    with pytest.raises(UpstreamError) as info:
        await reverse_proxy_strategy.reverse_proxy(make_request("/x"), UPSTREAM_URL)
    assert info.value.status_code == status_code
    assert info.value.__cause__ is exc


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("encoding", "upstream_body", "expected_body", "expected_encoding"),
    [
        ("gzip", gzip.compress(b'{"ok":true}'), b'{"ok":true}', "identity"),
        (
            "compress",
            b"\x1f\x9d-lzw-compressed-bytes",
            b"\x1f\x9d-lzw-compressed-bytes",
            "compress",
        ),
    ],
    ids=["decoded-gzip-relabelled", "undecoded-compress-kept"],
)
async def test_reverse_proxy_response_body_encoding(
    reverse_proxy_strategy,
    make_request,
    upstream_send,
    encoding,
    upstream_body,
    expected_body,
    expected_encoding,
):
    """httpx decodes gzip, so that body is forwarded decoded and relabelled
    ``identity``; a coding httpx skips reaches the client still encoded, and labelled so.
    Either way content-length is the length of the forwarded body."""
    upstream_send.return_value = httpx.Response(200, headers={"content-encoding": encoding}, content=upstream_body)
    response = await reverse_proxy_strategy.reverse_proxy(make_request("/x"), UPSTREAM_URL)
    assert response.body == expected_body
    assert response.headers["content-encoding"] == expected_encoding
    assert response.headers["content-length"] == str(len(expected_body))


@pytest.mark.asyncio
async def test_reverse_proxy_preserves_repeated_response_headers(reverse_proxy_strategy, make_request, upstream_send):
    """Upstream headers are copied item by item, so repeated ones such as Set-Cookie
    survive; the upstream's date and server are dropped, since uvicorn adds its own."""
    body = b'{"ok":true}'
    upstream_send.return_value = httpx.Response(
        200,
        headers=[
            ("date", "Mon, 01 Jan 2024 00:00:00 GMT"),
            ("server", "upstream/1.0"),
            ("content-type", "application/json"),
            ("set-cookie", "first=1; Path=/"),
            ("set-cookie", "second=2; Path=/"),
        ],
        content=body,
    )
    response = await reverse_proxy_strategy.reverse_proxy(make_request("/x"), UPSTREAM_URL)
    names = [name for name, _ in response.raw_headers]
    assert b"date" not in names
    assert b"server" not in names
    assert [v for k, v in response.raw_headers if k == b"set-cookie"] == [
        b"first=1; Path=/",
        b"second=2; Path=/",
    ]
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-length"] == str(len(body))
    assert response.body == body


@pytest.mark.asyncio
async def test_reverse_proxy_head_keeps_upstream_content_length(reverse_proxy_strategy, make_request, upstream_send):
    upstream_send.return_value = httpx.Response(
        200,
        headers=[("content-type", "application/json"), ("content-length", "1234")],
    )
    response = await reverse_proxy_strategy.reverse_proxy(make_request("/x", method="HEAD"), UPSTREAM_URL)
    assert response.headers["content-length"] == "1234"
    assert response.body == b""


# --- request and response headers ----------------------------------------------------


@pytest.mark.parametrize(
    ("headers", "forwarded", "stripped"),
    [
        (
            {"host": "example.com", "user-agent": "test", "accept": "application/json"},
            {
                "host": "api.target.com",
                "user-agent": "test",
                "accept": "application/json",
            },
            [],
        ),
        (
            {
                "host": "example.com",
                "transfer-encoding": "chunked",
                "content-length": "5",
                "connection": "keep-alive",
                "x-request-eval-scenario": "healthy",
            },
            {"host": "api.target.com", "x-request-eval-scenario": "healthy"},
            ["transfer-encoding", "content-length", "connection"],
        ),
        (
            {
                "host": "example.com",
                "connection": "keep-alive, X-Custom-Hop",
                "x-custom-hop": "1",
                "x-kept": "yes",
            },
            {"host": "api.target.com", "x-kept": "yes"},
            ["connection", "x-custom-hop"],
        ),
    ],
    ids=[
        "host-rewritten",
        "framing-and-hop-by-hop-stripped",
        "connection-listed-stripped",
    ],
)
def test_proxy_rules_strategy_reverse_proxy_headers(proxyrules_strategy, headers, forwarded, stripped):
    """Forwarded request headers get the target's host and lose hop-by-hop and framing
    headers (httpx recomputes those); everything else is forwarded as is."""
    out = proxyrules_strategy().reverse_proxy_headers(Headers(headers), "https://api.target.com/path")
    for name, value in forwarded.items():
        assert out[name] == value
    for name in stripped:
        assert name not in out


def test_proxy_rules_strategy_update_opentelemetry(proxyrules_strategy, traced_request, span):
    """Test OpenTelemetry span updates."""
    request = traced_request("/test")
    rule = Rule(pattern="/test", replacement="/target", method="GET", name="test_rule")

    proxyrules_strategy().update_opentelemetry(request, rule, "/target", result_type="proxy")

    span.set_attribute.assert_any_call("mockstack.proxyrules.rule_name", "test_rule")
    span.set_attribute.assert_any_call("mockstack.proxyrules.rule_method", "GET")
    span.set_attribute.assert_any_call("mockstack.proxyrules.rule_pattern", "/test")
    span.set_attribute.assert_any_call("mockstack.proxyrules.rule_replacement", "/target")
    span.set_attribute.assert_any_call("mockstack.proxyrules.rewritten_url", "/target")
    span.set_attribute.assert_any_call("mockstack.proxyrules.result_type", "proxy")


def test_maybe_update_response_headers_describes_buffered_body():
    """The body is buffered and decoded: a decoded coding is relabelled, transfer-encoding
    dropped and content-length set to the buffered length; other headers are kept."""
    updated = maybe_update_response_headers(
        httpx.Headers(
            {
                "content-encoding": "gzip",
                "transfer-encoding": "chunked",
                "content-type": "application/json",
            }
        ),
        content_length=42,
        status_code=200,
        request_method="GET",
    )
    assert updated["content-encoding"] == "identity"
    assert "transfer-encoding" not in updated
    assert updated["content-length"] == "42"
    assert updated["content-type"] == "application/json"


@pytest.mark.parametrize("status_code", [204, 304])
def test_maybe_update_response_headers_omits_content_length_for_204_304(status_code):
    """RFC 9110 §8.6: a server MUST NOT send Content-Length on a 204, and on a 304 the
    value must match what the 200 would have carried -- ``0`` would be a lie. Neither
    status should carry a content-length header at all.
    """
    response_headers = httpx.Headers({"content-length": "1234", "content-type": "application/json"})

    updated_headers = maybe_update_response_headers(
        response_headers=response_headers,
        content_length=0,
        status_code=status_code,
        request_method="GET",
    )

    assert "content-length" not in updated_headers


@pytest.mark.parametrize(
    ("upstream_headers", "expected_encoding", "expected_length"),
    [
        ({"content-length": "1234"}, None, "1234"),
        ({}, None, None),
        (
            {"content-encoding": "compress", "content-length": "1234"},
            "compress",
            "1234",
        ),
        (
            {"content-encoding": "identity", "content-length": "1234"},
            "identity",
            "1234",
        ),
        ({"content-encoding": "gzip", "content-length": "1234"}, "identity", None),
    ],
    ids=[
        "length-kept",
        "absent-length-not-added",
        "undecoded-coding-keeps-length",
        "identity-keeps-length",
        "decoded-coding-drops-length",
    ],
)
def test_maybe_update_response_headers_head_content_length(upstream_headers, expected_encoding, expected_length):
    """A HEAD response has no body, so the buffered length (0) says nothing; the
    upstream's Content-Length describes the GET representation and must survive (as must
    its absence). Once a coding is relabelled (a GET would be decoded) that length is the
    encoded one and wrong, so it is dropped; nothing decoded (or only the no-op
    ``identity``) leaves it standing."""
    updated = maybe_update_response_headers(
        httpx.Headers({"content-type": "application/json", **upstream_headers}),
        content_length=0,
        status_code=200,
        request_method="HEAD",
    )
    assert updated.get("content-encoding") == expected_encoding
    assert updated.get("content-length") == expected_length


# httpx only decodes the codings in SUPPORTED_DECODERS (br / zstd only when brotli /
# zstandard are installed) and silently skips the rest.
BROTLI_DECODED = "br" in SUPPORTED_DECODERS
ZSTD_DECODED = "zstd" in SUPPORTED_DECODERS


@pytest.mark.parametrize(
    ("encoding", "expected"),
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
def test_maybe_update_response_headers_relabels_only_decoded_encodings(encoding, expected):
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


def test_maybe_update_response_headers_strips_connection_listed_headers():
    updated = maybe_update_response_headers(
        httpx.Headers({"connection": "x-upstream-hop", "x-upstream-hop": "1"}),
        content_length=0,
        status_code=200,
        request_method="GET",
    )
    assert "x-upstream-hop" not in updated
    assert "connection" not in updated


def test_maybe_update_response_headers_drops_upstream_date_and_server():
    """The ASGI server (uvicorn) always prepends its own ``date`` and ``server``
    headers without checking the app's; forwarding the upstream's too would duplicate
    them."""
    updated = maybe_update_response_headers(
        httpx.Headers(
            [
                ("Date", "Mon, 01 Jan 2024 00:00:00 GMT"),
                ("Server", "upstream/1.0"),
                ("content-type", "application/json"),
            ]
        ),
        content_length=2,
        status_code=200,
        request_method="GET",
    )
    assert "date" not in updated
    assert "server" not in updated
    assert updated["content-type"] == "application/json"


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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ok", "ok"),
        ("  bad\x00name\x7f ", "bad name"),
        ("bad\x00name\x0bwith\x7fcontrol\r\nchars", "bad name with control  chars"),
        ("\r\n\t", "unnamed"),
        ("", "unnamed"),
        ("日本", "\\u65e5\\u672c"),
    ],
    ids=[
        "plain",
        "control-characters-trimmed",
        "every-ascii-control-character",
        "only-control-characters",
        "empty",
        "non-ascii-escaped",
    ],
)
def test_header_safe_strips_and_falls_back(value, expected):
    """Every ASCII control character (CR/LF, but also NUL, VT, DEL), which h11 rejects,
    becomes a space; surrounding whitespace is trimmed, non-ASCII is escaped, and an
    empty result falls back to ``unnamed``."""
    assert _header_safe(value) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [(12345, "12345"), ("\r\n", "unnamed")],
    ids=["non-string-name", "name-sanitised-to-empty"],
)
def test_with_result_headers_stamps_header_safe_rule_name(name, expected):
    rule = Rule(pattern=r"^/x$", replacement="u")
    rule.name = name  # bypass the constructor's str coercion
    response = with_result_headers(Response(), rule=rule, result_type="proxy")
    assert response.headers[RESULT_RULE_HEADER] == expected


# --- fixture status and response headers ---------------------------------------------


@pytest.mark.asyncio
async def test_fixture_rule_status_and_response_headers(apply_rule, write_template):
    """A fixture served with its rule's status and headers is still stamped ``template``:
    ``error`` stays reserved for mockstack's own failures."""
    template_file = write_template("unavailable.json.j2", '{"error": "unavailable", "path": {{ path | tojson }}}')
    response = await apply_rule(
        {
            "name": "outage",
            "pattern": r"^/x$",
            "replacement": f"file://{template_file}",
            "status": 503,
            "response_headers": {"Retry-After": 30, "Set-Cookie": ["a=1", "b=2"]},
        }
    )
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/json"
    assert response.headers["retry-after"] == "30"
    assert response.headers.getlist("set-cookie") == ["a=1", "b=2"]
    assert response.headers[RESULT_TYPE_HEADER] == "template"
    assert response.headers[RESULT_RULE_HEADER] == "outage"
    assert json.loads(response.body) == {"error": "unavailable", "path": "/x"}


@pytest.mark.asyncio
async def test_response_headers_content_type_replaces_the_suffix_content_type(apply_rule, write_template):
    template_file = write_template("problem.json.j2", '{"title": "Forbidden"}')
    response = await apply_rule(
        {
            "pattern": r"^/x$",
            "replacement": f"file://{template_file}",
            "status": 403,
            "response_headers": {"Content-Type": "application/problem+json"},
        }
    )
    assert response.status_code == 403
    assert response.headers.getlist("content-type") == ["application/problem+json"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [204, 304])
async def test_bodyless_fixture_status_sends_no_body(apply_rule, write_template, status_code):
    """RFC 9110: a 204 or 304 has no content, whatever the fixture renders."""
    template_file = write_template("ignored.json.j2", '{"ignored": true}')
    response = await apply_rule(
        {"pattern": r"^/x$", "replacement": f"file://{template_file}", "status": status_code},
    )
    assert response.status_code == status_code
    assert response.body == b""
    assert "content-length" not in response.headers
    assert "content-type" not in response.headers
    assert response.headers[RESULT_TYPE_HEADER] == "template"


@pytest.mark.asyncio
async def test_status_and_headers_do_not_apply_to_a_missing_fixture(apply_rule, tmp_path):
    response = await apply_rule(
        {
            "name": "outage",
            "pattern": r"^/x$",
            "replacement": f"file://{tmp_path}/missing.json",
            "status": 503,
            "response_headers": {"Retry-After": "30"},
        }
    )
    assert response.status_code == 404
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert "retry-after" not in response.headers


@pytest.mark.asyncio
async def test_status_on_rule_whose_replacement_renders_a_url_is_stamped_500(apply_rule, caplog):
    with caplog.at_level(logging.ERROR, logger="ProxyRulesStrategy"):
        response = await apply_rule(
            {
                "name": "dynamic",
                "pattern": r"^/(?P<rest>.*)$",
                "replacement": "https://upstream.invalid/{{ rest }}",
                "status": 503,
            }
        )
    assert response.status_code == 500
    assert response.headers[RESULT_TYPE_HEADER] == "error"
    assert response.headers[RESULT_RULE_HEADER] == "dynamic"
    assert json.loads(response.body) == {"error": "mockstack: internal error"}
    assert "status and response_headers only apply to file:/// fixtures" in caplog.text
