"""Unit tests for the templates module."""

import pytest
from fastapi import Request

from mockstack.templating import (
    iter_possible_template_arguments,
    iter_possible_template_filenames,
    parse_template_name_segments_and_identifiers,
)


@pytest.mark.parametrize(
    "path,expected_results",
    [
        (
            "/api/v1/projects/1234",
            [
                {
                    "name": "api-v1-projects.1234.j2",
                    "context": {
                        "projects": "1234",
                        "query": {},
                        "headers": {},
                        "request_json": None,
                    },
                    "media_type": "application/json",
                },
                {
                    "name": "api-v1-projects.j2",
                    "context": {
                        "projects": "1234",
                        "query": {},
                        "headers": {},
                        "request_json": None,
                    },
                    "media_type": "application/json",
                },
                {
                    "name": "index.j2",
                    "context": {
                        "projects": "1234",
                        "query": {},
                        "headers": {},
                        "request_json": None,
                    },
                    "media_type": "application/json",
                },
            ],
        ),
        (
            "/api/v1/users/3a4e5ad9-17ee-41af-972f-864dfccd4856",
            [
                {
                    "name": "api-v1-users.3a4e5ad9-17ee-41af-972f-864dfccd4856.j2",
                    "context": {
                        "users": "3a4e5ad9-17ee-41af-972f-864dfccd4856",
                        "query": {},
                        "headers": {},
                        "request_json": None,
                    },
                    "media_type": "application/json",
                },
                {
                    "name": "api-v1-users.j2",
                    "context": {
                        "users": "3a4e5ad9-17ee-41af-972f-864dfccd4856",
                        "query": {},
                        "headers": {},
                        "request_json": None,
                    },
                    "media_type": "application/json",
                },
                {
                    "name": "index.j2",
                    "context": {
                        "users": "3a4e5ad9-17ee-41af-972f-864dfccd4856",
                        "query": {},
                        "headers": {},
                        "request_json": None,
                    },
                    "media_type": "application/json",
                },
            ],
        ),
        (
            "/api/v1/projects",
            [
                {
                    "name": "api-v1-projects.j2",
                    "context": {"query": {}, "headers": {}, "request_json": None},
                    "media_type": "application/json",
                },
                {
                    "name": "index.j2",
                    "context": {"query": {}, "headers": {}, "request_json": None},
                    "media_type": "application/json",
                },
            ],
        ),
        (
            "/1234",
            [
                {
                    "name": "index.j2",
                    "context": {
                        "id": "1234",
                        "query": {},
                        "headers": {},
                        "request_json": None,
                    },
                    "media_type": "application/json",
                },
            ],
        ),
    ],
)
def test_iter_possible_template_arguments(
    path: str,
    expected_results: list,
) -> None:
    """Test the iter_possible_template_arguments function with various paths."""
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "headers": [],
        }
    )

    results = list(iter_possible_template_arguments(request))
    assert len(results) == len(expected_results)

    for actual, expected in zip(results, expected_results):
        assert actual["name"] == expected["name"]
        assert actual["context"] == expected["context"]
        assert actual["media_type"] == expected["media_type"]


def test_iter_possible_template_arguments_with_custom_media_type():
    """Test that custom media type from headers is respected."""
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/v1/projects",
            "query_string": b"",
            "headers": [(b"content-type", b"application/xml")],
        }
    )

    results = list(iter_possible_template_arguments(request))
    assert len(results) == 2
    assert results[0]["media_type"] == "application/xml"
    assert results[1]["media_type"] == "application/xml"
    # Check that headers are included in the context
    assert "headers" in results[0]["context"]
    assert "content-type" in results[0]["context"]["headers"]


def test_iter_possible_template_arguments_with_query_params():
    """Test that query parameters are included in the context."""
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/v1/projects",
            "query_string": b"filter=active&sort=name",
            "headers": [],
        }
    )

    results = list(iter_possible_template_arguments(request))
    assert len(results) == 2
    # Check that query parameters are included in the context
    assert "query" in results[0]["context"]
    assert results[0]["context"]["query"] == {"filter": "active", "sort": "name"}


def test_parse_template_name_segments_and_identifiers():
    """Test the parse_template_name_segments_and_identifiers function."""
    # Test with a simple path
    name_segments, identifiers = parse_template_name_segments_and_identifiers(
        "/api/v1/projects/1234", default_identifier_key="id"
    )
    assert name_segments == ["api", "v1", "projects"]
    assert identifiers == {"projects": "1234"}

    # Test with a path with no identifiers
    name_segments, identifiers = parse_template_name_segments_and_identifiers(
        "/api/v1/projects", default_identifier_key="id"
    )
    assert name_segments == ["api", "v1", "projects"]
    assert identifiers == {}

    # Test with a path with only an identifier
    name_segments, identifiers = parse_template_name_segments_and_identifiers(
        "/1234", default_identifier_key="id"
    )
    assert name_segments == []
    assert identifiers == {"id": "1234"}

    # Test with a path with multiple identifiers
    name_segments, identifiers = parse_template_name_segments_and_identifiers(
        "/api/v1/projects/1234/tasks/5678", default_identifier_key="id"
    )
    assert name_segments == ["api", "v1", "projects", "tasks"]
    assert identifiers == {"projects": "1234", "tasks": "5678"}


def test_iter_possible_template_filenames():
    """Test the iter_possible_template_filenames function."""
    # Test with name segments and context
    filenames = list(
        iter_possible_template_filenames(
            ["api", "v1", "projects"],
            identifiers={"projects": "1234"},
            template_file_separator="-",
            template_file_extension=".j2",
            default_template_name="index.j2",
        )
    )
    assert filenames == ["api-v1-projects.1234.j2", "api-v1-projects.j2", "index.j2"]

    # Test with name segments and no context
    filenames = list(
        iter_possible_template_filenames(
            ["api", "v1", "projects"],
            identifiers={},
            template_file_separator="-",
            template_file_extension=".j2",
            default_template_name="index.j2",
        )
    )
    assert filenames == ["api-v1-projects.j2", "index.j2"]

    # Test with no name segments and context
    filenames = list(
        iter_possible_template_filenames(
            [],
            identifiers={"id": "1234"},
            template_file_separator="-",
            template_file_extension=".j2",
            default_template_name="index.j2",
        )
    )
    assert filenames == ["index.j2"]

    # Test with no name segments and no context
    filenames = list(
        iter_possible_template_filenames(
            [],
            identifiers={},
            template_file_separator="-",
            template_file_extension=".j2",
            default_template_name="index.j2",
        )
    )
    assert filenames == ["index.j2"]

    # Test with custom separator and extension
    filenames = list(
        iter_possible_template_filenames(
            ["api", "v1", "projects"],
            identifiers={"projects": "1234"},
            template_file_separator="_",
            template_file_extension=".html",
            default_template_name="default.html",
        )
    )
    assert filenames == [
        "api_v1_projects.1234.html",
        "api_v1_projects.html",
        "default.html",
    ]
