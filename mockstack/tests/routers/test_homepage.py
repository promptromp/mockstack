"""Tests for the homepage router module."""

from fastapi.testclient import TestClient

from mockstack.routers.homepage import homepage_router_provider


def test_homepage_router_provider(app, settings):
    """Test that the homepage router provider sets up routes correctly."""
    app.include_router(homepage_router_provider(app, settings))

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.json() == {"Hello": "World"}
