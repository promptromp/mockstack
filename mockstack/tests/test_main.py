"""Tests for the application factory."""

import httpx
import pytest

from mockstack.main import create_app


OPENAPI_DOCS_PATHS = ["/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"]


def _route_paths(app):
    return {route.path for route in app.routes}


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


@pytest.mark.asyncio
@pytest.mark.parametrize("path", OPENAPI_DOCS_PATHS)
async def test_create_app_passes_openapi_docs_paths_to_strategy_by_default(make_settings, tmp_path, path):
    """FastAPI's documentation routes are off by default, so their paths reach the strategy
    like any other: a filefixtures app with no templates answers them with its 404."""
    app = create_app(make_settings(strategy="filefixtures", templates_dir=tmp_path))

    assert not _route_paths(app) & set(OPENAPI_DOCS_PATHS)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(path)

    assert response.status_code == 404
    assert response.json()["message"] == "mockstack: resource not found"


@pytest.mark.asyncio
async def test_create_app_serves_openapi_docs_when_enabled(make_settings, tmp_path):
    """With ``openapi_docs_enabled`` FastAPI serves its documentation routes, ahead of the
    catch-all route."""
    app = create_app(make_settings(strategy="filefixtures", templates_dir=tmp_path, openapi_docs_enabled=True))

    assert set(OPENAPI_DOCS_PATHS) <= _route_paths(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        docs = await client.get("/docs")
        # FastAPI gives every method of one route the same operation ID, and says so.
        with pytest.warns(UserWarning, match="Duplicate Operation ID"):
            schema = await client.get("/openapi.json")

    assert docs.status_code == 200
    assert docs.headers["content-type"].startswith("text/html")
    assert schema.status_code == 200
    assert "/{full_path}" in schema.json()["paths"]
