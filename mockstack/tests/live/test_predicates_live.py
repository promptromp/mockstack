"""Live tests for Jinja-rendered replacements that select per-scenario fixtures.

Header-gated fixtures versus passthrough (including body predicates) are covered by
``test_example_eval_isolation.py``, which runs the shipped example's rules file.
"""

import httpx
import pytest

from mockstack.tests.live.conftest import proxyrules_settings, write_rules

pytestmark = pytest.mark.slow


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
    assert r.headers["x-mockstack-result"] == "error"
    assert r.headers["x-mockstack-rule"] == "project-eval"
    assert r.json() == {"error": "Template file not found."}
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
    assert r.headers["x-mockstack-result"] == "error"
    assert r.json() == {"error": "Template file not found."}
    assert upstream.calls == []
