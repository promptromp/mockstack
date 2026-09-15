"""Tests for the ``mockstack`` command line: help, ``--version`` and configuration errors."""

import os
import re
from importlib import metadata

import pytest
from pydantic import ValidationError
from pydantic_settings import CliSettingsSource

from mockstack.cli import SettingName, build_parser, report_for, setting_name
from mockstack.config import CliSettings, OpenTelemetrySettings, Settings
from mockstack.main import run


# Environment variables that change whether and how rich colours and wraps its output.
TERMINAL_ENV_VARS = ("FORCE_COLOR", "NO_COLOR", "TTY_COMPATIBLE", "TTY_INTERACTIVE", "COLUMNS")

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

HELP_HINT = "Run 'mockstack --help' to see all options.\n"


@pytest.fixture
def served(monkeypatch, tmp_path):
    """Run the CLI from an empty directory, with no ``MOCKSTACK__*`` or terminal
    variables, recording ``uvicorn.run`` calls instead of starting a server."""
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name.upper().startswith("MOCKSTACK__") or name in TERMINAL_ENV_VARS:
            monkeypatch.delenv(name)
    calls: list[dict] = []
    monkeypatch.setattr("mockstack.main.uvicorn.run", lambda app, **kwargs: calls.append({"app": app, **kwargs}))
    return calls


def fail(argv, capsys):
    """Run the CLI expecting a configuration error, and return what it printed."""
    with pytest.raises(SystemExit) as excinfo:
        run(argv)
    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert captured.out == ""
    assert "Traceback" not in captured.err
    return captured.err


def test_run_serves_the_parsed_settings(served, tmp_path):
    run(["--templates-dir", str(tmp_path), "--host", "127.0.0.1", "--port", "9001"])

    [call] = served
    assert (call["host"], call["port"]) == ("127.0.0.1", 9001)


def test_run_without_arguments_names_the_missing_setting(served, capsys):
    assert fail([], capsys) == (
        "mockstack: error: --templates-dir is required when --strategy is filefixtures (the default)\n"
        "  environment or .env: MOCKSTACK__TEMPLATES_DIR, MOCKSTACK__STRATEGY\n" + HELP_HINT
    )
    assert served == []


@pytest.mark.parametrize(
    ("argv", "error", "env_var"),
    [
        (
            ["--templates-dir", "/does/not/exist"],
            "invalid value '/does/not/exist' for --templates-dir: path does not point to a directory",
            "MOCKSTACK__TEMPLATES_DIR",
        ),
        (
            ["--port", "abc"],
            "invalid value 'abc' for --port: input should be a valid integer, unable to parse string as an integer",
            "MOCKSTACK__PORT",
        ),
        (
            ["--strategy", "nope"],
            "invalid value 'nope' for --strategy: input should be 'filefixtures' or 'proxyrules'",
            "MOCKSTACK__STRATEGY",
        ),
        (
            ["--proxyrules-record-mode", "sometimes"],
            "invalid value 'sometimes' for --proxyrules-record-mode: input should be 'off', 'missing' or 'overwrite'",
            "MOCKSTACK__PROXYRULES_RECORD_MODE",
        ),
        (
            ["--proxyrules-record-scrubber", "no_such_module_for_mockstack:scrub"],
            (
                "invalid value 'no_such_module_for_mockstack:scrub' for --proxyrules-record-scrubber: "
                "invalid python path: No module named 'no_such_module_for_mockstack'"
            ),
            "MOCKSTACK__PROXYRULES_RECORD_SCRUBBER",
        ),
    ],
    ids=["missing-directory", "not-an-integer", "unknown-strategy", "unknown-enum-value", "unimportable-scrubber"],
)
def test_invalid_setting_is_named_with_its_value(served, capsys, tmp_path, argv, error, env_var):
    assert fail(["--templates-dir", str(tmp_path), *argv], capsys) == (
        f"mockstack: error: {error}\n  environment or .env: {env_var}\n" + HELP_HINT
    )


