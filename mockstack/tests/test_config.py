"""Tests for mockstack.config: settings construction isolation."""

import json
import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from mockstack.config import CliSettings, OpenTelemetrySettings, Settings, SettingsDependencyError
from mockstack.constants import ProxyRulesRecordMode, ProxyRulesRedirectVia


@pytest.mark.parametrize("model", [Settings, CliSettings, OpenTelemetrySettings])
def test_every_setting_has_help_text(model):
    """Attribute docstrings become each setting's description, which ``--help`` shows."""
    assert [name for name, field in model.model_fields.items() if not field.description] == []


def test_settings_dependency_error_names_the_settings_plainly():
    """Outside the command line (e.g. ``uvicorn --factory``), the message names settings
    by their Python names; the CLI renders the same template with flags instead."""
    error = SettingsDependencyError("{templates_dir} is required when {strategy} is filefixtures")

    assert str(error) == "templates_dir is required when strategy is filefixtures"
    assert error.template == "{templates_dir} is required when {strategy} is filefixtures"
    assert error.settings == ("templates_dir", "strategy")


def test_settings_dependency_error_names_a_setting_in_a_group_with_a_dot():
    error = SettingsDependencyError("{opentelemetry.enabled} requires {strategy} to be proxyrules")

    assert str(error) == "opentelemetry.enabled requires strategy to be proxyrules"
    assert error.settings == ("opentelemetry.enabled", "strategy")


# Unprefixed variables named like the OpenTelemetry settings, as another program might set them.
UNPREFIXED_OPENTELEMETRY_ENV = {
    "ENABLED": "true",
    "ENDPOINT": "http://elsewhere:4317/",
    "CAPTURE_RESPONSE_BODY": "true",
}


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """No ``MOCKSTACK__*`` variables and no ``.env`` file: the settings come from defaults
    and whatever the test sets."""
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name.upper().startswith("MOCKSTACK__"):
            monkeypatch.delenv(name)


def test_opentelemetry_settings_ignore_unprefixed_environment_variables(isolated_env, monkeypatch):
    for name, value in UNPREFIXED_OPENTELEMETRY_ENV.items():
        monkeypatch.setenv(name, value)

    assert OpenTelemetrySettings().model_dump() == {
        "enabled": False,
        "endpoint": "http://localhost:4317/",
        "capture_response_body": False,
    }


def test_settings_ignore_unprefixed_opentelemetry_variables_at_import(isolated_env, tmp_path):
    """The default OpenTelemetry settings are built when mockstack.config is imported, so
    only a fresh interpreter shows whether unprefixed variables leak into them."""
    env = {name: value for name, value in os.environ.items() if not name.upper().startswith("MOCKSTACK__")}
    script = (
        f"from mockstack.config import Settings; print(Settings(templates_dir={str(tmp_path)!r}).model_dump_json())"
    )

    # S603: runs this interpreter on the script above, with no untrusted input.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={**env, **UNPREFIXED_OPENTELEMETRY_ENV},
        check=True,
    )

    assert json.loads(result.stdout)["opentelemetry"] == {
        "enabled": False,
        "endpoint": "http://localhost:4317/",
        "capture_response_body": False,
    }


def test_opentelemetry_settings_come_from_prefixed_environment_variables(isolated_env, monkeypatch, tmp_path):
    monkeypatch.setenv("MOCKSTACK__OPENTELEMETRY__ENABLED", "true")
    monkeypatch.setenv("MOCKSTACK__OPENTELEMETRY__ENDPOINT", "http://collector:4317/")

    settings = Settings(templates_dir=tmp_path)

    assert settings.opentelemetry.enabled is True
    assert settings.opentelemetry.endpoint == "http://collector:4317/"
    assert settings.opentelemetry.capture_response_body is False


def test_port_must_be_a_valid_port_number(make_settings, templates_dir):
    with pytest.raises(ValidationError, match="less than or equal to 65535"):
        make_settings(templates_dir=templates_dir, port=65536)


