"""Live tests for the proxyrules cookbook (``docs/guides/proxyrules-cookbook.md``).

Each recipe's rules file and fixtures are loaded from ``examples/proxyrules-cookbook/``
(never re-typed here), with ``${FIXTURES_DIR}`` and ``${UPSTREAM_URL}`` substituted the
way the example README's ``envsubst`` step does. Every ``curl`` command shown on the
page is a constant below, executed as written against a live mockstack, one test per
command; ``test_every_documented_curl_is_tested`` keeps the page and this module in step.
"""

import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
import yaml


pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parents[3]
COOKBOOK_DIR = REPO_ROOT / "examples" / "proxyrules-cookbook"
COOKBOOK_PAGE = REPO_ROOT / "docs" / "guides" / "proxyrules-cookbook.md"
README = REPO_ROOT / "README.md"

# The mockstack address the page uses; requests go to the live server instead.
DOCS_MOCKSTACK_URL = "http://127.0.0.1:8000"

# Recipe 1: serve fixtures to tagged test traffic, pass everything else through.
R1_TAGGED = 'curl -i -H "X-Test-Run: ci-42" http://127.0.0.1:8000/projects/api/v1/project/proj-123'
R1_UNTAGGED = "curl -i http://127.0.0.1:8000/projects/api/v1/project/proj-123"
R1_TAGGED_WITHOUT_FIXTURE_RULE = (
    'curl -i -H "X-Test-Run: ci-42" "http://127.0.0.1:8000/projects/api/v1/projects?page=2"'
)

# Recipe 2: per-scenario fixture directories selected by a header.
R2_HEALTHY = 'curl -i -H "X-Test-Scenario: healthy" http://127.0.0.1:8000/projects/api/v1/project/proj-123'
R2_ARCHIVED = 'curl -i -H "X-Test-Scenario: archived" http://127.0.0.1:8000/projects/api/v1/project/proj-123'
R2_UNKNOWN_SCENARIO = 'curl -i -H "X-Test-Scenario: flaky" http://127.0.0.1:8000/projects/api/v1/project/proj-123'
R2_PREDICATE_MISMATCH = 'curl -i -H "X-Test-Scenario: Healthy" http://127.0.0.1:8000/projects/api/v1/project/proj-123'

# Recipe 3: mock a single-endpoint SQL gateway by request body.
R3_SALES_FACTS = """curl -i -H "Content-Type: application/json" \\
  -d '{"query": "SELECT region, SUM(amount) AS total FROM sales_facts GROUP BY region"}' \\
  http://127.0.0.1:8000/analytics/v1/sql"""
R3_OTHER_TABLE = """curl -i -H "Content-Type: application/json" \\
  -d '{"query": "SELECT id FROM orders LIMIT 10"}' \\
  http://127.0.0.1:8000/analytics/v1/sql"""

# Recipe 4: match JSON literals.
R4_BOOLEAN = """curl -i -H "Content-Type: application/json" -d '{"filter": {"express": true}}' http://127.0.0.1:8000/orders/api/v1/search"""
R4_STRING_TRUE = """curl -i -H "Content-Type: application/json" -d '{"filter": {"express": "true"}}' http://127.0.0.1:8000/orders/api/v1/search"""
R4_NULL = """curl -i -H "Content-Type: application/json" -d '{"filter": {"assignee": null}}' http://127.0.0.1:8000/orders/api/v1/search"""
R4_ABSENT = """curl -i -H "Content-Type: application/json" -d '{"filter": {"status": "OPEN"}}' http://127.0.0.1:8000/orders/api/v1/search"""
R4_NUMBER = """curl -i -H "Content-Type: application/json" -d '{"page": {"number": 1, "size": 50}}' http://127.0.0.1:8000/orders/api/v1/search"""
R4_NUMBER_EXPONENT = """curl -i -H "Content-Type: application/json" -d '{"page": {"number": 1, "size": 5e1}}' http://127.0.0.1:8000/orders/api/v1/search"""
R4_OBJECT = """curl -i -H "Content-Type: application/json" -d '{"filter": {"customer": {"tier": "gold", "id": 42}}}' http://127.0.0.1:8000/orders/api/v1/search"""

# Recipe 5: query-parameter predicates.
R5_PAGE = 'curl -i "http://127.0.0.1:8000/users/api/v1/users?page=2"'
R5_FIRST_MATCHING_RULE = 'curl -i "http://127.0.0.1:8000/users/api/v1/users?status=archived&page=2"'
R5_REPEATED_LAST_MATCHES = 'curl -i "http://127.0.0.1:8000/users/api/v1/users?status=active&status=archived"'
R5_REPEATED_LAST_DIFFERS = 'curl -i "http://127.0.0.1:8000/users/api/v1/users?status=archived&status=active"'

