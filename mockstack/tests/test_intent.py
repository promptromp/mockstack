"""Unit tests for the intent module."""

import pytest

from mockstack.intent import (
    looks_like_a_command,
    looks_like_a_create,
    looks_like_a_search,
    wants_json,
)


SEARCH_PATHS = ["/api/_search", "/api/search", "/api/_query"]

COMMAND_PATHS = [
    "/api/_command",
    "/api/command",
    "/api/_run",
    "/api/run",
    "/api/_execute",
    "/api/execute",
]

CREATE_PATHS = [
    "/api/create",
    "/api/data",  # POST without search/command
]


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("application/json", True),
        ("text/json", True),
        ("text/plain", False),
        ("application/xml", False),
        ("text/html", False),
        (None, False),
    ],
)
def test_wants_json_with_content_type(make_request, content_type, expected):
    """Test wants_json with different content types, or none."""
    headers = {"Content-Type": content_type} if content_type is not None else None
    assert wants_json(make_request(headers=headers)) is expected


@pytest.mark.parametrize(("path", "expected"), [("/api/data.json", True), ("/api/data", False)])
def test_wants_json_with_path(make_request, path, expected):
    """Test wants_json with .json path."""
    assert wants_json(make_request(path)) is expected


@pytest.mark.parametrize(("path", "expected"), [*((path, True) for path in SEARCH_PATHS), ("/api/data", False)])
def test_looks_like_a_search(make_request, path, expected):
    """Test looks_like_a_search with different paths."""
    assert looks_like_a_search(make_request(path)) is expected


@pytest.mark.parametrize(("path", "expected"), [*((path, True) for path in COMMAND_PATHS), ("/api/data", False)])
def test_looks_like_a_command(make_request, path, expected):
    """Test looks_like_a_command with different paths."""
    assert looks_like_a_command(make_request(path)) is expected


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        *(("POST", path, True) for path in CREATE_PATHS),
        # POSTs to search and command paths are not creates.
        *(("POST", path, False) for path in SEARCH_PATHS + COMMAND_PATHS),
        ("GET", "/api/data", False),
    ],
)
def test_looks_like_a_create(make_request, method, path, expected):
    """Test looks_like_a_create with different scenarios."""
    assert looks_like_a_create(make_request(path, method=method)) is expected
