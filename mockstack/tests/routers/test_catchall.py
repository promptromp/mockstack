"""Tests for the catchall router module."""

from unittest.mock import AsyncMock

import pytest
from fastapi.responses import JSONResponse

from mockstack.routers.catchall import catchall_router_provider


@pytest.fixture
def mock_strategy():
    """Create a mock strategy for testing."""
    strategy = AsyncMock()
    response_data = {"message": "Mock response"}
    strategy.apply.return_value = JSONResponse(content=response_data)
    return strategy


@pytest.fixture
def client(app, settings, mock_strategy, asgi_client):
    """A test client for an app whose catch-all router uses ``mock_strategy``."""
    app.state.strategy = mock_strategy
    catchall_router_provider(app, settings)
    return asgi_client


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE", "PATCH"])
async def test_catchall_router_provider(client, mock_strategy, method):
    """Test that the catchall router provider sets up routes correctly."""
    response = await client.request(method, "/test/path")

    assert response.status_code == 200
    assert response.json() == {"message": "Mock response"}
    mock_strategy.apply.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["HEAD", "OPTIONS"])
async def test_catchall_router_routes_head_and_options_to_strategy(client, mock_strategy, method):
    """HEAD and OPTIONS must reach the strategy rather than get a router-level 405."""
    response = await client.request(method, "/test/path")

    assert response.status_code == 200
    mock_strategy.apply.assert_called_once()
    assert mock_strategy.apply.call_args.args[0].method == method


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["HEAD", "OPTIONS"])
async def test_catchall_router_filefixtures_still_rejects_head_and_options(app, settings, asgi_client, method):
    """Routed to the filefixtures strategy (the ``app`` fixture's), HEAD and OPTIONS are
    still answered 405 -- now by the strategy itself rather than by the router."""
    catchall_router_provider(app, settings)

    response = await asgi_client.request(method, "/test/path")

    assert response.status_code == 405
    if method == "OPTIONS":
        assert response.json() == {"detail": "Method not allowed"}
