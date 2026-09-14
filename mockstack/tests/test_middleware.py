"""Tests for the middleware module."""

from starlette.testclient import TestClient

from mockstack.middleware import middleware_provider


def test_middleware_provider_process_time(app, settings):
    """Test that the middleware provider adds the process time header."""
    middleware_provider(app, settings)

    @app.get("/test")
    def route():
        return {"message": "test"}

    response = TestClient(app).get("/test")

    assert response.status_code == 200
    assert response.json() == {"message": "test"}

    # Verify the X-Process-Time header exists and is a positive float
    assert "X-Process-Time" in response.headers
    assert float(response.headers["X-Process-Time"]) > 0
