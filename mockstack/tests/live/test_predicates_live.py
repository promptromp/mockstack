"""Live tests for header/query predicates and fail-open ordering."""

import json

import httpx
import pytest

from mockstack.tests.live.conftest import proxyrules_settings, write_rules

pytestmark = pytest.mark.slow


@pytest.fixture
def server(tmp_path, upstream, mockstack_server):
    fixture = tmp_path / "project.json.j2"
    fixture.write_text(
        '{"source": "fixture", "scenario": "{{ headers[\'x-request-eval-scenario\'] }}"}'
    )
    rules = write_rules(
        tmp_path,
        [
            {
                "name": "project-eval",
                "method": "GET",
                "pattern": r"^/projects/api/v1/project/(?P<id>[^/]+)$",
                "headers": {"x-request-eval-scenario": ".*"},
                "replacement": f"file://{fixture}",
            },
            {
                "name": "projects-passthrough",
                "pattern": r"^/projects/(.*)",
                "replacement": f"{upstream.base_url}/\\1",
            },
        ],
    )
    return mockstack_server(proxyrules_settings(rules))


def test_stamped_request_gets_fixture(server, upstream):
    r = httpx.get(
        f"{server.base_url}/projects/api/v1/project/abc",
        headers={"X-Request-Eval-Scenario": "healthy"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.headers["x-mockstack-result"] == "template"
    assert r.json() == {"source": "fixture", "scenario": "healthy"}
    assert upstream.calls == []


def test_unstamped_request_falls_through_to_upstream(server, upstream):
    r = httpx.get(f"{server.base_url}/projects/api/v1/project/abc")
    assert r.status_code == 200
    assert r.headers["x-mockstack-result"] == "proxy"
    assert r.json()["source"] == "upstream"
    assert upstream.calls[-1]["path"] == "/api/v1/project/abc"
    assert "x-mockstack-rule" not in upstream.calls[-1]["headers"]


@pytest.fixture
def analytics(tmp_path, upstream, mockstack_server):
    fixture = tmp_path / "sales.json.j2"
    fixture.write_text(
        '{"source": "fixture", "sql": {{ request_json.query | tojson }}}'
    )
    rules = write_rules(
        tmp_path,
        [
            {
                "name": "analytics-sales-eval",
                "method": "POST",
                "pattern": r"^/analytics/v1/sql$",
                "headers": {"x-request-eval-scenario": ".*"},
                "json": {"query": r"(?is).*FROM\s+sales_facts.*"},
                "replacement": f"file://{fixture}",
            },
            {
                "name": "analytics-passthrough",
                "pattern": r"^/analytics/(.*)",
                "replacement": f"{upstream.base_url}/\\1",
            },
        ],
    )
    return mockstack_server(proxyrules_settings(rules))


def test_analytics_query_selected_by_body(analytics, upstream):
    sql = "SELECT region, SUM(amount)\nFROM sales_facts WHERE 1=1"
    stamped = {"X-Request-Eval-Scenario": "healthy"}
    r = httpx.post(
        f"{analytics.base_url}/analytics/v1/sql", json={"query": sql}, headers=stamped
    )
    assert r.status_code == 200 and r.json() == {"source": "fixture", "sql": sql}
    assert r.headers["x-mockstack-result"] == "template"

    other = httpx.post(
        f"{analytics.base_url}/analytics/v1/sql",
        json={"query": "SELECT 1 FROM users"},
        headers=stamped,
    )
    assert other.headers["x-mockstack-result"] == "proxy"
    assert other.json()["source"] == "upstream"
    assert json.loads(upstream.calls[-1]["body"]) == {"query": "SELECT 1 FROM users"}
    assert "x-mockstack-rule" not in upstream.calls[-1]["headers"]


@pytest.fixture
def scenarios(tmp_path, upstream, mockstack_server):
    for name in ("healthy", "degraded"):
        d = tmp_path / name / "projects"
        d.mkdir(parents=True)
        (d / "project.abc.json.j2").write_text(
            f'{{"scenario": "{name}", "id": "{{{{ id }}}}"}}'
        )
    rules = write_rules(
        tmp_path,
        [
            {
                "name": "project-eval",
                "method": "GET",
                "pattern": r"^/projects/api/v1/project/(?P<id>[^/]+)$",
                "headers": {"x-request-eval-scenario": ".*"},
                "replacement": f"file://{tmp_path}/{{{{ headers['x-request-eval-scenario'] }}}}/projects/project.{{{{ id }}}}.json.j2",
            },
            {
                "name": "passthrough",
                "pattern": r"^/projects/(.*)",
                "replacement": f"{upstream.base_url}/\\1",
            },
        ],
    )
    return mockstack_server(proxyrules_settings(rules))


@pytest.mark.parametrize("scenario", ["healthy", "degraded"])
def test_scenario_header_selects_fixture_directory(scenarios, scenario):
    r = httpx.get(
        f"{scenarios.base_url}/projects/api/v1/project/abc",
        headers={"X-Request-Eval-Scenario": scenario},
    )
    assert r.status_code == 200
    assert r.headers["x-mockstack-result"] == "template"
    assert r.json() == {"scenario": scenario, "id": "abc"}


def test_unknown_scenario_returns_404_not_upstream(scenarios, upstream):
    r = httpx.get(
        f"{scenarios.base_url}/projects/api/v1/project/abc",
        headers={"X-Request-Eval-Scenario": "nope"},
    )
    assert r.status_code == 404
    assert upstream.calls == []


def test_traversal_scenario_returns_404_not_upstream(scenarios, upstream):
    """A scenario header carrying a ``..`` path traversal attempt must be rejected by
    the strategy's own guard, not merely by the (still permissive, ``.*``) header
    predicate -- proving the fixture directory can't be escaped via header content.
    """
    r = httpx.get(
        f"{scenarios.base_url}/projects/api/v1/project/abc",
        headers={"X-Request-Eval-Scenario": "../healthy"},
    )
    assert r.status_code == 404
    assert upstream.calls == []
