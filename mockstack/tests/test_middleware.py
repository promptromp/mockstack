"""Tests for the middleware module."""

import time

import pytest
from starlette.testclient import TestClient

from mockstack.middleware import middleware_provider


@pytest.mark.asyncio
async def test_middleware_provider_process_time(app, settings):
    """Test that the middleware provider adds the process time header."""
    # Apply the middleware provider
    middleware_provider(app, settings)

    # Create a test client
    client = TestClient(app)

    # Add a test route
    @app.get("/test")
    def test_route():
        # Simulate some processing time
        time.sleep(0.1)
        return {"message": "test"}

    # Make a request
    response = client.get("/test")

    # Verify the response
    assert response.status_code == 200
    assert response.json() == {"message": "test"}

    # Verify the X-Process-Time header exists and is a float
    assert "X-Process-Time" in response.headers
    process_time = float(response.headers["X-Process-Time"])
    assert process_time > 0  # Should be greater than 0 due to sleep
