![mockstack logo](https://github.com/adamhadani/mockstack/raw/main/docs/assets/mockstack.png)

--------------------------------------------------------------------------------


[![CI](https://github.com/adamhadani/mockstack/actions/workflows/ci.yml/badge.svg)](https://github.com/adamhadani/mockstack/actions/workflows/ci.yml)
[![GitHub License](https://img.shields.io/github/license/adamhadani/mockstack)](https://github.com/adamhadani/mockstack/blob/main/LICENSE)
[![PyPI - Version](https://img.shields.io/pypi/v/mockstack)](https://pypi.org/project/mockstack/)

An API mocking workhorse :racehorse:

Enabling a sane development lifecycle for microservice-oriented architectures.

Highlights include:

* Multiple strategies for handling requests such as Jinja2 template files with intelligent URL request-to-template routing, proxy strategy, and mixed strategies. :game_die:
* Observability via OpenTelemetry integration. Get detailed traces of your sessions instantly reported to backends such as Grafana, Jaeger, Zipkin, etc. :eyes:
* Configurability via `pydantic-settings` supports customizing behaviour via environment variables and a `.env` file. :flags:
* Comprehensive unit-tests, linting and formatting coverage as well as vulnerabilities and security scanning with full CI automation to ensure stability and a high-quality codebase for production-grade use. :+1:


## Installation

Install using [uv](https://docs.astral.sh/uv/). This package conforms the concept of a [tool](https://docs.astral.sh/uv/concepts/tools/) and hence can simply install / run with `uvx`:

    uvx mockstack

or install into a persistent environment and add it to the PATH with:

    uv tool install mockstack


## Usage

Available configuration options are [here](https://github.com/adamhadani/mockstack/blob/main/mockstack/config.py). Setting individual options can be done with env. variables as in the following example:

```shell
    export MOCKSTACK__TEMPLATES_DIR=~/mockstack-templates/
    export MOCKSTACK__OPENTELEMETRY__ENABLED=true
    export MOCKSTACK__OPENTELEMETRY__CAPTURE_RESPONSE_BODY=true
    uv run
```

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

Linting, formatting, static type checks etc. are all managed via [pre-commit](https://pre-commit.com/) hooks. These will run automatically on every commit. You can invoke these manually on all files with:

    pre-commit run --all-files


## Contributing

If you are contributing to development, you will want to clone this project, and can then install it locally with:

    gh repo clone adamhadani/mockstack
    cd mockstack/
    uv sync
    uv pip install -e .

Copy the included [.env.example](https://github.com/adamhadani/mockstack/blob/main/.env.example) file to `.env` and fill in configuration as needed based on the given examples.

Run in development mode (for live-reload of changes when developing):

    uv run uvicorn --factory mockstack.main:create_app --reload
