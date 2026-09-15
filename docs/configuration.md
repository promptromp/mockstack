# Configuration

mockstack can be configured through multiple methods, in order of priority:

- Command-line arguments
- Environment variables
- `.env` file


All configuration options are prefixed with `MOCKSTACK__` when using environment variables or the `.env` file.
Upper-case the option name and add the prefix: `proxyrules_rules_filename` becomes
`MOCKSTACK__PROXYRULES_RULES_FILENAME`. Nested options use `__` as the separator:
`opentelemetry.enabled` becomes `MOCKSTACK__OPENTELEMETRY__ENABLED`. On the command
line, use the kebab-case form, e.g. `--proxyrules-rules-filename`, with a dot for nested
options (`--opentelemetry.enabled`); boolean options are flags with a `--no-` form.
`mockstack --help` describes every flag, and `mockstack --version` prints the installed
version.

## General Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `debug` | boolean | `false` | Whether to run in debug mode |
| `host` | string | `0.0.0.0` | Host to run the server on |
| `port` | integer | `8000` | Port to run the server on, from 0 to 65535 |
| `openapi_docs_enabled` | boolean | `false` | Whether to serve FastAPI's documentation routes: `/docs`, `/redoc`, `/openapi.json` and `/docs/oauth2-redirect`. They take precedence over the catch-all route and document only that route, so by default they are off and those paths reach the strategy like any other |
| `strategy` | string | `filefixtures` | Strategy to use for handling requests. Options: `filefixtures`, `proxyrules` |

## OpenTelemetry Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `opentelemetry.enabled` | boolean | `false` | Whether to enable OpenTelemetry integration |
| `opentelemetry.endpoint` | string | `http://localhost:4317/` | OpenTelemetry endpoint |
| `opentelemetry.capture_response_body` | boolean | `false` | Whether to capture response body in traces |

## Strategy-Specific Settings

### FileFixtures Strategy

| Option | Environment variable | Type | Default | Description |
|--------|----------------------|------|---------|-------------|
| `templates_dir` | `MOCKSTACK__TEMPLATES_DIR` | path | - | Base directory for templates used by the strategy. Required when `strategy` is `filefixtures` (the default), and the directory must exist |
| `filefixtures_enable_templates_for_post` | `MOCKSTACK__FILEFIXTURES_ENABLE_TEMPLATES_FOR_POST` | boolean | `true` | Whether to try a template-based response for POST requests before simulating resource creation |
| `filefixtures_simulate_create_on_missing` | `MOCKSTACK__FILEFIXTURES_SIMULATE_CREATE_ON_MISSING` | boolean | `true` | Whether a create-looking POST with no matching template (or with templates-for-POST off) gets a simulated 201 instead of the same 404 (`missing`) a GET with no template gets |

### ProxyRules Strategy

See [ProxyRules](strategies/proxyrules.md) for how rules are written and evaluated.

