"""Ollama integration"""

from typing import List, Dict

try:
    from ollama import chat
    from ollama import ChatResponse

    IS_OLLAMA_AVAILABLE = True
except ImportError:
    IS_OLLAMA_AVAILABLE = False


if IS_OLLAMA_AVAILABLE:

    class OllamaLLM:
        def __init__(self, model: str = "llama3.2"):
            self.model = model

        def __call__(
            self,
            messages: List[Dict[str, str]],
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
        return response["message"]["content"]

    def ollama(
        messages: List[Dict[str, str]],
        model: str = "llama3.2",
        *args,
        **kwargs,
    ) -> str:
        """Fluent interface for Ollama to be used in templates."""

        return OllamaLLM(model)(
            messages,
            *args,
            **kwargs,
        )
