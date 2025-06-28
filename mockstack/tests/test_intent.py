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


@pytest.fixture
def json_content_types():
    """Return a list of valid JSON content types."""
    return [
        "application/json",
        "text/json",
    ]


@pytest.fixture
def non_json_content_types():
    """Return a list of non-JSON content types."""
    return [
        "text/plain",
        "application/xml",
        "text/html",
    ]


@pytest.fixture
def search_paths():
    """Return a list of paths that should be identified as search requests."""
    return [
        "/api/_search",
        "/api/search",
        "/api/_query",
    ]


@pytest.fixture
def command_paths():
    """Return a list of paths that should be identified as command requests."""
    return [
        "/api/_command",
        "/api/command",
        "/api/_run",
        "/api/run",
        "/api/_execute",
        "/api/execute",
    ]


@pytest.fixture
def create_paths():
    """Return a list of paths that should be identified as create requests."""
    return [
        "/api/create",
        "/api/data",  # POST without search/command
    ]


def test_wants_json_with_content_type(
    mock_request, json_content_types, non_json_content_types
):
    """Test wants_json with different content types."""
    # Test valid JSON content types
    for content_type in json_content_types:
        request = mock_request(headers={"Content-Type": content_type})
        assert wants_json(request) is True

    # Test non-JSON content types
    for content_type in non_json_content_types:
        request = mock_request(headers={"Content-Type": content_type})
        assert wants_json(request) is False

    # Test missing content type
    request = mock_request()
    assert wants_json(request) is False


def test_wants_json_with_path(mock_request):
    """Test wants_json with .json path."""
    # Test .json suffix
    request = mock_request(path="/api/data.json")
    assert wants_json(request) is True

    # Test non-.json path
    request = mock_request(path="/api/data")
    assert wants_json(request) is False


def test_looks_like_a_search(mock_request, search_paths):
    """Test looks_like_a_search with different paths."""
    # Test search paths
    for path in search_paths:
        request = mock_request(path=path)
        assert looks_like_a_search(request) is True

    # Test non-search path
    request = mock_request(path="/api/data")
    assert looks_like_a_search(request) is False


def test_looks_like_a_command(mock_request, command_paths):
    """Test looks_like_a_command with different paths."""
    # Test command paths
    for path in command_paths:
        request = mock_request(path=path)
        assert looks_like_a_command(request) is True

    # Test non-command path
    request = mock_request(path="/api/data")
    assert looks_like_a_command(request) is False


def test_looks_like_a_create(mock_request, create_paths, search_paths, command_paths):
    """Test looks_like_a_create with different scenarios."""
    # Test create paths with POST method
    for path in create_paths:
        request = mock_request(method="POST", path=path)
        assert looks_like_a_create(request) is True

    # Test POST with search paths (should be False)
    for path in search_paths:
        request = mock_request(method="POST", path=path)
        assert looks_like_a_create(request) is False

    # Test POST with command paths (should be False)
    for path in command_paths:
        request = mock_request(method="POST", path=path)
        assert looks_like_a_create(request) is False

    # Test non-POST method
    request = mock_request(method="GET", path="/api/data")
    assert looks_like_a_create(request) is False