# Recipe 6: reading error results.
R6_MISSING_FIXTURE = "curl -i http://127.0.0.1:8000/users/api/v1/users/user-2"
R6_REPLACEMENT_ERROR = "curl -i http://127.0.0.1:8000/tenants/tenant-a/projects"
R6_FIXTURE_RENDER_ERROR = "curl -i http://127.0.0.1:8000/orders/api/v1/echo"
R6_RELATIVE_URL = "curl -i http://127.0.0.1:8000/accounts/v1/balance"
R6_UPSTREAM_FAILED = "curl -i http://127.0.0.1:8000/invoices/api/v1/invoices"
R6_UPSTREAM_TIMEOUT = "curl -i http://127.0.0.1:8000/reports/daily"

# Recipe 7: redirect mode versus reverse proxy.
R7_FIXTURE = "curl -i http://127.0.0.1:8000/users/api/v1/users/user-1"
R7_REDIRECT = "curl -i http://127.0.0.1:8000/users/api/v1/users/user-2"
R7_FOLLOW_REDIRECT = "curl -i -L http://127.0.0.1:8000/users/api/v1/users/user-2"
R7_QUERY_KEPT = 'curl -i "http://127.0.0.1:8000/users/api/v1/users?page=2"'

TESTED_CURLS = {name: value for name, value in dict(globals()).items() if re.fullmatch(r"R\d_[A-Z0-9_]+", name)}


def curl(command: str, base_url: str) -> httpx.Response:
    """Run a documented ``curl`` command, as written, against mockstack at ``base_url``.

    Supports the flags the cookbook uses: ``-i`` (ignored), ``-L``, ``-H``, ``-d``
    (which, as in curl, implies POST and a form content type unless one is given).
    """
    args = shlex.split(command.replace("\\\n", " "))
    assert args.pop(0) == "curl"
    headers = httpx.Headers()
    data: bytes | None = None
    follow_redirects = False
    url: str | None = None
    it = iter(args)
    for arg in it:
        if arg == "-i":
            continue
        if arg == "-L":
            follow_redirects = True
        elif arg == "-H":
            name, _, value = next(it).partition(":")
            headers[name.strip()] = value.strip()
        elif arg == "-d":
            data = next(it).encode()
        elif arg.startswith(DOCS_MOCKSTACK_URL):
            url = base_url + arg.removeprefix(DOCS_MOCKSTACK_URL)
        else:
            raise ValueError(f"unsupported curl argument: {arg!r}")
    assert url is not None, command
    if data is not None:
        headers.setdefault("content-type", "application/x-www-form-urlencoded")
    return httpx.request(
        "POST" if data is not None else "GET",
        url,
        headers=headers,
        content=data,
        follow_redirects=follow_redirects,
        timeout=10,
    )


def assert_result(response: httpx.Response, status: int, result: str, rule: str | None) -> None:
    actual = (
        response.status_code,
        response.headers.get("x-mockstack-result"),
        response.headers.get("x-mockstack-rule"),
    )
    assert actual == (status, result, rule)


@pytest.fixture(scope="module")
def cookbook(upstream, render_rules, mockstack_server) -> Callable[..., str]:
    """Factory: start mockstack on one recipe's real rules file and fixtures, for the
    rest of this module; returns its base URL."""

    def _start(recipe: str, **overrides: Any) -> str:
        recipe_dir = COOKBOOK_DIR / recipe
        # Like `envsubst '${FIXTURES_DIR} ${UPSTREAM_URL}'`.
        rules_file = render_rules(
            recipe_dir / "rules.yml",
            FIXTURES_DIR=str(recipe_dir / "fixtures"),
            UPSTREAM_URL=upstream.base_url,
        )
        base_url: str = mockstack_server(rules_file, **overrides).base_url
        return base_url

    return _start


# --- Recipe 1 ---------------------------------------------------------------


@pytest.fixture(scope="module")
def recipe1(cookbook):
    return cookbook("01-tagged-traffic")


def test_recipe1_tagged_request_gets_fixture(recipe1, upstream):
    r = curl(R1_TAGGED, recipe1)
    assert_result(r, 200, "template", "projects-fixture")
    assert r.json() == {
        "id": "proj-123",
        "name": "Test project",
        "status": "ACTIVE",
        "test_run": "ci-42",
    }
    assert upstream.calls == []


