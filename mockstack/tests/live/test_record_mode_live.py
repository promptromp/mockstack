"""Live tests for proxyrules record mode: real sockets, a real upstream and real files."""

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from mockstack.recording import RECORDED_MARKER


pytestmark = pytest.mark.slow

SCENARIO = {"X-Test-Scenario": "healthy"}
JSON = {"content-type": "application/json"}


def rules_for(root: Path, upstream_url: str, **fixture_fields: Any) -> list[dict[str, Any]]:
    """A scenario-directory users fixture and a 201 orders fixture, each before a URL rule."""
    return [
        {
            "name": "users-fixture",
            "pattern": r"^/users/api/v1/users/(?P<user_id>[a-z0-9-]+)$",
            "headers": {"x-test-scenario": "[a-z0-9_-]+"},
            "replacement": f"file://{root}/{{{{ headers['x-test-scenario'] }}}}/users/{{{{ user_id }}}}.json.j2",
            **fixture_fields,
        },
        {
            "name": "orders-created",
            "method": "POST",
            "pattern": r"^/orders/api/v1/orders$",
            "status": 201,
            "replacement": f"file://{root}/orders/created.json.j2",
        },
        {
            "name": "orders-upstream",
            "method": "POST",
            "pattern": r"^/orders/api/v1/orders$",
            "replacement": f"{upstream_url}/created",
        },
        {"name": "users-passthrough", "pattern": r"^/users/(.*)", "replacement": f"{upstream_url}/\\1"},
    ]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "fixtures"
    path.mkdir()
    return path


@pytest.fixture
def start(root, upstream, mockstack_server):
    """Factory: a live mockstack recording into ``root`` in ``mode``; returns its base URL."""

    def _start(mode: str = "missing", **fixture_fields: Any) -> str:
        live = mockstack_server(
            rules_for(root, upstream.base_url, **fixture_fields),
            proxyrules_record_mode=mode,
            proxyrules_record_root=root,
        )
        return str(live.base_url)

    return _start


def stamp(response: httpx.Response) -> tuple[int, str | None, str | None]:
    return response.status_code, response.headers.get("x-mockstack-result"), response.headers.get("x-mockstack-rule")


def test_first_request_records_then_replays_without_the_upstream(start, root, upstream):
    url = f"{start()}/users/api/v1/users/user-1"
    first = httpx.get(url, headers=SCENARIO)
    second = httpx.get(url, headers=SCENARIO)
    assert stamp(first) == (200, "record", "users-fixture")
    assert stamp(second) == (200, "template", "users-fixture")
    assert second.content == first.content
    assert first.json()["path"] == "/api/v1/users/user-1"
    assert len(upstream.calls) == 1
    assert (root / "healthy" / "users" / "user-1.json.j2").read_text().startswith(RECORDED_MARKER)


def test_recorded_fixture_replays_after_a_restart_with_recording_off(start, root, upstream, mockstack_server):
    recorded = httpx.get(f"{start()}/users/api/v1/users/user-2", headers=SCENARIO)
    replay_server = mockstack_server(rules_for(root, upstream.base_url))
    upstream.calls.clear()
    replayed = httpx.get(f"{replay_server.base_url}/users/api/v1/users/user-2", headers=SCENARIO)
    assert stamp(replayed) == (200, "template", "users-fixture")
    assert replayed.content == recorded.content
    assert upstream.calls == []


def test_overwrite_refreshes_recorded_fixtures_but_not_hand_written_ones(start, root, upstream):
    hand_written = root / "healthy" / "users" / "user-9.json.j2"
    hand_written.parent.mkdir(parents=True)
    hand_written.write_text('{"source": "hand-written"}')
    missing = start("missing")
    httpx.get(f"{missing}/users/api/v1/users/user-3?v=1", headers=SCENARIO)

    overwrite = start("overwrite")
    refreshed = httpx.get(f"{overwrite}/users/api/v1/users/user-3?v=2", headers=SCENARIO)
    kept = httpx.get(f"{overwrite}/users/api/v1/users/user-9", headers=SCENARIO)
    replayed = httpx.get(f"{missing}/users/api/v1/users/user-3", headers=SCENARIO)

    assert stamp(refreshed) == (200, "record", "users-fixture")
    assert replayed.json()["query"] == {"v": "2"}
    assert (stamp(kept), kept.json()) == ((200, "template", "users-fixture"), {"source": "hand-written"})
    assert [call["path"] for call in upstream.calls] == ["/api/v1/users/user-3", "/api/v1/users/user-3"]


def test_status_rule_records_a_201_from_the_upstream(start, upstream):
    base = start()
    created = httpx.post(f"{base}/orders/api/v1/orders", headers=JSON, content=b'{"customer": "cust-7"}')
    replayed = httpx.post(f"{base}/orders/api/v1/orders", headers=JSON, content=b'{"customer": "cust-8"}')
    assert stamp(created) == (201, "record", "orders-created")
    assert stamp(replayed) == (201, "template", "orders-created")
    assert replayed.json()["body"] == '{"customer": "cust-7"}'
    assert len(upstream.calls) == 1


def test_status_mismatch_is_proxied_and_not_recorded(start, root):
    response = httpx.get(f"{start(status=201)}/users/api/v1/users/user-4", headers=SCENARIO)
    assert stamp(response) == (200, "proxy", "users-passthrough")
    assert not (root / "healthy").exists()


def test_concurrent_recordings_of_one_fixture_leave_one_complete_file(start, root):
    base = start()

    async def burst() -> list[httpx.Response]:
        async with httpx.AsyncClient(base_url=base, timeout=10) as client:
            return await asyncio.gather(
                *(client.get("/users/api/v1/users/user-5", headers=SCENARIO) for _ in range(20))
            )

    responses = asyncio.run(burst())
    assert {stamp(r)[:2] for r in responses} <= {(200, "record"), (200, "template")}
    assert sorted(p.name for p in (root / "healthy" / "users").iterdir()) == ["user-5.json.j2"]
    replay = httpx.get(f"{base}/users/api/v1/users/user-5", headers=SCENARIO)
    assert stamp(replay) == (200, "template", "users-fixture")
    assert replay.json()["path"] == "/api/v1/users/user-5"
