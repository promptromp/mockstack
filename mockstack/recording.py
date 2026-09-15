"""Record mode for the proxyrules strategy: the file-level building blocks.

A recorded fixture is an ordinary Jinja template that renders back to the upstream body
it was recorded from. It starts with ``RECORDED_MARKER`` so that ``overwrite`` mode can
tell it from a hand-written fixture.
"""

import importlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Final, Protocol, cast

from fastapi import Request


RECORDED_MARKER: Final = "{# mockstack:recorded #}"

# Template text a body must not contain: the openers of Jinja expressions, statements
# and comments, and carriage returns, which Jinja normalises in template text. A "{"
# directly before a carriage return is taken with it, since the expression printing
# the carriage return starts with "{{" and would otherwise follow that brace.
_TEMPLATE_SENSITIVE_RE = re.compile(r"\{[{%#\r]|\r")


def encode_fixture(body: str) -> str:
    """A fixture template, starting with ``RECORDED_MARKER``, that renders exactly ``body``.

    Every template-sensitive sequence in ``body`` is printed by a Jinja string expression,
    so nothing in the body is ever evaluated. A body ending in a newline gets one more,
    because Jinja drops a single trailing newline from template source.
    """
    encoded = _TEMPLATE_SENSITIVE_RE.sub(lambda match: "{{ " + json.dumps(match.group(0)) + " }}", body)
    if body.endswith("\n"):
        encoded += "\n"
    return RECORDED_MARKER + encoded


def is_recorded(path: Path) -> bool:
    """True when ``path`` is a readable file whose content starts with ``RECORDED_MARKER``."""
    marker = RECORDED_MARKER.encode()
    try:
        with path.open("rb") as file:
            return file.read(len(marker)) == marker
    except OSError:
        return False


def resolve_inside(root: Path, path: Path) -> Path | None:
    """``path`` resolved through any symlinks, or ``None`` unless it lies strictly inside
    ``root`` (also resolved)."""
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved == resolved_root or not resolved.is_relative_to(resolved_root):
        return None
    return resolved


def write_fixture_atomically(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` as UTF-8 with newlines untranslated, creating parent
    directories.

    The text goes to a temporary file in the same directory, which is then renamed over
    ``path``. A concurrent reader sees the old file or the new one, never a partial
    write, and the temporary file never outlives the call.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".mockstack-record-", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        temporary.chmod(0o644)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class Scrubber(Protocol):
    """Called with every body before it is recorded: returns the text to write, or ``None``
    to skip recording that response."""

    def __call__(self, body: str, *, request: Request, rule_name: str | None, path: Path) -> str | None: ...


def load_scrubber(reference: str) -> Scrubber:
    """Import the ``module:function`` scrubber named by ``reference``.

    Raises ``ValueError``, naming the setting, when the reference is malformed, the module
    cannot be imported, or the attribute is not callable.
    """
    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError(f"proxyrules_record_scrubber must look like 'module:function', got {reference!r}")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(f"proxyrules_record_scrubber: cannot import {module_name!r}: {exc}") from exc
    scrubber = getattr(module, attribute, None)
    if not callable(scrubber):
        # Every proxyrules_record_scrubber mistake is a ValueError naming the setting.
        raise ValueError(  # noqa: TRY004
            f"proxyrules_record_scrubber: {reference!r} is not a callable"
        )
    return cast(Scrubber, scrubber)