def test_recipe1_untagged_request_passes_through(recipe1, upstream):
    r = curl(R1_UNTAGGED, recipe1)
    assert_result(r, 200, "proxy", "projects-passthrough")
    assert r.json()["source"] == "upstream"
    assert r.json()["path"] == "/api/v1/project/proj-123"
    assert [c["path"] for c in upstream.calls] == ["/api/v1/project/proj-123"]


def test_recipe1_tagged_request_without_fixture_rule_passes_through(recipe1, upstream):
    r = curl(R1_TAGGED_WITHOUT_FIXTURE_RULE, recipe1)
    assert_result(r, 200, "proxy", "projects-passthrough")
    assert r.json()["path"] == "/api/v1/projects"
    assert [(c["path"], c["query"]) for c in upstream.calls] == [("/api/v1/projects", {"page": "2"})]


# --- Recipe 2 ---------------------------------------------------------------


@pytest.fixture(scope="module")
def recipe2(cookbook):
    return cookbook("02-scenario-directories")


def test_recipe2_healthy_scenario(recipe2, upstream):
    r = curl(R2_HEALTHY, recipe2)
    assert_result(r, 200, "template", "projects-scenario")
    assert r.json() == {"id": "proj-123", "status": "ACTIVE", "scenario": "healthy"}
    assert upstream.calls == []


def test_recipe2_archived_scenario(recipe2, upstream):
    r = curl(R2_ARCHIVED, recipe2)
    assert_result(r, 200, "template", "projects-scenario")
    assert r.json() == {"id": "proj-123", "status": "ARCHIVED", "scenario": "archived"}
    assert upstream.calls == []


def test_recipe2_unknown_scenario_is_a_404_error_not_a_passthrough(recipe2, upstream):
    r = curl(R2_UNKNOWN_SCENARIO, recipe2)
    assert_result(r, 404, "error", "projects-scenario")
    assert r.json() == {"error": "Template file not found."}
    assert upstream.calls == []


def test_recipe2_value_failing_the_predicate_passes_through(recipe2, upstream):
    r = curl(R2_PREDICATE_MISMATCH, recipe2)
    assert_result(r, 200, "proxy", "projects-passthrough")
    assert r.json()["path"] == "/api/v1/project/proj-123"
    assert len(upstream.calls) == 1


# --- Recipe 3 ---------------------------------------------------------------


@pytest.fixture(scope="module")
def recipe3(cookbook):
    return cookbook("03-sql-gateway")


def test_recipe3_sales_facts_query_gets_fixture(recipe3, upstream):
    r = curl(R3_SALES_FACTS, recipe3)
    assert_result(r, 200, "template", "sales-facts-query")
    assert r.headers["content-type"] == "application/json"
    assert r.json() == {
        "columns": ["region", "total"],
        "rows": [["north", 1250.0], ["south", 980.5]],
        "request": {"query": "SELECT region, SUM(amount) AS total FROM sales_facts GROUP BY region"},
    }
    assert upstream.calls == []


def test_recipe3_other_query_passes_through(recipe3, upstream):
    r = curl(R3_OTHER_TABLE, recipe3)
    assert_result(r, 200, "proxy", "analytics-passthrough")
    assert r.json()["path"] == "/v1/sql"
    assert len(upstream.calls) == 1
    assert json.loads(upstream.calls[0]["body"]) == {"query": "SELECT id FROM orders LIMIT 10"}


# --- Recipe 4 ---------------------------------------------------------------

ORDERS_FIXTURE = {"orders": [{"id": "ord-1001", "status": "OPEN"}], "total": 1}


@pytest.fixture(scope="module")
def recipe4(cookbook):
    return cookbook("04-json-literals")


def test_recipe4_boolean(recipe4, upstream):
    r = curl(R4_BOOLEAN, recipe4)
    assert_result(r, 200, "template", "express-orders")
    assert r.json() == ORDERS_FIXTURE
    assert upstream.calls == []


def test_recipe4_string_true_also_matches(recipe4):
    r = curl(R4_STRING_TRUE, recipe4)
    assert_result(r, 200, "template", "express-orders")
    assert r.json() == ORDERS_FIXTURE


def test_recipe4_null(recipe4):
    r = curl(R4_NULL, recipe4)
    assert_result(r, 200, "template", "unassigned-orders")
    assert r.json() == ORDERS_FIXTURE


