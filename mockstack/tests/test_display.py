"""Tests for the display module."""

from unittest.mock import patch

from mockstack.constants import ProxyRulesRecordMode
from mockstack.display import announce


def test_announce(app, settings):
    """Test the announce function logs the correct message."""
    with patch("mockstack.display.logging") as mock_logging:
        mock_logger = mock_logging.getLogger.return_value

        announce(app, settings)

        mock_logging.getLogger.assert_called_once_with("uvicorn")
        mock_logger.info.assert_called()

        # Check that the log message contains the expected information
        first_log_message = mock_logger.info.call_args[0][0]
        assert "OpenTelemetry" in first_log_message


def test_announce_warns_when_proxyrules_record_mode_is_on(app, settings, tmp_path):
    """M-a: the record-mode WARNING is logged from ``announce``, which runs after
    logging is configured (see ``lifespan_provider``), not from the strategy's
    ``__init__``, which runs earlier in ``create_app``."""
    recording_settings = settings.model_copy(
        update={"proxyrules_record_mode": ProxyRulesRecordMode.OVERWRITE, "proxyrules_record_root": tmp_path}
    )
    with patch("mockstack.display.logging") as mock_logging:
        mock_logger = mock_logging.getLogger.return_value

        announce(app, recording_settings)

        warning_messages = [call.args[0] % call.args[1:] for call in mock_logger.warning.call_args_list]
        assert any(
            "record mode 'overwrite' is on" in message and str(tmp_path) in message for message in warning_messages
        )


def test_announce_does_not_warn_when_proxyrules_record_mode_is_off(app, settings):
    """The record-mode WARNING is only logged when recording is actually on."""
    assert settings.proxyrules_record_mode == ProxyRulesRecordMode.OFF

    with patch("mockstack.display.logging") as mock_logging:
        mock_logger = mock_logging.getLogger.return_value

        announce(app, settings)

        mock_logger.warning.assert_not_called()
