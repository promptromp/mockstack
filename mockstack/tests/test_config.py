"""Tests for mockstack.config: settings construction isolation."""

import pytest

from mockstack.config import CliSettings, Settings
from mockstack.constants import ProxyRulesRecordMode, ProxyRulesRedirectVia


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


def test_record_mode_defaults_to_off(make_settings, templates_dir):
    settings = make_settings(templates_dir=templates_dir)
    assert settings.proxyrules_record_mode == ProxyRulesRecordMode.OFF
    assert settings.proxyrules_record_root is None


def test_record_mode_requires_a_record_root(make_settings, templates_dir):
    with pytest.raises(ValueError, match="proxyrules_record_root is required when proxyrules_record_mode is not off"):
        make_settings(templates_dir=templates_dir, proxyrules_record_mode="missing")


def test_record_mode_requires_reverse_proxy(make_settings, templates_dir, tmp_path):
    with pytest.raises(ValueError, match="proxyrules_record_mode requires proxyrules_redirect_via to be reverse_proxy"):
        make_settings(
            templates_dir=templates_dir,
            proxyrules_record_mode="overwrite",
            proxyrules_record_root=tmp_path,
            proxyrules_redirect_via=ProxyRulesRedirectVia.HTTP_TEMPORARY_REDIRECT,
        )


def test_record_root_must_be_an_existing_directory(make_settings, templates_dir, tmp_path):
    with pytest.raises(ValueError, match="proxyrules_record_root"):
        make_settings(
            templates_dir=templates_dir,
            proxyrules_record_mode="missing",
            proxyrules_record_root=tmp_path / "absent",
        )


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


def test_record_scrubber_defaults_to_none_and_reads_its_env_var(monkeypatch, templates_dir):
    assert Settings(templates_dir=templates_dir).proxyrules_record_scrubber is None
    monkeypatch.setenv("MOCKSTACK__PROXYRULES_RECORD_SCRUBBER", "scrubbers:mask_emails")
    assert Settings(templates_dir=templates_dir).proxyrules_record_scrubber == "scrubbers:mask_emails"
