"""Tests for the catchall router module."""

from unittest.mock import AsyncMock

import pytest
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from mockstack.routers.catchall import catchall_router_provider


@pytest.fixture
def mock_strategy():
    """Create a mock strategy for testing."""
    strategy = AsyncMock()
    response_data = {"message": "Mock response"}
    strategy.apply.return_value = JSONResponse(content=response_data)
    return strategy


@pytest.mark.asyncio
async def test_catchall_router_provider(app, settings, mock_strategy):
    """Test that the catchall router provider sets up routes correctly."""
    # Set up the app state with the mock strategy
    app.state.strategy = mock_strategy

    # Apply the router provider
    catchall_router_provider(app, settings)

    # Create a test client
    client = TestClient(app)

    # Test each HTTP method
    for method in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
        # Make the request using the test client
        response = client.request(method, "/test/path")

        # Verify the response
        assert response.status_code == 200
        assert response.json() == {"message": "Mock response"}

        # Verify the strategy was called
        mock_strategy.apply.assert_called_once()

        # Reset the mock for the next iteration
        mock_strategy.reset_mock()


@pytest.mark.asyncio
async def test_catchall_router_routes_head_and_options_to_strategy(
    app, settings, mock_strategy
):
    """HEAD and OPTIONS must reach the strategy rather than get a router-level 405."""
    app.state.strategy = mock_strategy
    catchall_router_provider(app, settings)
    client = TestClient(app)

    for method in ["HEAD", "OPTIONS"]:
        response = client.request(method, "/test/path")

        assert response.status_code == 200
        mock_strategy.apply.assert_called_once()
        assert mock_strategy.apply.call_args.args[0].method == method
        mock_strategy.reset_mock()


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS"])
def test_catchall_router_filefixtures_still_rejects_head_and_options(
    app, settings, method
):
    """Routed to the filefixtures strategy (the ``app`` fixture's), HEAD and OPTIONS are
    still answered 405 -- now by the strategy itself rather than by the router."""
    catchall_router_provider(app, settings)
    client = TestClient(app, raise_server_exceptions=True)

    response = client.request(method, "/test/path")

    assert response.status_code == 405
    if method == "OPTIONS":
        assert response.json() == {"detail": "Method not allowed"}
