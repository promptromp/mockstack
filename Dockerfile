# Use Python 3.13 as base image
FROM python:3.13.3-slim

# Define build argument for version
ARG MOCKSTACK_VERSION=0.1.0

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv and add it to PATH
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    echo 'export PATH="/root/.cargo/bin:$PATH"' >> /root/.bashrc && \
    . /root/.bashrc

# Set working directory
WORKDIR /app

# Create package structure
RUN mkdir -p /app/src/mockstack /app/templates

# Copy package files
COPY mockstack /app/src/mockstack/
COPY pyproject.toml setup.* README.md /app/

# Set version using build argument
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${MOCKSTACK_VERSION}

# Create and activate virtual environment, then install dependencies
RUN . /root/.bashrc && \
    uv venv && \
    . .venv/bin/activate && \
    cd /app && \
    uv pip install -e .

# Set required environment variables
ENV MOCKSTACK__TEMPLATES_DIR=/app/templates
ENV MOCKSTACK__FILEFIXTURES_ENABLE_TEMPLATES_FOR_POST=true

# Create a sample template file for testing
RUN echo '{"message": "Hello from mockstack!"}' > /app/templates/index.j2

# Expose the default port
EXPOSE 8000

# Set the entrypoint to run the mockstack service
ENTRYPOINT ["/bin/bash", "-c", "source /root/.bashrc && . .venv/bin/activate && cd /app && uv run mockstack"]
