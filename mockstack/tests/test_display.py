"""Tests for the display module."""

from unittest.mock import patch

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
