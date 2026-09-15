"""Tests for the application factory."""

import httpx
import pytest

from mockstack.main import create_app


@pytest.mark.asyncio
async def test_create_app_routes_root_path_to_strategy(make_settings, write_template, tmp_path):
    """``GET /`` reaches the strategy through the catch-all route: the app registers no
    route of its own at the root path."""
    write_template("index.j2", '{"message": "root fixture"}')
    app = create_app(make_settings(strategy="filefixtures", templates_dir=tmp_path))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "root fixture"}