def test_make_settings_ignores_mockstack_env_vars(monkeypatch, make_settings, templates_dir):
    """A developer's exported ``MOCKSTACK__*`` environment variables must never leak
    into settings built by the shared ``make_settings`` fixture: otherwise a test
    could pass or fail depending on whatever happens to be set in the shell it runs
    in (see the reverse-proxy timeout regression this guards against).
    """
    monkeypatch.setenv("MOCKSTACK__DEBUG", "true")
    monkeypatch.setenv("MOCKSTACK__PROXYRULES_REVERSE_PROXY_TIMEOUT", "0.001")

    settings = make_settings(templates_dir=templates_dir)

    assert isinstance(settings, Settings)
    assert settings.debug is False
    assert settings.proxyrules_reverse_proxy_timeout == 10.0


def test_filefixtures_simulate_create_on_missing_env_var(monkeypatch, templates_dir):
    """``MOCKSTACK__FILEFIXTURES_SIMULATE_CREATE_ON_MISSING`` flips the setting.

    ``make_settings`` deliberately ignores ``MOCKSTACK__*`` environment variables
    (see above), so this constructs ``Settings`` directly to observe the env var.
    """
    settings_default = Settings(templates_dir=templates_dir)
    assert settings_default.filefixtures_simulate_create_on_missing is True

    monkeypatch.setenv("MOCKSTACK__FILEFIXTURES_SIMULATE_CREATE_ON_MISSING", "false")
    settings_disabled = Settings(templates_dir=templates_dir)
    assert settings_disabled.filefixtures_simulate_create_on_missing is False


def test_filefixtures_simulate_create_on_missing_cli_flag(templates_dir):
    """The pydantic-settings-generated CLI flag flips the setting."""
    # `_cli_parse_args` is a real pydantic-settings BaseSettings kwarg at runtime, but
    # mypy (without the pydantic plugin) checks the synthesized __init__ against the
    # model's own fields and doesn't know about it.
    settings_default = CliSettings(_cli_parse_args=["--templates-dir", templates_dir])  # type: ignore[call-arg]
    assert settings_default.filefixtures_simulate_create_on_missing is True

    settings_disabled = CliSettings(
        _cli_parse_args=[  # type: ignore[call-arg]
            "--templates-dir",
            templates_dir,
            "--no-filefixtures-simulate-create-on-missing",
        ]
    )
    assert settings_disabled.filefixtures_simulate_create_on_missing is False


def test_filefixtures_without_templates_dir_names_the_right_strategy():
    with pytest.raises(ValueError, match="templates_dir is required when strategy is filefixtures"):
        Settings(strategy="filefixtures", templates_dir=None)


def test_openapi_docs_enabled_defaults_to_off(make_settings, templates_dir):
    assert make_settings(templates_dir=templates_dir).openapi_docs_enabled is False


def test_openapi_docs_enabled_env_var(monkeypatch, templates_dir):
    """``MOCKSTACK__OPENAPI_DOCS_ENABLED`` turns FastAPI's documentation routes on."""
    monkeypatch.setenv("MOCKSTACK__OPENAPI_DOCS_ENABLED", "true")

    assert Settings(templates_dir=templates_dir).openapi_docs_enabled is True


def test_openapi_docs_enabled_cli_flag(templates_dir):
    """``--openapi-docs-enabled`` turns the documentation routes on and its ``--no-`` form off."""
    enabled = CliSettings(
        _cli_parse_args=["--templates-dir", templates_dir, "--openapi-docs-enabled"]  # type: ignore[call-arg]
    )
    assert enabled.openapi_docs_enabled is True

    disabled = CliSettings(
        _cli_parse_args=["--templates-dir", templates_dir, "--no-openapi-docs-enabled"]  # type: ignore[call-arg]
    )
    assert disabled.openapi_docs_enabled is False


def test_record_mode_defaults_to_off(make_settings, templates_dir):
    settings = make_settings(templates_dir=templates_dir)
    assert settings.proxyrules_record_mode == ProxyRulesRecordMode.OFF
    assert settings.proxyrules_record_root is None


def test_record_mode_requires_a_record_root(make_settings, proxyrules_rules_filename):
    with pytest.raises(ValueError, match="proxyrules_record_root is required when proxyrules_record_mode is not off"):
        make_settings(
            strategy="proxyrules",
            proxyrules_rules_filename=proxyrules_rules_filename,
            proxyrules_record_mode="missing",
        )