def test_invalid_nested_environment_variable_is_named_by_its_flag(served, capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("MOCKSTACK__OPENTELEMETRY__ENABLED", "maybe")

    assert fail(["--templates-dir", str(tmp_path)], capsys) == (
        "mockstack: error: invalid value 'maybe' for --opentelemetry.enabled: "
        "input should be a valid boolean, unable to interpret input\n"
        "  environment or .env: MOCKSTACK__OPENTELEMETRY__ENABLED\n" + HELP_HINT
    )


def test_invalid_dotenv_value_is_reported(served, capsys, tmp_path):
    (tmp_path / ".env").write_text("MOCKSTACK__PORT=abc\n")

    error = fail(["--templates-dir", str(tmp_path)], capsys)

    assert error.startswith("mockstack: error: invalid value 'abc' for --port: input should be a valid integer")


def test_setting_without_a_flag_is_named_by_its_environment_variable(served, capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("MOCKSTACK__MISSING_RESOURCE_FIELDS", "[1]")

    assert fail(["--templates-dir", str(tmp_path)], capsys) == (
        "mockstack: error: MOCKSTACK__MISSING_RESOURCE_FIELDS: input should be a valid dictionary\n" + HELP_HINT
    )


def test_every_invalid_setting_is_reported_at_once(served, capsys):
    assert fail(["--port", "abc", "--strategy", "nope", "--templates-dir", "/does/not/exist"], capsys) == (
        "mockstack: error: 3 invalid settings\n"
        "  invalid value 'abc' for --port: input should be a valid integer, unable to parse string as an integer\n"
        "  invalid value 'nope' for --strategy: input should be 'filefixtures' or 'proxyrules'\n"
        "  invalid value '/does/not/exist' for --templates-dir: path does not point to a directory\n"
        "  environment or .env: MOCKSTACK__PORT, MOCKSTACK__STRATEGY, MOCKSTACK__TEMPLATES_DIR\n" + HELP_HINT
    )


@pytest.mark.parametrize(
    ("argv", "error", "env_vars"),
    [
        (
            ["--strategy", "proxyrules"],
            "--proxyrules-rules-filename is required when --strategy is proxyrules",
            "MOCKSTACK__PROXYRULES_RULES_FILENAME, MOCKSTACK__STRATEGY",
        ),
        (
            [
                "--strategy",
                "proxyrules",
                "--proxyrules-rules-filename",
                "{rules}",
                "--proxyrules-record-mode",
                "missing",
            ],
            "--proxyrules-record-root is required when --proxyrules-record-mode is not off",
            "MOCKSTACK__PROXYRULES_RECORD_ROOT, MOCKSTACK__PROXYRULES_RECORD_MODE",
        ),
        (
            [
                "--strategy",
                "proxyrules",
                "--proxyrules-rules-filename",
                "{rules}",
                "--proxyrules-record-mode",
                "missing",
                "--proxyrules-record-root",
                "{directory}",
                "--proxyrules-redirect-via",
                "http_307_temporary",
            ],
            "--proxyrules-record-mode requires --proxyrules-redirect-via to be reverse_proxy",
            "MOCKSTACK__PROXYRULES_RECORD_MODE, MOCKSTACK__PROXYRULES_REDIRECT_VIA",
        ),
    ],
    ids=["rules-file-for-proxyrules", "record-root-for-record-mode", "reverse-proxy-for-record-mode"],
)
def test_settings_that_depend_on_each_other_are_named_by_flag(
    served, capsys, tmp_path, proxyrules_rules_filename, argv, error, env_vars
):
    argv = [arg.format(rules=proxyrules_rules_filename, directory=tmp_path) for arg in argv]

    assert fail(argv, capsys) == f"mockstack: error: {error}\n  environment or .env: {env_vars}\n" + HELP_HINT


def test_unparseable_environment_variable_is_reported(served, capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("MOCKSTACK__LOGGING", "{not json")

    error = fail(["--templates-dir", str(tmp_path)], capsys)

    assert error.startswith('mockstack: error: error parsing value for field "logging" from source "EnvSettingsSource"')


def test_rules_file_that_does_not_load_names_the_file_and_rule(served, capsys, tmp_path):
    rules = tmp_path / "rules.yml"
    rules.write_text("rules:\n  - pattern: ^/a\n    replacement: u\n  - name: second\n    replacement: u\n")

    assert fail(["--strategy", "proxyrules", "--proxyrules-rules-filename", str(rules)], capsys) == (
        f"mockstack: error: {rules}: rule #2 ('second'): 'pattern' is required\n"
    )


@pytest.mark.parametrize(
    ("argv", "hint"),
    [
        (["--template-dir", "templates"], "  --template-dir: did you mean --templates-dir?\n"),
        (["--prot=80"], "  --prot: did you mean --port?\n"),
        (["--zzz"], ""),
    ],
    ids=["typo-with-value", "typo-with-equals", "nothing-close"],
)
def test_unrecognized_flag_suggests_the_closest_one(served, capsys, argv, hint):
    assert fail(argv, capsys) == f"mockstack: error: unrecognized arguments: {' '.join(argv)}\n{hint}" + HELP_HINT


def test_flag_without_its_value_is_reported_without_the_usage_text(served, capsys):
    assert fail(["--port"], capsys) == "mockstack: error: argument --port: expected one argument\n" + HELP_HINT


def test_errors_are_coloured_only_when_colour_is_forced(served, capsys, monkeypatch):
    plain = fail([], capsys)
    assert ANSI_ESCAPE.search(plain) is None

    monkeypatch.setenv("FORCE_COLOR", "1")
    coloured = fail([], capsys)

    assert ANSI_ESCAPE.search(coloured) is not None
    assert ANSI_ESCAPE.sub("", coloured) == plain


def test_version_flag_prints_the_installed_version(served, capsys):
    with pytest.raises(SystemExit) as excinfo:
        run(["--version"])

    assert excinfo.value.code == 0
    assert capsys.readouterr().out == f"mockstack {metadata.version('mockstack')}\n"


def test_help_describes_the_options_and_environment_variables(served, capsys):
    with pytest.raises(SystemExit) as excinfo:
        run(["--help"])

    assert excinfo.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "--port int Port to run the server on. (default: 8000)" in help_text
    assert "MOCKSTACK__TEMPLATES_DIR" in help_text


def test_report_names_what_it_can_of_each_error_location():
    """An error about the settings as a whole keeps its message; a location that runs past
    a plain setting is named by that setting."""
    exc = ValidationError.from_exception_data(
        "CliSettings",
        [
            {"type": "value_error", "loc": (), "input": {}, "ctx": {"error": ValueError("settings conflict")}},
            {"type": "int_parsing", "loc": ("port", "[key]"), "input": "abc"},
        ],
    )

    report = report_for(exc)

    assert [problem.plain for problem in report.problems] == [
        "settings conflict",
        "invalid value 'abc' for --port: input should be a valid integer, unable to parse string as an integer",
    ]
    assert report.settings == [SettingName(flag="--port", env_var="MOCKSTACK__PORT")]


def test_setting_name_rejects_a_path_below_a_plain_setting():
    with pytest.raises(ValueError, match=r"not a setting: port\.number"):
        setting_name(("port", "number"))


def test_setting_name_for_a_nested_setting():
    assert setting_name(("opentelemetry", "enabled")) == SettingName(
        flag="--opentelemetry.enabled", env_var="MOCKSTACK__OPENTELEMETRY__ENABLED"
    )


def test_setting_names_match_the_generated_flags():
    """Every flag an error names is one the parser really has; settings without one are
    named by their environment variable."""
    parser = build_parser()
    CliSettingsSource(CliSettings, root_parser=parser)
    paths: list[tuple[str, ...]] = [(name,) for name in Settings.model_fields]
    paths += [("opentelemetry", name) for name in OpenTelemetrySettings.model_fields]

    names = {path: setting_name(path) for path in paths}

    assert {name.flag for name in names.values() if name.flag is not None} <= set(parser._option_string_actions)
    assert {path for path, name in names.items() if name.flag is None} == {
        ("opentelemetry",),
        ("created_resource_metadata",),
        ("missing_resource_fields",),
        ("logging",),
    }
