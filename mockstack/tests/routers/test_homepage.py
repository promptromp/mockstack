"""Tests for the homepage router module."""

import pytest

from mockstack.routers.homepage import homepage_router_provider


@pytest.mark.asyncio
async def test_homepage_router_provider(app, settings):
    """Test that the homepage router provider sets up routes correctly."""
    # Apply the router provider
    router = homepage_router_provider(app, settings)

    # Include the router in the app
    app.include_router(router)

    # Create a test client
    from fastapi.testclient import TestClient

    client = TestClient(app)

    # Test the homepage endpoint
    response = client.get("/")

    # Verify the response
    assert response.status_code == 200
    assert response.json() == {"Hello": "World"}