def test_recipe4_absent_is_not_null(recipe4, upstream):
    r = curl(R4_ABSENT, recipe4)
    assert_result(r, 200, "proxy", "orders-passthrough")
    assert [c["path"] for c in upstream.calls] == ["/api/v1/search"]


def test_recipe4_number(recipe4):
    r = curl(R4_NUMBER, recipe4)
    assert_result(r, 200, "template", "page-size-50")
    assert r.json() == ORDERS_FIXTURE


def test_recipe4_number_is_reserialised(recipe4, upstream):
    r = curl(R4_NUMBER_EXPONENT, recipe4)
    assert_result(r, 200, "proxy", "orders-passthrough")
    assert len(upstream.calls) == 1


def test_recipe4_nested_object(recipe4):
    r = curl(R4_OBJECT, recipe4)
    assert_result(r, 200, "template", "gold-customer")
    assert r.json() == ORDERS_FIXTURE


# --- Recipe 5 ---------------------------------------------------------------


@pytest.fixture(scope="module")
def recipe5(cookbook):
    return cookbook("05-query-parameters")


def test_recipe5_page(recipe5, upstream):
    r = curl(R5_PAGE, recipe5)
    assert_result(r, 200, "template", "users-page")
    assert r.json() == {"page": 2, "per_page": 2, "users": ["user-1", "user-2"]}
    assert upstream.calls == []


def test_recipe5_first_matching_rule_wins(recipe5):
    r = curl(R5_FIRST_MATCHING_RULE, recipe5)
    assert_result(r, 200, "template", "archived-users")
    assert r.json() == {"status": "archived", "users": ["user-9"]}


def test_recipe5_repeated_parameter_uses_last_value(recipe5):
    r = curl(R5_REPEATED_LAST_MATCHES, recipe5)
    assert_result(r, 200, "template", "archived-users")
    assert r.json() == {"status": "archived", "users": ["user-9"]}


def test_recipe5_repeated_parameter_with_other_last_value_passes_through(recipe5, upstream):
    r = curl(R5_REPEATED_LAST_DIFFERS, recipe5)
    assert_result(r, 200, "proxy", "users-passthrough")
    assert r.json()["path"] == "/api/v1/users"
    assert len(upstream.calls) == 1


# --- Recipe 6 ---------------------------------------------------------------

FIXTURE_ASSERTIONS = COOKBOOK_DIR / "06-asserting-in-tests" / "fixture_assertions.py"


@pytest.fixture(scope="module")
def recipe6(cookbook):
    # The page starts this recipe with MOCKSTACK__PROXYRULES_REVERSE_PROXY_TIMEOUT=1.
    return cookbook("06-asserting-in-tests", proxyrules_reverse_proxy_timeout=1.0)


