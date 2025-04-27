# mockstack

An API mocking workhorse :racehorse:

Ideal for a sane development lifecycle of microservice-oriented architectures.

Highlights include:

* Multiple strategies for handling requests such as Jinja2 template files with intelligent URL request-to-template routing, proxy strategy, and mixed strategies.
* Observability via OpenTelemetry integration. Get detailed traces of your sessions instantly reported to backends such as Grafana, Jaeger, Zipkin, etc.
* Configurability via `pydantic-settings` supports customizing behaviour via environment variables and a `.env` file.
* Comprehensive unit-tests, linting and formatting coverage and automation to ensure stability and a high-quality codebase for production-grade use.


## Installation

Install using [uv](https://docs.astral.sh/uv/). This will create a virtualenv for you and install all dependencies:

    uv sync
    uv pip install -e .


## Usage

Copy the included [.env.example](.env.example) file to `.env` and fill in configuration as needed based on the given examples.

Run in development mode (for live-reload of changes when developing):

    uv run fastapi dev mockstack/main.py

Or, run in production mode:

    uv run fastapi run mockstack/main.py

Out of the box, you get the following behavior when using the default `filefixtures` strategy:

- The HTTP request `GET /someservice/api/v1/user/c27f5b2b-6e81-420d-a4e4-6426e1c32db8` will try to find `<templates_dir>/someservice-api-v1-user.c27f5b2b-6e81-420d-a4e4-6426e1c32db8.j2`,
  and will fallback to `<templates_dir>/someservice-api-v1-user.j2` (and finally to `index.j2` if exists). These are j2 files that have access to request body context variables.
- The HTTP request `POST /someservice/api/v2/item` with a JSON body will attempt to intelligently simulate the creation of a resource, returning the appropriate status code and will echo back the provided request resource, after injecting additional metadata fields based on strategy configuration. This is useful for services that expect fields such as `id` and `created_at` on returned created resources.
- HTTP requests for `DELETE` / `PUT` / `PATCH` are a no-op by default, simply returning the appropriate status code.
- The HTTP request `POST /someservice/api/v2/embedding_search` will be handled as a search request rather than a resource creation, returning an appropriate http status code and mock results based on user-configurable formatting.

Overall, the design philosophy is that things "just work". The framework attempts to intelligently deduce the intent of the request as much as possible and act accordingly,
while leaving room for advanced users to go in and customize behavior using the configuration options.


## Testing

Invoke unit-tests with:

    uv run python -m pytest
