# FileFixtures Strategy

The `FileFixturesStrategy` is a template-based strategy that uses Jinja2 templates to generate responses. It's particularly useful for creating consistent mock responses for your API endpoints.

## Overview

This strategy:

- Uses Jinja2 templates stored in a specified directory
- Intelligently matches requests to templates based on the request path
- Supports all HTTP methods (GET, POST, PUT, PATCH, DELETE)
- Simulates resource creation for POST requests which are not handled by proxying rules (behavior controlled via configuration)
- Provides OpenTelemetry integration for observability

## Template Resolution

For a given request path like `/api/v1/projects/1234`, the strategy will look for templates in the following order:

1. `api-v1-projects.1234.j2` (specific to the resource ID)
2. `api-v1-projects.j2` (generic for the resource type)
3. `index.j2` (fallback template)

## HTTP Method Handling

### GET Requests
- Attempts to find and render a matching template
- Returns 404 if no matching template is found

### POST Requests
The strategy intelligently handles POST requests based on the request context:

1. **Search Requests**: If the request looks like a search (based on URL and body), returns a template response
2. **Command Requests**: If the request looks like a command, returns a 201 CREATED status with template response
3. **Resource Creation**: Otherwise, simulates resource creation with injected metadata

### DELETE/PUT/PATCH Requests
- Returns 204 NO CONTENT by default
- These are no-op operations in the default implementation

## Template Context

Templates have access to the following context variables:

- `request`: The FastAPI Request object
- `request.body`: The parsed request body
- `request.headers`: The request headers
- `request.query_params`: The query parameters
- `request.path_params`: The path parameters

## Resource Creation

When simulating resource creation (POST requests), the strategy injects the following metadata fields by default:

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

## Configuration

The strategy requires the following configuration:

```python
settings = Settings(
    strategy="filefixtures",
    templates_dir="/path/to/templates",
    filefixtures_enable_templates_for_post=True  # Optional: Enables template-based responses for POST requests
)
```

## Example Template

Here's an example template for a user resource:

```jinja2
{
    "id": "{{ uuid4() }}",
    "name": "{{ request.body.name }}",
    "email": "{{ request.body.email }}",
    "createdAt": "{{ utcnow().isoformat() }}",
    "updatedAt": "{{ utcnow().isoformat() }}"
}
```

## OpenTelemetry Integration

The strategy automatically adds the following OpenTelemetry attributes:

- `mockstack.filefixtures.template_name`: The name of the template being rendered

## Error Handling

When no matching template is found, the strategy returns a 404 response with the following structure:

```json
{
    "code": 404,
    "message": "mockstack: resource not found",
    "retryable": false
}
```
