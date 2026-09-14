"""Fail a test when mockstack did not answer from a fixture.

Copy into your test suite and point ``MOCKSTACK_URL`` at the running mockstack.
"""

import os
from collections.abc import Iterator

import httpx
import pytest


MOCKSTACK_URL = os.environ.get("MOCKSTACK_URL", "http://127.0.0.1:8000")


def expect_fixture(response: httpx.Response, rule: str | None = None) -> httpx.Response:
    """Assert that ``response`` was rendered from a fixture (by ``rule``, if given)."""
    result = response.headers.get("X-Mockstack-Result")
    served_by = response.headers.get("X-Mockstack-Rule")
    assert result == "template", (
        f"{response.request.method} {response.request.url.path} got "
        f"{response.status_code} with X-Mockstack-Result={result!r} "
        f"(rule {served_by!r}), not a fixture"
    )
    if rule is not None:
        assert served_by == rule, f"served by rule {served_by!r}, expected {rule!r}"
    return response


@pytest.fixture
def mockstack() -> Iterator[httpx.Client]:
    headers = {"X-Test-Run": "ci"}
    with httpx.Client(base_url=MOCKSTACK_URL, headers=headers) as client:
        yield client


def test_project_comes_from_fixture(mockstack: httpx.Client) -> None:
    response = mockstack.get("/projects/api/v1/project/proj-123")
    expect_fixture(response, rule="project-fixture")
    assert response.json()["status"] == "ACTIVE"
