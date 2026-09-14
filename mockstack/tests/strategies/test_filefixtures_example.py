"""The ``filefixtures-with-templates`` example's templates, rendered through the strategy."""

import json
from pathlib import Path

import pytest
from fastapi import status

from mockstack.strategies.filefixtures import FileFixturesStrategy


EXAMPLE_TEMPLATES = Path(__file__).resolve().parents[3] / "examples" / "filefixtures-with-templates" / "templates"
ITEM_ID = "533ec889-7c68-45c8-b21e-4a7e455de123"


@pytest.fixture
def example_strategy(make_settings) -> FileFixturesStrategy:
    """A filefixtures strategy serving the example's ``templates/`` directory."""
    return FileFixturesStrategy(make_settings(strategy="filefixtures", templates_dir=EXAMPLE_TEMPLATES))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_items"),
    [
        (f"item_id={ITEM_ID}".encode(), [{"createdAt": "2023-05-02T11:48:16.708081+00:00", "id": ITEM_ID}]),
        (b"", []),
    ],
    ids=["matching-item-id", "without-item-id"],
)
async def test_items_template_renders_valid_json(example_strategy, traced_request, query, expected_items):
    """Both branches of ``servicename-api-v1-items.j2`` render JSON with the same fields."""
    response = await example_strategy.apply(traced_request("/servicename/api/v1/items", query=query))

    assert response.status_code == status.HTTP_200_OK
    assert json.loads(response.body) == {
        "items": expected_items,
        "count": len(expected_items),
        "limit": 20,
        "offset": 0,
    }
