"""Custom exceptions for mockstack."""


def raise_for_missing(message: str, *args, **kwargs):
    """Raise an exception for a missing dependency."""
    raise RuntimeError(message)
