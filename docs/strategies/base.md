# Base Strategy

The `BaseStrategy` class serves as the foundation for all mockstack strategies. It defines the core interface that all strategies must implement.

## Interface

### Constructor

```python
def __init__(self, settings: Settings, *args, **kwargs)
```

Initializes the strategy with the provided settings.

### Methods

#### `apply`

```python
async def apply(self, request: Request) -> Response
```

This is the main method that all strategies must implement. It takes a FastAPI `Request` object and returns a FastAPI `Response` object. This is where the strategy's core logic for handling requests is implemented.

#### `update_opentelemetry`

```python
def update_opentelemetry(self, request: Request, *args, **kwargs) -> None
```

This method allows strategies to add strategy-specific attributes to the OpenTelemetry span. The span is available on `request.state.span`. When OpenTelemetry is not enabled, this span will exist but will not be reported.

## Creating Custom Strategies

To create a custom strategy, you should:

1. Inherit from `BaseStrategy`
2. Implement the `apply` method
3. Optionally override `update_opentelemetry` to add strategy-specific telemetry

Example:

```python
from mockstack.strategies.base import BaseStrategy
from fastapi import Request, Response

class CustomStrategy(BaseStrategy):
    async def apply(self, request: Request) -> Response:
        # Implement your custom logic here
        pass

    def update_opentelemetry(self, request: Request, *args, **kwargs) -> None:
        # Add custom telemetry attributes
        request.state.span.set_attribute("custom.attribute", "value")
```
