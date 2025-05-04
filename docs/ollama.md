# Ollama Integration

Mockstack provides integration with [Ollama](https://ollama.com/), allowing you to use real LLM responses in your mock templates. This is particularly useful for development, debugging, and integration testing scenarios where you want to capture the non-deterministic nature of LLM responses.

## Prerequisites

To use the Ollama integration, you'll need:

1. Mockstack installed with the optional `llm` dependencies:
   ```bash
   uv pip install mockstack[llm]
   ```

2. [Ollama](https://ollama.com/) installed locally with at least one model (e.g., "llama3.2")

## Basic Usage

The Ollama integration works by routing requests to a template file that uses the special `ollama` template function.

1. Configure your LLM client to hit an endpoint that maps to a template filepath calling the `ollama` method, e.g.:
   ```python
   from langchain_openai import ChatOpenAI

   llm = ChatOpenAI(
       model="gpt-4o",
       base_url="http://localhost:8000/ollama/openai/v1",
       api_key="SOME_STRING_THAT_DOES_NOT_MATTER",
   )
   ```

2. Make requests as you normally would:
   ```python
   messages = [
       (
           "system",
           "You are a helpful assistant that translates English to French. Translate the user sentence.",
       ),
       ("human", "mockstack is pretty cool. But LLMs are way cooler"),
   ]
   ai_msg = llm.invoke(messages)
   print(ai_msg.content)
   ```

## Integration with Templates

You can use Ollama responses within your Jinja templates via the provided `ollama` template function. This allows you to:

1. Mix static and dynamic content
2. Apply transformations to the LLM responses
3. Create conditional logic based on the responses

Example template structure:

```jinja
{
  "id": "chatcmpl-123",
  "object": "chat.completion",
  "created": 1677652288,
  "model": "gpt-4.1",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "{{ ollama(request_json.messages, 'llama3.2') | json_escape }}"
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 9,
    "completion_tokens": 12,
    "total_tokens": 21
  }
}
```

## Best Practices

1. **Caching**: Consider implementing caching for frequently used responses to improve performance
2. **Model Selection**: Choose the appropriate model based on your testing needs
3. **Error Handling**: Implement proper error handling in your templates
4. **Performance**: Be mindful of response times when using real LLM responses

## Limitations

- The integration requires a local Ollama instance
- Response times will be slower than static templates
- Model availability depends on your local setup
