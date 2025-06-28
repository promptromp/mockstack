"""Helpers for deducing user intent from a request."""

from fastapi import Request


def wants_json(request: Request) -> bool:
    """Check if the request wants JSON response."""
    content_type = request.headers.get("Content-Type", "")
    return any(
        (
            content_type.startswith("application/json"),
            content_type.startswith("text/json"),
            request.url.path.endswith(".json"),
        )
    )


def looks_like_a_search(request: Request) -> bool:
    """Check if the request looks like a search.

    This is a heuristic to try and identify cases where a POST
    request is used for issuing a search rather than for creating
    a new resource.

    """
    return any(
        (
            request.url.path.endswith("_search"),
            request.url.path.endswith("/search"),
            request.url.path.endswith("_query"),
            request.url.path.endswith("/query"),
        )
    )


def looks_like_a_command(request: Request) -> bool:
    """Check if the request looks like a command.

    This is a heuristic to try and identify cases where a POST
    request is used for issuing a command rather than for creating
    a new resource.
    """
    return any(
        (
            request.url.path.endswith("_command"),
            request.url.path.endswith("/command"),
            request.url.path.endswith("_cmd"),
            request.url.path.endswith("/cmd"),
            request.url.path.endswith("_run"),
            request.url.path.endswith("/run"),
            request.url.path.endswith("_execute"),
            request.url.path.endswith("/execute"),
        )
    )


def looks_like_a_create(request: Request) -> bool:
    """Check if the request looks like a create.

    This is a heuristic to try and identify cases where a POST
    request is used for creating a new resource.

    """
    return any(
        (
            request.method == "POST"
            and not any(
                (
                    looks_like_a_search(request),
                    looks_like_a_command(request),
                )
            ),
            request.url.path.endswith("/create"),
        ),
    )
