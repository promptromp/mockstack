"""Custom exceptions for mockstack."""


def raise_for_missing(message: str):
    """Raise an exception for a missing dependency."""
    raise ValueError(message)
