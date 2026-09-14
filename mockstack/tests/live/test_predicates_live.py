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
                "pattern": r"^/juvenal/api/v2/project/(?P<id>[^/]+)$",
                "headers": {"x-request-eval-scenario": ".*"},
                "replacement": f"file://{fixture}",
            },
            {
                "name": "juvenal-passthrough",
                "pattern": r"^/juvenal/(.*)",
                "replacement": f"{upstream.base_url}/\\1",
            },
        ],
    )
    return mockstack_server(proxyrules_settings(rules))


def test_stamped_request_gets_fixture(server, upstream):
    r = httpx.get(
        f"{server.base_url}/juvenal/api/v2/project/abc",
        headers={"X-Request-Eval-Scenario": "healthy"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"source": "fixture", "scenario": "healthy"}
    assert upstream.calls == []


def test_unstamped_request_falls_through_to_upstream(server, upstream):
    r = httpx.get(f"{server.base_url}/juvenal/api/v2/project/abc")
    assert r.status_code == 200
    assert r.json()["source"] == "upstream"
    assert upstream.calls[-1]["path"] == "/api/v2/project/abc"


@pytest.fixture
def druid(tmp_path, upstream, mockstack_server):
    fixture = tmp_path / "pricing.json.j2"
    fixture.write_text(
        '{"source": "fixture", "sql": {{ request_json.query | tojson }}}'
    )
    rules = write_rules(
        tmp_path,
        [
            {
                "name": "druid-pricing-eval",
                "method": "POST",
                "pattern": r"^/druid/druid/v2/sql$",
                "headers": {"x-request-eval-scenario": ".*"},
                "json": {"query": r"(?is).*FROM\s+pricing_facts.*"},
                "replacement": f"file://{fixture}",
            },
            {
                "name": "druid-passthrough",
                "pattern": r"^/druid/(.*)",
                "replacement": f"{upstream.base_url}/\\1",
            },
        ],
    )
    return mockstack_server(proxyrules_settings(rules))


def test_druid_query_selected_by_body(druid, upstream):
    sql = "SELECT client_id, SUM(amount)\nFROM pricing_facts WHERE 1=1"
    stamped = {"X-Request-Eval-Scenario": "healthy"}
    r = httpx.post(
        f"{druid.base_url}/druid/druid/v2/sql", json={"query": sql}, headers=stamped
    )
    assert r.status_code == 200 and r.json() == {"source": "fixture", "sql": sql}

    other = httpx.post(
        f"{druid.base_url}/druid/druid/v2/sql",
        json={"query": "SELECT 1 FROM users"},
        headers=stamped,
    )
    assert other.json()["source"] == "upstream"
    assert json.loads(upstream.calls[-1]["body"]) == {"query": "SELECT 1 FROM users"}
