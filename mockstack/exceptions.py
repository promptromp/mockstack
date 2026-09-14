"""Custom exceptions for mockstack."""

from typing import Any, NoReturn


def raise_for_missing(message: str, *args: Any, **kwargs: Any) -> NoReturn:
    """Raise an exception for a missing dependency."""
    raise RuntimeError(message)
