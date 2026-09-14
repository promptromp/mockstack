"""Tests for the Ollama module."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_messages() -> list[dict[str, str]]:
    """Sample messages for testing."""
    return [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]


@pytest.fixture
def mock_chat_response() -> dict:
    """Mock chat response from Ollama."""
    return {"message": {"content": "This is a test response"}}


@pytest.fixture
def mock_ollama_module():
    """Mock the ollama module, and mark it available."""
    # TODO: Should probably remove this in favor making sure ollama optional package
    # is installed for running unit-tests, and instead mocking it as missing for the
    # "not available" test cases.
    with (
        patch.dict("sys.modules", {"ollama": MagicMock()}) as mocked_dict,
        patch("mockstack.llm.ollama.IS_OLLAMA_AVAILABLE", True),
    ):
        yield mocked_dict


@pytest.fixture
def mock_chat(mock_ollama_module, mock_chat_response):
    """Patch ollama's ``chat`` to answer with ``mock_chat_response``."""
    with patch("mockstack.llm.ollama.chat", MagicMock(return_value=mock_chat_response)) as chat:
        yield chat


class TestOllamaAvailable:
    """Test cases when Ollama is available."""

    def test_ollama_llm_initialization(self, mock_ollama_module):
        """Test OllamaLLM initialization with default model."""
        from mockstack.llm.ollama import OllamaLLM

        llm = OllamaLLM()
        assert llm.model == "llama3.2"

    def test_ollama_llm_initialization_custom_model(self, mock_ollama_module):
        """Test OllamaLLM initialization with custom model."""
        from mockstack.llm.ollama import OllamaLLM

        llm = OllamaLLM(model="custom-model")
        assert llm.model == "custom-model"

    def test_ollama_llm_call(self, mock_chat, mock_messages):
        """Test OllamaLLM.__call__ method."""
        from mockstack.llm.ollama import OllamaLLM

        response = OllamaLLM()(mock_messages)

        mock_chat.assert_called_once_with(
            model="llama3.2",
            messages=mock_messages,
            options={"num_ctx": 4096, "temperature": 0.7},
        )
        assert response == "This is a test response"

    def test_content_function(self, mock_ollama_module, mock_chat_response):
        """Test content function extraction."""
        from mockstack.llm.ollama import content

        result = content(mock_chat_response)
        assert result == "This is a test response"

    def test_ollama_function(self, mock_chat, mock_messages):
        """Test ollama function."""
        from mockstack.llm.ollama import ollama

        response = ollama(mock_messages)

        mock_chat.assert_called_once_with(
            model="llama3.2",
            messages=mock_messages,
            options={"num_ctx": 4096, "temperature": 0.7},
        )
        assert response == "This is a test response"
