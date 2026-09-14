"""Unit tests for the templates module."""

import pytest

from mockstack.templating import (
    iter_possible_template_arguments,
    iter_possible_template_filenames,
    parse_template_name_segments_and_identifiers,
)


@pytest.mark.parametrize(
    ("path", "expected_results"),
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
    make_request,
    path: str,
    expected_results: list,
) -> None:
    """Test the iter_possible_template_arguments function with various paths."""
    results = list(iter_possible_template_arguments(make_request(path)))
    assert len(results) == len(expected_results)

    for actual, expected in zip(results, expected_results):
        assert actual["name"] == expected["name"]
        assert actual["context"] == expected["context"]
        assert actual["media_type"] == expected["media_type"]


def test_iter_possible_template_arguments_with_custom_media_type(make_request):
    """Test that custom media type from headers is respected."""
    request = make_request("/api/v1/projects", headers={"content-type": "application/xml"})

    results = list(iter_possible_template_arguments(request))
    assert len(results) == 2
    assert results[0]["media_type"] == "application/xml"
    assert results[1]["media_type"] == "application/xml"
    # Check that headers are included in the context
    assert "headers" in results[0]["context"]
    assert "content-type" in results[0]["context"]["headers"]


def test_iter_possible_template_arguments_with_query_params(make_request):
    """Test that query parameters are included in the context."""
    request = make_request("/api/v1/projects", query=b"filter=active&sort=name")

    results = list(iter_possible_template_arguments(request))
    assert len(results) == 2
    # Check that query parameters are included in the context
    assert "query" in results[0]["context"]
    assert results[0]["context"]["query"] == {"filter": "active", "sort": "name"}


@pytest.mark.parametrize(
    ("path", "expected_segments", "expected_identifiers"),
    [
        ("/api/v1/projects/1234", ["api", "v1", "projects"], {"projects": "1234"}),
        ("/api/v1/projects", ["api", "v1", "projects"], {}),
        ("/1234", [], {"id": "1234"}),
        (
            "/api/v1/projects/1234/tasks/5678",
            ["api", "v1", "projects", "tasks"],
            {"projects": "1234", "tasks": "5678"},
        ),
    ],
    ids=[
        "nested-identifier",
        "no-identifier",
        "only-an-identifier",
        "multiple-identifiers",
    ],
)
def test_parse_template_name_segments_and_identifiers(path, expected_segments, expected_identifiers):
    """Test the parse_template_name_segments_and_identifiers function."""
    name_segments, identifiers = parse_template_name_segments_and_identifiers(path, default_identifier_key="id")
    assert name_segments == expected_segments
    assert identifiers == expected_identifiers


@pytest.mark.parametrize(
    ("name_segments", "identifiers", "separator", "extension", "default_name", "expected"),
    [
        (
            ["api", "v1", "projects"],
            {"projects": "1234"},
            "-",
            ".j2",
            "index.j2",
            ["api-v1-projects.1234.j2", "api-v1-projects.j2", "index.j2"],
        ),
        (
            ["api", "v1", "projects"],
            {},
            "-",
            ".j2",
            "index.j2",
            ["api-v1-projects.j2", "index.j2"],
        ),
        ([], {"id": "1234"}, "-", ".j2", "index.j2", ["index.j2"]),
        ([], {}, "-", ".j2", "index.j2", ["index.j2"]),
        (
            ["api", "v1", "projects"],
            {"projects": "1234"},
            "_",
            ".html",
            "default.html",
            ["api_v1_projects.1234.html", "api_v1_projects.html", "default.html"],
        ),
    ],
    ids=[
        "segments-and-identifiers",
        "segments-only",
        "identifiers-only",
        "neither",
        "custom-separator-and-extension",
    ],
)
def test_iter_possible_template_filenames(name_segments, identifiers, separator, extension, default_name, expected):
    """Test the iter_possible_template_filenames function."""
    filenames = iter_possible_template_filenames(
        name_segments,
        identifiers=identifiers,
        template_file_separator=separator,
        template_file_extension=extension,
        default_template_name=default_name,
    )
    assert list(filenames) == expected
