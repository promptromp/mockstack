"""The installed ``mockstack`` command, run as a real process."""

import os
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest


pytestmark = pytest.mark.slow

# The console script installed next to the interpreter running the tests.
MOCKSTACK = Path(sys.executable).with_name("mockstack")

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

# Environment variables that change whether and how rich colours and wraps its output.
TERMINAL_ENV_VARS = frozenset(
    {"FORCE_COLOR", "NO_COLOR", "TTY_COMPATIBLE", "TTY_INTERACTIVE", "COLUMNS", "TERM", "COLORTERM"}
)


def mockstack(cwd: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run ``mockstack`` in ``cwd`` without the caller's ``MOCKSTACK__*`` or terminal variables."""
    inherited = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith("MOCKSTACK__") and name not in TERMINAL_ENV_VARS
    }
    # S603: a fixed executable, with arguments the tests control.
    return subprocess.run(  # noqa: S603
        [str(MOCKSTACK), *args],
        cwd=cwd,
        env=inherited | env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_mockstack_without_arguments_names_the_missing_setting(tmp_path):
    result = mockstack(tmp_path)

    assert result.returncode == 2
    assert result.stderr.startswith("mockstack: error: --templates-dir is required when --strategy is filefixtures")
    assert "Traceback" not in result.stderr
    assert ANSI_ESCAPE.search(result.stderr) is None


def test_mockstack_colours_errors_when_colour_is_forced(tmp_path):
    plain = mockstack(tmp_path).stderr

    coloured = mockstack(tmp_path, FORCE_COLOR="1").stderr

    assert ANSI_ESCAPE.search(coloured) is not None
    assert ANSI_ESCAPE.sub("", coloured) == plain


def test_mockstack_version(tmp_path):
    result = mockstack(tmp_path, "--version")

    assert result.returncode == 0
    assert result.stdout == f"mockstack {metadata.version('mockstack')}\n"
