"""Unit tests for the intent module."""

import pytest
from fastapi import Request
from starlette.datastructures import Headers

from mockstack.intent import (
    wants_json,
    looks_like_a_search,
    looks_like_a_command,
    looks_like_a_create,
)


@pytest.fixture
def mock_request():
    """Create a mock FastAPI request object."""

    def _create_request(
        method="GET",
        path="/",
        headers=None,
    ):
        return Request(
            {
                "type": "http",
                "method": method,
                "path": path,
                "headers": Headers(headers or {}).raw,
            }
        )

    return _create_request


def test_wants_json_with_content_type(mock_request):
    """Test wants_json with different content types."""
    # Test application/json
    request = mock_request(headers={"Content-Type": "application/json"})
    assert wants_json(request) is True

    # Test text/json
    request = mock_request(headers={"Content-Type": "text/json"})
    assert wants_json(request) is True

    # Test non-json content type
    request = mock_request(headers={"Content-Type": "text/plain"})
    assert wants_json(request) is False

    # Test missing content type
    request = mock_request()
    assert wants_json(request) is False


def test_wants_json_with_path(mock_request):
    """Test wants_json with .json path."""
    request = mock_request(path="/api/data.json")
    assert wants_json(request) is True

    request = mock_request(path="/api/data")
    assert wants_json(request) is False


def test_looks_like_a_search(mock_request):
    """Test looks_like_a_search with different paths."""
    # Test _search suffix
    request = mock_request(path="/api/_search")
    assert looks_like_a_search(request) is True

    # Test /search suffix
    request = mock_request(path="/api/search")
    assert looks_like_a_search(request) is True

    # Test _query suffix
    request = mock_request(path="/api/_query")
    assert looks_like_a_search(request) is True

    # Test non-search path
    request = mock_request(path="/api/data")
    assert looks_like_a_search(request) is False


def test_looks_like_a_command(mock_request):
    """Test looks_like_a_command with different paths."""
    # Test various command-like suffixes
    command_suffixes = [
        "_command",
        "/command",
        "_request",
        "/request",
        "_run",
        "/run",
        "_execute",
        "/execute",
    ]

    for suffix in command_suffixes:
        request = mock_request(path=f"/api{suffix}")
        assert looks_like_a_command(request) is True

    # Test non-command path
    request = mock_request(path="/api/data")
    assert looks_like_a_command(request) is False


def test_looks_like_a_create(mock_request):
    """Test looks_like_a_create with different scenarios."""
    # Test POST method without search/command
    request = mock_request(method="POST", path="/api/data")
    assert looks_like_a_create(request) is True

    # Test POST with search path (should be False)
    request = mock_request(method="POST", path="/api/_search")
    assert looks_like_a_create(request) is False

    # Test POST with command path (should be False)
    request = mock_request(method="POST", path="/api/_command")
    assert looks_like_a_create(request) is False

    # Test /create suffix
    request = mock_request(path="/api/create")
    assert looks_like_a_create(request) is True

    # Test non-POST method
    request = mock_request(method="GET", path="/api/data")
    assert looks_like_a_create(request) is False
