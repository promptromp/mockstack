![mockstack logo](https://github.com/promptromp/mockstack/raw/main/docs/assets/mockstack.png)

--------------------------------------------------------------------------------


[![CI](https://github.com/promptromp/mockstack/actions/workflows/ci.yml/badge.svg)](https://github.com/promptromp/mockstack/actions/workflows/ci.yml)
[![GitHub License](https://img.shields.io/github/license/promptromp/mockstack)](https://github.com/promptromp/mockstack/blob/main/LICENSE)
[![PyPI - Version](https://img.shields.io/pypi/v/mockstack)](https://pypi.org/project/mockstack/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/mockstack)](https://pypi.org/project/mockstack/)


An API mocking workhorse :racehorse:

Enabling a sane development lifecycle for microservice-oriented architectures and LLM-driven tool chains.

Use mockstack for:

* **Development** :pencil2:. Simulating HTTP-based interactions between a particular component you're developing or debugging locally and multiple other components it depends on during execution of a particular flow. You can create template-based mock responses, simulate creation of resources in a realistic way, as well as proxy to other services using a rich rules DSL. Full request and response metadata and payloads can be observed via OpenTelemetry integration.

* **Integration Testing** :ok_hand:. Creating a consistent environment for running integration tests on a single component, using fixture responses.

* **LLM-powered Workflows** :alien:. Speeding up development and reducing per-token costs of LLM-based workflows and tools for use with frameworks such as [LangChain](https://python.langchain.com/docs/introduction/), [LangGraph](https://www.langchain.com/langgraph) and others. When developing LLM-driven execution graphs. Optional [Ollama](https://ollama.com/) integration allows for realistic mocking of 3rd party LLMs without changing a line of code in your project. In addition, when you want to have a consistent response from a tool while you're tuning prompts or debugging other aspects of a particular trace you can create various fixture responses with varying levels of dynamic content that is template-driven. **mockstack** can give you a solid foundation for this.

* **Chaos Engineering** :boom:. mockstack can simulate various real-world runtime error scenarios such as timeouts, http error codes, and invalid response payloads. This can be a great way to do some upfront [Chaos Monkey](https://github.com/Netflix/chaosmonkey) type of testing on software components.

Highlights include:

* Multiple strategies for handling requests such as [Jinja](https://jinja.palletsprojects.com/en/stable/) template files with intelligent URL request-to-template routing, proxy strategy, and mixed strategies. :game_die:
* Observability via [OpenTelemetry](https://opentelemetry.io/) integration. Get detailed traces of your sessions instantly reported to backends such as [Grafana](https://grafana.com/), [Jaeger](https://www.jaegertracing.io/), [Zipkin](https://zipkin.io/), etc. :eyes:
* Configurability via [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) supports customizing behaviour via environment variables and a `.env` file. :flags:
* Comprehensive unit-tests, linting and formatting coverage as well as vulnerabilities and security scanning with full CI automation to ensure stability and a high-quality codebase for production-grade use. :+1:


## Installation

Install using [uv](https://docs.astral.sh/uv/). This package conforms the concept of a [tool](https://docs.astral.sh/uv/concepts/tools/) and hence can simply install / run with [uvx](https://docs.astral.sh/uv/guides/tools/):

    uvx mockstack --help

or install into a persistent environment and add it to the PATH with:

    uv tool install mockstack


## Usage

See the [examples](https://github.com/promptromp/mockstack/blob/main/examples/) directory for complete examples with documentation.

Available configuration options are [here](https://github.com/promptromp/mockstack/blob/main/mockstack/config.py).

Setting individual options can be done either through an `.env` file, individual environment variables, or command-line arguments.


Minimal example to get you started:

```shell
    mkdir -p ~/mockstack-templates
    echo '{"message": "Hello from mockstack!"}' > ~/mockstack-templates/myservice-api-myresource.j2

    export MOCKSTACK__TEMPLATES_DIR=~/mockstack-templates/
    uvx mockstack
```

You can then hit `http://localhost:8000/myservice/api/myresource/23faa8cf-5daa-4bcb-8c92-27018b712aa9` (or any other UUID).

This is of course just the tip of the iceberg.

See also the included [.env.example](https://github.com/promptromp/mockstack/blob/main/.env.example) for more settings you are likely to find useful. You can copy that file to `.env` and fill in configuration as needed based on the given examples.

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

    gh repo clone promptromp/mockstack
    cd mockstack/
    uv sync
    uv pip install -e .

Run in development mode (for live-reload of changes when developing):

    uv run uvicorn --factory mockstack.main:create_app --reload

Note that when you run using the uvicorn CLI, you will need to set any configuration via `.env` file or environment variables.
