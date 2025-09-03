# ---------------------------- Build Time Arguments ----------------------------

# Define build argument for version
ARG PYTHON_IMAGE_VERSION=3.13-slim
ARG MOCKSTACK_VERSION=0.8.0

# ---------------------------- Base Image --------------------------------

FROM python:${PYTHON_IMAGE_VERSION} AS base

# Install system dependencies
RUN apt-get update && apt-get install --no-install-recommends -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv and add it to PATH
ENV PATH="/root/.local/bin:${PATH}"
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# ---------------------------- Builder --------------------------------

FROM base AS builder

ARG MOCKSTACK_VERSION

# Maintainer label
LABEL maintainer="mockstack.contact@gmail.com"

# Set working directory
WORKDIR /app

# Create package structure
RUN mkdir -p /app/src/mockstack /usr/local/share/mockstack/templates

# Copy package files
COPY mockstack /app/src/mockstack/
COPY docker-entrypoint.sh pyproject.toml setup.* README.md /app/

WORKDIR /app

# Set version using build argument. Needs to happen before
# we install the package with `pip install -e` below.
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${MOCKSTACK_VERSION}

# Create and activate virtual environment, then install dependencies
RUN uv venv && \
    . .venv/bin/activate

RUN uv pip install -e .

# ---------------------------- Runner --------------------------------

FROM builder AS runner

# Set required environment variables for virtualenv
ENV VIRTUAL_ENV="/app/.venv"
ENV PATH="/app/.venv/bin:$PATH"

# Set default
ENV MOCKSTACK__TEMPLATES_DIR=/usr/local/share/mockstack/templates

# Create a sample template file for default running of mockstack
RUN echo '{"message": "Hello from mockstack!"}' > /usr/local/share/mockstack/templates/index.j2

# Expose the default port
EXPOSE 8000

# Set the entrypoint to run the mockstack service
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uv", "run", "mockstack"]
