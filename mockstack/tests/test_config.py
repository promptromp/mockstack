"""Tests for mockstack.config: settings construction isolation."""

import pytest

from mockstack.config import CliSettings, Settings


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
