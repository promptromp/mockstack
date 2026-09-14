"""Live test for the ``examples/proxyrules-eval-isolation`` worked example.

Loads the *real* rules file and fixture templates shipped under
``examples/proxyrules-eval-isolation/`` (never a copy re-typed into the test) and
substitutes its ``${FIXTURES_DIR}``/``${PROJECTS_URL}``/``${ANALYTICS_URL}`` placeholders
the same way the README's ``envsubst`` step does, so the example and this test can
never drift apart. Asserts exactly the three ``curl`` scenarios documented in the
example's README, plus a fourth passthrough case for a non-matching Analytics query.
"""

import json
import shutil
import string
from pathlib import Path

import httpx
import pytest

from mockstack.tests.live.conftest import proxyrules_settings

pytestmark = pytest.mark.slow

EXAMPLE_DIR = (
    Path(__file__).resolve().parents[3] / "examples" / "proxyrules-eval-isolation"
)

STAMPED = {"X-Request-Eval-Scenario": "healthy"}


@pytest.fixture
def server(tmp_path, upstream, mockstack_server):
    fixtures_dir = tmp_path / "fixtures"
    shutil.copytree(EXAMPLE_DIR / "fixtures", fixtures_dir)

    rendered = string.Template((EXAMPLE_DIR / "rules.yml").read_text()).safe_substitute(
        FIXTURES_DIR=str(fixtures_dir),
        PROJECTS_URL=upstream.base_url,
        ANALYTICS_URL=upstream.base_url,
    )
    rules_file = tmp_path / "rules.local.yml"
    rules_file.write_text(rendered)

    return mockstack_server(proxyrules_settings(rules_file))


def test_stamped_get_project_returns_fixture(server, upstream):
    """README scenario 1: stamped GET project -> template fixture."""
    r = httpx.get(
        f"{server.base_url}/projects/api/v2/project/proj-123", headers=STAMPED
    )
    assert r.status_code == 200
    assert r.headers["x-mockstack-result"] == "template"
    assert r.headers["x-mockstack-rule"] == "projects-project-eval"
    assert r.json() == {
        "id": "proj-123",
        "name": "Eval project proj-123",
        "status": "ACTIVE",
        "scenario": "healthy",
    }
    assert upstream.calls == []


def test_unstamped_get_project_falls_through_to_upstream(server, upstream):
    """README scenario 2: unstamped GET project -> proxy passthrough."""
    r = httpx.get(f"{server.base_url}/projects/api/v2/project/proj-123")
    assert r.status_code == 200
    assert r.headers["x-mockstack-result"] == "proxy"
    assert r.headers["x-mockstack-rule"] == "projects-passthrough"
    assert r.json()["source"] == "upstream"
    assert len(upstream.calls) == 1
    assert upstream.calls[0]["path"] == "/api/v2/project/proj-123"


def test_stamped_analytics_sales_query_returns_fixture(server, upstream):
    """README scenario 3: stamped Analytics POST mentioning sales_facts -> template fixture."""
    sql = "SELECT client_id, SUM(amount)\nFROM sales_facts WHERE 1=1"
    r = httpx.post(
        f"{server.base_url}/analytics/analytics/v2/sql",
        json={"query": sql},
        headers=STAMPED,
    )
    assert r.status_code == 200
    assert r.headers["x-mockstack-result"] == "template"
    assert r.headers["x-mockstack-rule"] == "analytics-sales-eval"
    assert r.json() == [
        {"client_id": "eval-client", "total_amount": 1234.5, "echo_sql": sql}
    ]
    assert upstream.calls == []


def test_stamped_analytics_non_sales_query_falls_through_to_upstream(server, upstream):
    """Fourth scenario: stamped Analytics POST that doesn't mention sales_facts -> proxy."""
    r = httpx.post(
        f"{server.base_url}/analytics/analytics/v2/sql",
        json={"query": "SELECT 1 FROM other_table"},
        headers=STAMPED,
    )
    assert r.status_code == 200
    assert r.headers["x-mockstack-result"] == "proxy"
    assert r.headers["x-mockstack-rule"] == "analytics-passthrough"
    assert r.json()["source"] == "upstream"
    assert len(upstream.calls) == 1
    assert json.loads(upstream.calls[0]["body"]) == {
        "query": "SELECT 1 FROM other_table"
    }