| Option | Environment variable | Type | Default | Description |
|--------|----------------------|------|---------|-------------|
| `proxyrules_rules_filename` | `MOCKSTACK__PROXYRULES_RULES_FILENAME` | path | - | The YAML rules file. Required when `strategy` is `proxyrules`, and the file must exist. It is loaded and validated at startup, so an invalid rule stops mockstack from starting |
| `proxyrules_redirect_via` | `MOCKSTACK__PROXYRULES_REDIRECT_VIA` | string | `reverse_proxy` | What a rule whose `replacement` is a URL does. `reverse_proxy` forwards the request and returns the upstream's response (`X-Mockstack-Result: proxy`); `http_307_temporary` and `http_301_permanent` answer with that redirect (`X-Mockstack-Result: redirect`). Rules that serve `file:///` templates are unaffected. Environment variables take these values; `mockstack --help` lists the enum names (`REVERSE_PROXY`, ...), and the command line accepts either form |
| `proxyrules_reverse_proxy_timeout` | `MOCKSTACK__PROXYRULES_REVERSE_PROXY_TIMEOUT` | float | `10.0` | Timeout in seconds for reverse-proxied upstream requests. An upstream that does not answer in time is answered with a 504 stamped `X-Mockstack-Result: error`. `None` (when constructing `Settings` in Python) disables the timeout |
| `proxyrules_simulate_create_on_missing` | `MOCKSTACK__PROXYRULES_SIMULATE_CREATE_ON_MISSING` | boolean | `false` | Whether a request that matches no rule and looks like a resource creation (e.g. a POST) gets a simulated 201 (`X-Mockstack-Result: create`) instead of a 404 (`missing`) |
| `proxyrules_verify_ssl_certificates` | `MOCKSTACK__PROXYRULES_VERIFY_SSL_CERTIFICATES` | boolean | `true` | Whether to verify the TLS certificates of HTTPS upstreams when reverse proxying. Disable with caution, e.g. for a trusted upstream with a self-signed certificate |
| `proxyrules_record_mode` | `MOCKSTACK__PROXYRULES_RECORD_MODE` | string | `off` | Applies to the `proxyrules` strategy. Record mode. `missing` writes the upstream response into a fixture rule's file when that file does not exist yet; `overwrite` also re-records files that were recorded before, never hand-written ones. Requires `proxyrules_record_root` and `reverse_proxy`. Never enable on a shared or exposed instance; see [Recording fixtures](strategies/proxyrules.md#recording-fixtures). Environment variables take the lower-case values; `mockstack --help` lists the enum names (`OFF`, `MISSING`, `OVERWRITE`), and the command line accepts either form |
| `proxyrules_record_root` | `MOCKSTACK__PROXYRULES_RECORD_ROOT` | path | - | Applies to the `proxyrules` strategy. Existing directory that every recorded fixture file must resolve inside, symlinks followed. Required when `proxyrules_record_mode` is not `off` |
| `proxyrules_record_scrubber` | `MOCKSTACK__PROXYRULES_RECORD_SCRUBBER` | string | - | Optional `module:function` called with every body before it is recorded; it returns the text to write, or `None` to skip that response. Imported and checked when settings load, so the module must be importable (e.g. `PYTHONPATH=.`); see [Scrubbing recorded bodies](strategies/proxyrules.md#scrubbing-recorded-bodies) |

## Resource Creation Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `created_resource_metadata` | object | See below | Metadata fields to inject into created resources |
| `missing_resource_fields` | object | See below | Fields to inject into missing resources response JSON |

These options, and `logging` below, have no command-line flags. Set them as JSON in an
environment variable or the `.env` file, e.g.
`MOCKSTACK__MISSING_RESOURCE_FIELDS='{"code": 404, "message": "not found"}'`.

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

Here's an example `.env` file. A `.env` file does not expand `~`, so give paths in full:

```env
MOCKSTACK__STRATEGY=filefixtures
MOCKSTACK__TEMPLATES_DIR=/path/to/mockstack-templates/
MOCKSTACK__OPENTELEMETRY__ENABLED=true
MOCKSTACK__OPENTELEMETRY__CAPTURE_RESPONSE_BODY=true
```

And one for the `proxyrules` strategy:

```env
MOCKSTACK__STRATEGY=proxyrules
MOCKSTACK__PROXYRULES_RULES_FILENAME=./rules.yml
MOCKSTACK__PROXYRULES_REDIRECT_VIA=reverse_proxy
MOCKSTACK__PROXYRULES_REVERSE_PROXY_TIMEOUT=5
```

And one that records fixtures from the real services behind the rules (see
[Recording fixtures](strategies/proxyrules.md#recording-fixtures)):

```env
MOCKSTACK__STRATEGY=proxyrules
MOCKSTACK__PROXYRULES_RULES_FILENAME=./rules.yml
MOCKSTACK__PROXYRULES_RECORD_MODE=missing
MOCKSTACK__PROXYRULES_RECORD_ROOT=/path/to/fixtures
```

## Command Line Usage

You can also set configuration options via command line arguments:

```bash
uvx mockstack --strategy filefixtures --templates-dir ~/mockstack-templates/
uvx mockstack --strategy proxyrules --proxyrules-rules-filename ./rules.yml --proxyrules-redirect-via http_307_temporary
uvx mockstack --strategy proxyrules --proxyrules-rules-filename ./rules.yml --proxyrules-record-mode missing --proxyrules-record-root ./fixtures
```

### Configuration errors

Settings are checked before the server starts. When a setting is missing or invalid, a
flag, a key in the `.env` file or a variable inside a settings group (such as
`MOCKSTACK__OPENTELEMETRY__ENABLED`) is not recognized, or the rules file does not load,
mockstack exits with status 2 and a short message instead of a traceback. It names each
setting by its flag and lists the environment variables for the same settings, since the
value may have come from the command line, the environment or a `.env` file. Flags must
be spelled in full, and a misspelt flag or `.env` key gets a suggestion. An exported
`MOCKSTACK__*` variable that names no setting is ignored, like any other environment
variable:

```console
$ mockstack
mockstack: error: --templates-dir is required when --strategy is filefixtures (the default)
  environment or .env: MOCKSTACK__TEMPLATES_DIR, MOCKSTACK__STRATEGY
Run 'mockstack --help' to see all options.

$ mockstack --port abc --strategy nope
mockstack: error: 2 invalid settings
  invalid value 'abc' for --port: input should be a valid integer, unable to parse string as an integer
  invalid value 'nope' for --strategy: input should be 'filefixtures' or 'proxyrules'
  environment or .env: MOCKSTACK__PORT, MOCKSTACK__STRATEGY
Run 'mockstack --help' to see all options.

$ mockstack --template-dir ./templates
mockstack: error: unrecognized arguments: --template-dir ./templates
  --template-dir: did you mean --templates-dir?
Run 'mockstack --help' to see all options.
```

A rules file that does not load is named with the offending rule; see
[Load-time validation](strategies/proxyrules.md#load-time-validation). A problem found
only while the server starts, such as a port that is already in use, is reported by
uvicorn instead.

Help and error output are coloured on a terminal. Set `NO_COLOR=1` to turn colour off,
or `FORCE_COLOR=1` to keep it when the output is piped.
