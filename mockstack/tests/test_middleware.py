"""Tests for the middleware module."""

import pytest

from mockstack.middleware import middleware_provider


@pytest.mark.asyncio
async def test_middleware_provider_process_time(app, settings, asgi_client):
    """Test that the middleware provider adds the process time header."""
    middleware_provider(app, settings)

    @app.get("/test")
    def route():
        return {"message": "test"}

    response = await asgi_client.get("/test")

    assert response.status_code == 200
    assert response.json() == {"message": "test"}

    # Verify the X-Process-Time header exists and is a positive float
    assert "X-Process-Time" in response.headers
    assert float(response.headers["X-Process-Time"]) > 0
