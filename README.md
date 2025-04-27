# mockstack

:racehorse: An API mocking workhorse :racehorse:. Ideal for microservice-oriented architectures.


## Installation

Install using [uv](https://docs.astral.sh/uv/). This will create a virtualenv for you and install all dependencies:

    uv sync


## Usage

Run in development mode (for live-reload of changes):

    uv run fastapi dev mockstack/main.py

Run in production mode:

    uv run fastapi run mockstack/main.py


## Testing

Invoke unit-tests with:

    uv run python -m pytest
