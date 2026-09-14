"""Ollama integration"""

from typing import Any


try:
    from ollama import ChatResponse, chat

    IS_OLLAMA_AVAILABLE = True
except ImportError:
    IS_OLLAMA_AVAILABLE = False


if IS_OLLAMA_AVAILABLE:

    class OllamaLLM:
        def __init__(self, model: str = "llama3.2"):
            self.model = model

        def __call__(
            self,
            messages: list[dict[str, str]],
            max_tokens: int = 4096,
            temperature: float = 0.7,
        ) -> str:
            response: ChatResponse = chat(
                model=self.model,
                messages=messages,
                options={"num_ctx": max_tokens, "temperature": temperature},
            )

            return content(response)

    def content(response: ChatResponse) -> str:
        """Extract the message content from the LLM response."""
        message_content: str = response["message"]["content"]
        return message_content

    def ollama(
        messages: list[dict[str, str]],
        model: str = "llama3.2",
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """Fluent interface for Ollama to be used in templates."""

        return OllamaLLM(model)(
            messages,
            *args,
            **kwargs,
        )
