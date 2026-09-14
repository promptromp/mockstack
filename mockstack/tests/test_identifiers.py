"""Unit tests for the identifiers module."""

import pytest

from mockstack.identifiers import looks_like_id, prefixes


@pytest.mark.parametrize(
    "items,reverse,expected",
    [
        ([1, 2, 3], False, [(1,), (1, 2), (1, 2, 3)]),
        ([1, 2, 3], True, [(1, 2, 3), (1, 2), (1,)]),
        ([], False, []),
        ([1], False, [(1,)]),
        (["a", "b", "c"], False, [("a",), ("a", "b"), ("a", "b", "c")]),
    ],
    ids=["basic", "reverse", "empty", "single-element", "strings"],
)
def test_prefixes(items, reverse, expected):
    assert list(prefixes(items, reverse=reverse)) == expected


@pytest.mark.parametrize(
    "chunk,expected,reason",
    [
        # Even length numeric IDs
        ("1234", True, "Even length numeric"),
        ("12", True, "Even length numeric"),
        ("1234567890", True, "Even length numeric"),
        # Odd length numeric IDs
        ("123", False, "Odd length numeric"),
        ("12345", False, "Odd length numeric"),
        # Even length hexadecimal IDs
        ("abcd", True, "Even length hex"),
        ("1234abcd", True, "Even length hex"),
        ("1234567890abcdef", True, "Even length hex"),
        # Odd length hexadecimal IDs
        ("abc", False, "Odd length hex"),
        ("1234567890abcde", False, "Odd length hex"),
        ("1234567890abcdefg", False, "Invalid hex character"),
        ("xyz", False, "Not hex"),
        # UUID format (36 characters with dashes)
        ("3a4e5ad9-17ee-41af-972f-864dfccd4856", True, "Valid UUID"),
        ("3A4E5AD9-17EE-41AF-972F-864DFCCD4856", True, "UUID with uppercase"),
        ("3a4e5ad917ee41af972f864dfccd4856", True, "UUID without dashes"),
        ("3a4e5ad9-17ee-41af-972f-864dfccd485", False, "UUID too short"),
        ("3a4e5ad9-17ee-41af-972f-864dfccd4856-", False, "UUID too long"),
        ("3a4e5ad9-17ee-41af-972f-864dfccd485g", False, "UUID with invalid char"),
        # Common non-ID path segments
        ("api", False, "Common path segment"),
        ("v1", False, "API version"),
        ("users", False, "Resource name"),
        ("projects", False, "Resource name"),
        ("index", False, "Page name"),
        ("create", False, "Action name"),
        ("update", False, "Action name"),
        ("delete", False, "Action name"),
        # Empty and whitespace strings
        ("", False, "Empty string"),
        (" ", False, "Whitespace"),
        ("\t", False, "Whitespace"),
        ("\n", False, "Whitespace"),
        ("  ", False, "Whitespace"),
        # Special characters
        ("12-34", False, "Hyphen in wrong place"),
        ("12_34", False, "Underscore"),
        ("12.34", False, "Period"),
        ("12/34", False, "Slash"),
        ("12+34", False, "Plus"),
        ("@1234", False, "At symbol"),
    ],
)
def test_looks_like_id(chunk: str, expected: bool, reason: str) -> None:
    """Test the looks_like_id function with various inputs.

    The test cases cover:
    1. Even and odd length numeric IDs
    2. Even and odd length hexadecimal IDs
    3. Valid and invalid UUID formats
    4. Common non-ID path segments
    5. Empty strings, whitespace and special characters
    """
    assert looks_like_id(chunk) == expected, f"Failed for {chunk!r} ({reason})"
