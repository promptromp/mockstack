"""Identifiers helpers."""


def looks_like_id(chunk: str) -> bool:
    """Check if a URL path segment looks like an ID.

    Identifiers are typically numeric or alphanumeric (e.g. UUIDs) and are used to identify a resource.

    We apply a couple of simple heuristics to determine if a segment looks like an ID:
    - It must be numeric and have an even number of characters.
    - Or, It must be a hexdecimal string with an even number of characters.
    - Or, It must be a valid UUID4 (36 characters, alphanumeric, and dashes).

    Examples:
    >>> looks_like_id("123")
    True
    >>> looks_like_id("1234567890")
    True
    >>> looks_like_id("1234567890abcdef")
    True
    >>> looks_like_id("3a4e5ad9-17ee-41af-972f-864dfccd4856")
    True
    >>> looks_like_id("project")
    False
    >>> looks_like_id("api")
    False
    >>> looks_like_id("v1")
    False

    """
    N = len(chunk)
    return (
        (N % 2 == 0 and chunk.isdigit())
        or (N % 2 == 0 and all(c in "0123456789abcdef" for c in chunk))
        or (N == 36 and all(c in "0123456789abcdef-" for c in chunk))
    )
