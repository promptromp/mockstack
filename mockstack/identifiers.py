"""Identifiers helpers."""

import itertools


def prefixes(iterable, reverse=False):
    """Return an iterator of the prefixes of the iterable.

    Examples:
    ---------
    >>> list(prefixes([1, 2, 3]))
    [(1,), (1, 2), (1, 2, 3)]

    >>> list(prefixes([1, 2, 3], reverse=True))
    [(1, 2, 3), (1, 2), (1,)]

    """
    iterator = itertools.accumulate(map(lambda x: (x,), iterable))
    if reverse:
        return reversed(list(iterator))
    return iterator


def looks_like_id(segment: str) -> bool:
    """Check if a URL path segment looks like an ID.

    Identifiers are typically numeric or hexadecimal (e.g. UUIDs) and are used to identify a resource.

    We apply a few simple heuristics to try and provide a good balance between false positives and false negatives.

    Examples:
    ---------
    >>> looks_like_id("123")
    False  # Odd length numeric

    >>> looks_like_id("1234567890")
    True   # Even length numeric

    >>> looks_like_id("1234567890abcdef")
    True   # Even length hex

    >>> looks_like_id("3a4e5ad9-17ee-41af-972f-864dfccd4856")
    True   # UUID with dashes

    >>> looks_like_id("3a4e5ad917ee41af972f864dfccd4856")
    True   # UUID without dashes

    >>> looks_like_id("project")
    False  # Not a valid ID format

    >>> looks_like_id("api")
    False  # Not a valid ID format

    >>> looks_like_id("v1")
    False  # Not a valid ID format

    """
    if not segment or segment.isspace():
        return False

    # Check for special characters that aren't allowed in IDs
    if any(c in segment for c in "_./+@"):
        return False

    N = len(segment)

    # Check for UUID format (with or without dashes)
    if N == 36:
        # UUID with dashes
        parts = segment.lower().split("-")
        if len(parts) == 5 and all(
            all(c in "0123456789abcdef" for c in p) for p in parts
        ):
            lengths = [len(p) for p in parts]
            if lengths == [8, 4, 4, 4, 12]:
                return True
    elif N == 32:
        # UUID without dashes
        return all(c in "0123456789abcdefABCDEF" for c in segment)

    # Check for even length numeric or hex
    return (N % 2 == 0 and segment.isdigit()) or (
        N % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in segment)
    )
