"""Unit tests for the identifiers module."""

import pytest

from mockstack.identifiers import looks_like_id, prefixes


def test_prefixes():
    # Test basic functionality
    assert list(prefixes([1, 2, 3])) == [(1,), (1, 2), (1, 2, 3)]

    # Test with reverse=True
    assert list(prefixes([1, 2, 3], reverse=True)) == [(1, 2, 3), (1, 2), (1,)]

    # Test with empty list
    assert list(prefixes([])) == []

    # Test with single element
    assert list(prefixes([1])) == [(1,)]

    # Test with strings
    assert list(prefixes(["a", "b", "c"])) == [("a",), ("a", "b"), ("a", "b", "c")]


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
    ],
)
def test_looks_like_id(chunk: str, expected: bool, reason: str) -> None:
    """Test the looks_like_id function with various inputs.

    The test cases cover:
    1. Even and odd length numeric IDs
    2. Even and odd length hexadecimal IDs
    3. Valid and invalid UUID formats
    4. Common non-ID path segments
    """
    assert looks_like_id(chunk) == expected, f"Failed for {chunk} ({reason})"


def test_looks_like_id_empty_string():
    """Test that empty string is not considered an ID."""
    assert not looks_like_id("")


def test_looks_like_id_whitespace():
    """Test that whitespace is not considered an ID."""
    assert not looks_like_id(" ")
    assert not looks_like_id("\t")
    assert not looks_like_id("\n")
    assert not looks_like_id("  ")


def test_looks_like_id_special_chars():
    """Test that strings with special characters are not considered IDs."""
    assert not looks_like_id("12-34")  # Hyphen in wrong place
    assert not looks_like_id("12_34")  # Underscore
    assert not looks_like_id("12.34")  # Period
    assert not looks_like_id("12/34")  # Slash
    assert not looks_like_id("12+34")  # Plus
    assert not looks_like_id("@1234")  # At symbol
