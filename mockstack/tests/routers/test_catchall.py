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
