"""Scrubbers for mockstack record mode: mask personal data before a fixture is written."""

import re
from pathlib import Path

from fastapi import Request


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def mask_emails(body: str, *, request: Request, rule_name: str | None, path: Path) -> str | None:
    """Replace every e-mail address in a recorded body with ``***@***``."""
    return EMAIL.sub("***@***", body)