def test_record_mode_requires_reverse_proxy(make_settings, proxyrules_rules_filename, tmp_path):
    with pytest.raises(ValueError, match="proxyrules_record_mode requires proxyrules_redirect_via to be reverse_proxy"):
        make_settings(
            strategy="proxyrules",
            proxyrules_rules_filename=proxyrules_rules_filename,
            proxyrules_record_mode="overwrite",
            proxyrules_record_root=tmp_path,
            proxyrules_redirect_via=ProxyRulesRedirectVia.HTTP_TEMPORARY_REDIRECT,
        )


def test_record_root_must_be_an_existing_directory(make_settings, proxyrules_rules_filename, tmp_path):
    with pytest.raises(ValueError, match="proxyrules_record_root"):
        make_settings(
            strategy="proxyrules",
            proxyrules_rules_filename=proxyrules_rules_filename,
            proxyrules_record_mode="missing",
            proxyrules_record_root=tmp_path / "absent",
        )


def test_record_mode_validation_is_scoped_to_proxyrules(make_settings, templates_dir):
    """M-f: the record-mode checks apply only to the proxyrules strategy, so a
    filefixtures instance can set proxyrules_record_mode without also setting a
    record root."""
    settings = make_settings(
        strategy="filefixtures",
        templates_dir=templates_dir,
        proxyrules_record_mode="missing",
    )
    assert settings.proxyrules_record_mode == ProxyRulesRecordMode.MISSING
    assert settings.proxyrules_record_root is None


def test_record_settings_from_env_vars(monkeypatch, templates_dir, tmp_path):
    """``make_settings`` ignores ``MOCKSTACK__*``, so this builds ``Settings`` directly."""
    monkeypatch.setenv("MOCKSTACK__PROXYRULES_RECORD_MODE", "missing")
    monkeypatch.setenv("MOCKSTACK__PROXYRULES_RECORD_ROOT", str(tmp_path))
    settings = Settings(templates_dir=templates_dir)
    assert settings.proxyrules_record_mode == ProxyRulesRecordMode.MISSING
    assert settings.proxyrules_record_root == tmp_path


def test_record_settings_from_cli_flags(templates_dir, tmp_path):
    settings = CliSettings(
        _cli_parse_args=[  # type: ignore[call-arg]
            "--templates-dir",
            templates_dir,
            "--proxyrules-record-mode",
            "overwrite",
            "--proxyrules-record-root",
            str(tmp_path),
        ]
    )
    assert settings.proxyrules_record_mode == ProxyRulesRecordMode.OVERWRITE
    assert settings.proxyrules_record_root == tmp_path


def test_record_scrubber_defaults_to_none(templates_dir):
    assert Settings(templates_dir=templates_dir).proxyrules_record_scrubber is None


def test_record_scrubber_from_env_var_imports_the_callable(monkeypatch, templates_dir):
    """``make_settings`` ignores ``MOCKSTACK__*``, so this builds ``Settings`` directly."""
    monkeypatch.setenv("MOCKSTACK__PROXYRULES_RECORD_SCRUBBER", "json:dumps")
    settings = Settings(templates_dir=templates_dir)
    assert settings.proxyrules_record_scrubber is json.dumps


def test_record_scrubber_from_cli_flag_imports_the_callable(templates_dir):
    settings = CliSettings(
        _cli_parse_args=[  # type: ignore[call-arg]
            "--templates-dir",
            templates_dir,
            "--proxyrules-record-scrubber",
            "json:dumps",
        ]
    )
    assert settings.proxyrules_record_scrubber is json.dumps


@pytest.mark.parametrize(
    "reference",
    ["no_such_module_for_mockstack:scrub", "json:no_such_function", "json:__doc__"],
    ids=["unimportable-module", "missing-attribute", "not-callable"],
)
def test_record_scrubber_rejects_a_bad_reference(templates_dir, reference):
    with pytest.raises((ValidationError, ValueError), match="proxyrules_record_scrubber"):
        Settings(templates_dir=templates_dir, proxyrules_record_scrubber=reference)
