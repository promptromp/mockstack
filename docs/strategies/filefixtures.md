# FileFixtures Strategy

The `FileFixturesStrategy` is a template-based strategy that uses Jinja2 templates to generate responses. It's particularly useful for creating consistent mock responses for your API endpoints.

## Overview

This strategy:

- Uses Jinja2 templates stored in a specified directory
- Intelligently matches requests to templates based on the request path
- Supports the GET, POST, PUT, PATCH and DELETE HTTP methods; HEAD and OPTIONS requests are answered 405 Method Not Allowed
- Simulates resource creation for POST requests that match no template (behavior controlled via configuration)
- Provides OpenTelemetry integration for observability

## Template Resolution

For a given request path like `/api/v1/projects/1234`, the strategy will look for templates in the following order:

1. `api-v1-projects.1234.j2` (specific to the resource ID)
2. `api-v1-projects.j2` (generic for the resource type)
3. `index.j2` (fallback template)

A path segment counts as an identifier when it looks like one: a UUID (with or without
dashes), or an even-length string of digits or hexadecimal characters. With several
identifiers the most specific name comes first: `/api/v1/projects/1234/tasks/abcd` tries
`api-v1-projects-tasks.1234.abcd.j2`, then `api-v1-projects-tasks.1234.j2`,
`api-v1-projects-tasks.j2` and `index.j2`.

A rendered template is served with the request's `Content-Type`, or `application/json`
when the request has none.

## HTTP Method Handling

### GET Requests
- Attempts to find and render a matching template
- Returns 404 if no matching template is found

### POST Requests
The strategy intelligently handles POST requests based on the request context:

1. **Templates**: With `filefixtures_enable_templates_for_post` enabled (the default), a matching
   template is looked up first, as for a GET, and rendered with a 200
2. **Search Requests**: If the path looks like a search (it ends in `_search`, `/search`, `_query`
   or `/query`), returns a template response
3. **Command Requests**: If the path looks like a command (it ends in `_command`, `/command`,
   `_cmd`, `/cmd`, `_run`, `/run`, `_execute` or `/execute`), returns a 201 CREATED status with
   template response
4. **Resource Creation**: Otherwise, simulates resource creation with injected metadata, when
   `filefixtures_simulate_create_on_missing` is enabled (the default). When it is disabled, a
   create-looking POST with no matching template gets the same 404 missing-resource response as
   a GET with no template, instead of a simulated create.

With templates for POST enabled, step 1 has already looked for the template, so a search or
command POST is answered 200 by its template, or 404 when there is none. Since `index.j2`
matches every path, a templates directory containing an `index.j2` answers every POST from it,
create-looking ones included; set `filefixtures_enable_templates_for_post=False` to restore the
search (200), command (201) and create handling.

### DELETE/PUT/PATCH Requests
- Returns 204 NO CONTENT by default
- These are no-op operations in the default implementation

## Template Context

Templates have access to the following context variables:

- `query`: The query parameters, as a dict
- `headers`: The request headers, as a dict (names lower-cased)
- `request_json`: The parsed JSON body of a POST request with a JSON content type (`application/json` or `text/json`) or a path ending in `.json`; otherwise `None`
- Identifiers inferred from the path: each ID-like segment is available under the name of the segment before it (`projects` for `/api/v1/projects/<uuid>`), or as `id` when nothing comes before it

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

The response is a 201 CREATED echoing the request's JSON body with these fields rendered into
it; the field templates can use `uuid4()`, `utcnow()` and `request`. A POST that is not JSON (see
`request_json` above) gets a 201 with an empty body. The fields are set with
[`created_resource_metadata`](../configuration.md#resource-creation-settings).

## Configuration

The strategy requires the following configuration:

```python
settings = Settings(
    strategy="filefixtures",
    templates_dir="/path/to/templates",
    filefixtures_enable_templates_for_post=True,  # Optional: Enables template-based responses for POST requests
    filefixtures_simulate_create_on_missing=False,  # Optional: Disables the create-simulation fallback for POSTs without a template
)
```

## Example Template

Here's an example template for a user resource, `api-v1-users.j2`, which serves
`GET /api/v1/users/<uuid>`:

```jinja2
{
    "id": {{ users | tojson }},
    "name": "Test user",
    "fields": {{ query.get("fields", "all") | tojson }}
}
```

## OpenTelemetry Integration

The strategy automatically adds the following OpenTelemetry attributes:

- `mockstack.filefixtures.template_name`: The name of the template being rendered

## Error Handling

When no matching template is found, the strategy returns a 404 response with the following structure. The exception is a POST that looks like resource creation: with `filefixtures_simulate_create_on_missing` enabled (the default), a missing template there falls back to simulating creation (see [Resource Creation](#resource-creation)) instead of 404ing. Set `filefixtures_simulate_create_on_missing=False` to turn that fallback off and get the same 404 as any other unmatched request.

```json
{
    "code": 404,
    "message": "mockstack: resource not found",
    "retryable": false
}
```
