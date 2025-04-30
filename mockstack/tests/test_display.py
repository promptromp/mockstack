"""Tests for the display module."""

from unittest.mock import patch

from mockstack.display import ANSIColors, announce


def test_ansicolors_constants():
    """Test that ANSIColors constants are defined correctly."""
    assert ANSIColors.HEADER == "\033[95m"
    assert ANSIColors.OKBLUE == "\033[94m"
    assert ANSIColors.OKCYAN == "\033[96m"
    assert ANSIColors.OKGREEN == "\033[92m"
    assert ANSIColors.WARNING == "\033[93m"
    assert ANSIColors.FAIL == "\033[91m"
    assert ANSIColors.ENDC == "\033[0m"
    assert ANSIColors.BOLD == "\033[1m"
    assert ANSIColors.UNDERLINE == "\033[4m"


def test_announce(app, settings):
    """Test the announce function logs the correct message."""
    with patch("mockstack.display.logging") as mock_logging:
        mock_logger = mock_logging.getLogger.return_value

        announce(app, settings)

        mock_logging.getLogger.assert_called_once_with("uvicorn")
        mock_logger.info.assert_called()

        # Check that the log message contains the expected information
        first_log_message = mock_logger.info.call_args[0][0]
        assert "OpenTelemetry enabled:" in first_log_message
