"""Live test that a Jinja-rendered fixture path cannot escape its fixtures directory.

Header-selected scenario directories (including an unknown scenario) are covered by
``test_cookbook.py`` (recipe 2), and header-gated fixtures versus passthrough (including
body predicates) by ``test_example_eval_isolation.py``, which run the shipped rules files.
"""

import httpx
import pytest


pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def scenarios(tmp_path_factory, upstream, mockstack_server):
    """Mockstack serving ``scenarios/<header>/...``, with a real fixture file just
    outside that directory for a traversal attempt to aim at."""
    root = tmp_path_factory.mktemp("fixtures")
    outside = root / "outside" / "projects" / "project.abc.json.j2"
    outside.parent.mkdir(parents=True)
    outside.write_text('{"scenario": "outside", "id": "{{ id }}"}')
    return mockstack_server(
        [
            {
                "name": "project-eval",
                "method": "GET",
                "pattern": r"^/projects/api/v1/project/(?P<id>[^/]+)$",
                "headers": {"x-request-eval-scenario": ".*"},
                "replacement": (
                    f"file://{root}/scenarios/{{{{ headers['x-request-eval-scenario'] }}}}"
                    "/projects/project.{{ id }}.json.j2"
                ),
            },
            {
                "name": "passthrough",
                "pattern": r"^/projects/(.*)",
                "replacement": f"{upstream.base_url}/\\1",
            },
        ]
    )


def test_traversal_scenario_returns_404_not_upstream(scenarios, upstream):
    """A scenario header carrying a ``..`` path traversal attempt must be rejected by
    the strategy's own guard, not merely by the (still permissive, ``.*``) header
    predicate -- proving the fixture directory can't be escaped via header content.
    The rendered path points at a file that exists, so only the guard can 404 it.
    """
    r = httpx.get(
        f"{scenarios.base_url}/projects/api/v1/project/abc",
        headers={"X-Request-Eval-Scenario": "../outside"},
    )
    assert r.status_code == 404
    assert r.headers["x-mockstack-result"] == "error"
    assert r.headers["x-mockstack-rule"] == "project-eval"
    assert r.json() == {"error": "Template file not found."}
    assert upstream.calls == []
