"""Tests for mockstack.config: settings construction isolation."""

from mockstack.config import Settings


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
