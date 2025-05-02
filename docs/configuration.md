# Configuration

mockstack can be configured through multiple methods, in order of priority:

- Command-line arguments
- Environment variables
- `.env` file


All configuration options are prefixed with `MOCKSTACK__` when using environment variables or the `.env` file.

## General Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `debug` | boolean | `false` | Whether to run in debug mode |
| `host` | string | `0.0.0.0` | Host to run the server on |
| `port` | integer | `8000` | Port to run the server on |
| `strategy` | string | `filefixtures` | Strategy to use for handling requests. Options: `filefixtures`, `proxyrules` |

## OpenTelemetry Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `opentelemetry.enabled` | boolean | `false` | Whether to enable OpenTelemetry integration |
| `opentelemetry.endpoint` | string | `http://localhost:4317/` | OpenTelemetry endpoint |
| `opentelemetry.capture_response_body` | boolean | `false` | Whether to capture response body in traces |

## Strategy-Specific Settings

### FileFixtures Strategy

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `templates_dir` | string | - | Base directory for templates used by the strategy |
| `filefixtures_enable_templates_for_post` | boolean | `false` | Whether to enable template-based responses for POST requests |

### ProxyRules Strategy

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `proxyrules_rules_filename` | string | - | Rules filename for proxyrules strategy |
| `proxyrules_redirect_via` | string | `reverse_proxy` | Controls behavior of proxying. Options: `reverse_proxy`, `http_307_temporary`, `http_301_permanent` |
| `proxyrules_reverse_proxy_timeout` | float | `10.0` | Default timeout for reverse proxy requests in seconds |
| `proxyrules_simulate_create_on_missing` | boolean | `false` | Whether to simulate creation of resources when a POST request is made to a resource that doesn't match any rules |

## Resource Creation Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `created_resource_metadata` | object | See below | Metadata fields to inject into created resources |
| `missing_resource_fields` | object | See below | Fields to inject into missing resources response JSON |

### Default created_resource_metadata
```json
{
    "id": "{{ uuid4() }}",
    "createdAt": "{{ utcnow().isoformat() }}",
    "updatedAt": "{{ utcnow().isoformat() }}",
    "createdBy": "{{ request.headers.get('X-User-Id', uuid4()) }}",
    "status": {
        "code": "OK",
        "error_code": null
    }
}
```

### Default missing_resource_fields
```json
{
    "code": 404,
    "message": "mockstack: resource not found",
    "retryable": false
}
```

## Logging Configuration

The logging configuration follows the Python logging configuration schema. By default, it includes:

- Rich console handler
- Uvicorn formatter
- Separate loggers for different components
- Debug level logging for strategy-specific loggers

## Example Configuration

Here's an example `.env` file:

```env
MOCKSTACK__STRATEGY=filefixtures
MOCKSTACK__TEMPLATES_DIR=~/mockstack-templates/
MOCKSTACK__OPENTELEMETRY__ENABLED=true
MOCKSTACK__OPENTELEMETRY__CAPTURE_RESPONSE_BODY=true
```

## Command Line Usage

You can also set configuration options via command line arguments:

```bash
uvx mockstack --strategy filefixtures --templates-dir ~/mockstack-templates/
```