def _load_fixture_assertions() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cookbook_fixture_assertions", FIXTURE_ASSERTIONS)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_recipe6_snippet_passes_against_fixture(recipe6):
    """Run the snippet with pytest, as the page shows."""
    # A fixed argument list: this interpreter running pytest on the shipped snippet.
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", FIXTURE_ASSERTIONS.name],
        cwd=FIXTURE_ASSERTIONS.parent,
        env={
            **os.environ,
            "MOCKSTACK_URL": recipe6,
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout


def test_recipe6_snippet_fails_when_request_is_proxied(recipe6, upstream):
    checks = _load_fixture_assertions()
    untagged = httpx.get(f"{recipe6}/projects/api/v1/project/proj-123")
    with pytest.raises(AssertionError, match="X-Mockstack-Result='proxy'"):
        checks.expect_fixture(untagged, rule="project-fixture")
    assert len(upstream.calls) == 1


def test_recipe6_missing_fixture_is_404(recipe6, upstream):
    r = curl(R6_MISSING_FIXTURE, recipe6)
    assert_result(r, 404, "error", "user-fixture")
    assert r.json() == {"error": "Template file not found."}
    assert upstream.calls == []


def test_recipe6_fixture_path_rendered_from_named_group_is_served(recipe6, upstream):
    """The page embeds the one user fixture that exists: ``user-fixture`` renders its
    file name from the ``user_id`` group, so user-1 is served where user-2 is a 404."""
    r = httpx.get(f"{recipe6}/users/api/v1/users/user-1")
    assert_result(r, 200, "template", "user-fixture")
    assert r.json() == {"id": "user-1", "name": "Test user"}
    assert upstream.calls == []


def test_recipe6_replacement_error_is_500(recipe6):
    r = curl(R6_REPLACEMENT_ERROR, recipe6)
    assert_result(r, 500, "error", "tenant-projects")
    assert r.json() == {"error": "mockstack: internal error"}


def test_recipe6_fixture_render_error_is_500(recipe6):
    r = curl(R6_FIXTURE_RENDER_ERROR, recipe6)
    assert_result(r, 500, "error", "order-echo")
    assert r.json() == {"error": "An internal error occurred while rendering the template."}


def test_recipe6_relative_replacement_is_500_not_502(recipe6, upstream):
    r = curl(R6_RELATIVE_URL, recipe6)
    assert_result(r, 500, "error", "accounts-relative")
    assert r.json() == {"error": "mockstack: internal error"}
    assert upstream.calls == []


def test_recipe6_upstream_failure_is_502(recipe6):
    r = curl(R6_UPSTREAM_FAILED, recipe6)
    assert_result(r, 502, "error", "invoices-unreachable")
    assert r.json() == {"error": "mockstack: upstream request failed"}


def test_recipe6_upstream_timeout_is_504(recipe6):
    r = curl(R6_UPSTREAM_TIMEOUT, recipe6)
    assert_result(r, 504, "error", "reports-slow")
    assert r.json() == {"error": "mockstack: upstream request timed out"}


# --- Recipe 7 ---------------------------------------------------------------


@pytest.fixture(scope="module")
def recipe7(cookbook):
    # The page starts this recipe with MOCKSTACK__PROXYRULES_REDIRECT_VIA=http_307_temporary.
    return cookbook("07-redirect-mode", proxyrules_redirect_via="http_307_temporary")


def test_recipe7_fixture_is_served_in_redirect_mode(recipe7, upstream):
    r = curl(R7_FIXTURE, recipe7)
    assert_result(r, 200, "template", "user-fixture")
    assert r.json() == {"id": "user-1", "name": "Test user"}
    assert upstream.calls == []


def test_recipe7_passthrough_rule_redirects(recipe7, upstream):
    r = curl(R7_REDIRECT, recipe7)
    assert_result(r, 307, "redirect", "users-redirect")
    assert r.headers["location"] == f"{upstream.base_url}/api/v1/users/user-2"
    assert upstream.calls == []


def test_recipe7_following_the_redirect_reaches_upstream_directly(recipe7, upstream):
    r = curl(R7_FOLLOW_REDIRECT, recipe7)
    [redirect] = r.history
    assert_result(redirect, 307, "redirect", "users-redirect")
    assert r.status_code == 200
    assert "x-mockstack-result" not in r.headers
    assert r.json()["path"] == "/api/v1/users/user-2"
    assert [c["path"] for c in upstream.calls] == ["/api/v1/users/user-2"]


def test_recipe7_query_string_is_kept_in_location(recipe7, upstream):
    r = curl(R7_QUERY_KEPT, recipe7)
    assert_result(r, 307, "redirect", "users-redirect")
    assert r.headers["location"] == f"{upstream.base_url}/api/v1/users?page=2"
    assert upstream.calls == []


# --- The page, the README and this module stay in step ----------------------


def _documented_curls(markdown: str) -> list[str]:
    """Every ``curl`` command in ``markdown``, with its continuation lines."""
    commands: list[str] = []
    current: list[str] | None = None
    for line in markdown.splitlines():
        if current is None and line.startswith("curl "):
            current = []
        if current is None:
            continue
        current.append(line)
        if not line.endswith("\\"):
            commands.append("\n".join(current))
            current = None
    return commands


def test_every_documented_curl_is_tested():
    documented = _documented_curls(COOKBOOK_PAGE.read_text())
    assert sorted(documented) == sorted(TESTED_CURLS.values())


def test_cookbook_page_embeds_every_recipe_file():
    page = COOKBOOK_PAGE.read_text()
    recipe_files = [
        path
        for path in sorted(COOKBOOK_DIR.glob("0*/**/*"))
        if path.is_file() and "__pycache__" not in path.parts and path.name != "rules.local.yml"
    ]
    assert recipe_files
    for path in recipe_files:
        assert f'--8<-- "{path.relative_to(REPO_ROOT)}"' in page


def test_readme_mix_example_matches_recipe1():
    readme = README.read_text()
    section = readme.split("### Mix fixtures and real services", 1)[1]
    block = re.search(r"```yaml\n(.*?)```", section, re.DOTALL)
    assert block is not None
    recipe_rules = (COOKBOOK_DIR / "01-tagged-traffic" / "rules.yml").read_text()
    assert yaml.safe_load(block.group(1)) == yaml.safe_load(recipe_rules)
    for command in (R1_TAGGED, R1_UNTAGGED):
        assert command in section
