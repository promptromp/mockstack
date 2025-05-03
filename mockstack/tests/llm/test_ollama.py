"""Tests for the Ollama module."""

import pytest
from unittest.mock import patch, MagicMock
from typing import List, Dict


@pytest.fixture
def mock_messages() -> List[Dict[str, str]]:
    """Sample messages for testing."""
    return [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]


@pytest.fixture
def mock_chat_response() -> Dict:
    """Mock chat response from Ollama."""
    return {"message": {"content": "This is a test response"}}


@pytest.fixture
def mock_ollama_module():
    """Mock the ollama module."""
    # TODO: Should probably remove this in favor making sure ollama optional package
    # is installed for running unit-tests, and instead mocking it as missing for the
    # "not available" test cases.
    with patch.dict("sys.modules", {"ollama": MagicMock()}) as mocked_dict:
        yield mocked_dict


class TestOllamaAvailable:
    """Test cases when Ollama is available."""

    @patch("mockstack.llm.ollama.IS_OLLAMA_AVAILABLE", True)
    def test_ollama_llm_initialization(self, mock_ollama_module):
        """Test OllamaLLM initialization with default model."""
        from mockstack.llm.ollama import OllamaLLM

        llm = OllamaLLM()
        assert llm.model == "llama3.2"

    @patch("mockstack.llm.ollama.IS_OLLAMA_AVAILABLE", True)
    def test_ollama_llm_initialization_custom_model(self, mock_ollama_module):
        """Test OllamaLLM initialization with custom model."""
        from mockstack.llm.ollama import OllamaLLM

        llm = OllamaLLM(model="custom-model")
        assert llm.model == "custom-model"

    @patch("mockstack.llm.ollama.IS_OLLAMA_AVAILABLE", True)
    def test_ollama_llm_call(
        self, mock_ollama_module, mock_messages, mock_chat_response
    ):
        """Test OllamaLLM.__call__ method."""
        from mockstack.llm.ollama import OllamaLLM

        mock_chat = MagicMock(return_value=mock_chat_response)
        with patch("mockstack.llm.ollama.chat", mock_chat):
            llm = OllamaLLM()
            response = llm(mock_messages)

            mock_chat.assert_called_once_with(
                model="llama3.2",
                messages=mock_messages,
                options={"num_ctx": 4096, "temperature": 0.7},
            )
            assert response == "This is a test response"

    @patch("mockstack.llm.ollama.IS_OLLAMA_AVAILABLE", True)
    def test_content_function(self, mock_ollama_module, mock_chat_response):
        """Test content function extraction."""
        from mockstack.llm.ollama import content

        result = content(mock_chat_response)
        assert result == "This is a test response"

    @patch("mockstack.llm.ollama.IS_OLLAMA_AVAILABLE", True)
    def test_ollama_function(
        self, mock_ollama_module, mock_messages, mock_chat_response
    ):
        """Test ollama function."""
        from mockstack.llm.ollama import ollama

        mock_chat = MagicMock(return_value=mock_chat_response)
        with patch("mockstack.llm.ollama.chat", mock_chat):
            response = ollama(mock_messages)

            mock_chat.assert_called_once_with(
                model="llama3.2",
                messages=mock_messages,
                options={"num_ctx": 4096, "temperature": 0.7},
            )
            assert response == "This is a test response"
