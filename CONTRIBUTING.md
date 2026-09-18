# Contributing to mockstack

Thank you for your interest in contributing to mockstack! We welcome contributions from the community and appreciate your help in making this project better.

## Getting Started

### Prerequisites

- Python 3.13 or higher (CI tests 3.13 and 3.14)
- [uv](https://docs.astral.sh/uv/)
- Git
- A GitHub account

### Setting Up Your Development Environment

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/mockstack.git
   cd mockstack
   ```
3. Install the package in development mode, with its development dependencies (which
   include the optional `opentelemetry` extra, since the tests exercise tracing). `uv sync`
   creates the `.venv` virtual environment itself:
   ```bash
   uv sync
   ```
   Run commands in it with `uv run` (e.g. `uv run pytest`), or activate it with
   `source .venv/bin/activate` (on Windows: `.venv\Scripts\activate`).
4. Install the pre-commit hooks, which run ruff, mypy and the unit tests on every commit:
   ```bash
   uvx pre-commit install
   ```

## How to Contribute

### Reporting Bugs

If you find a bug, please create an issue using our **Bug Report** template. This helps us understand and reproduce the issue quickly. Include:

- A clear description of the problem
- Steps to reproduce the issue
- Expected vs actual behavior
- Your environment details (mockstack version, Python version, OS, etc.)
- Any relevant code snippets or error messages

### Suggesting Features

We welcome feature suggestions! Please use our **Feature Request** template when creating an issue. Help us understand:

- The problem your feature would solve
- How you envision the feature working
- Any alternatives you've considered
- Whether you're willing to help implement it

### Contributing Code

1. **Create a branch** for your work:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following our coding standards:
   - Write clear, readable code
   - Follow PEP 8 style guidelines
   - Add docstrings to new functions and classes
   - Keep commits focused and atomic

3. **Add tests** for your changes:
   - All new functionality should include tests
   - Ensure existing tests still pass
   - Aim for good test coverage

4. **Run the test suite**:
   ```bash
   uv run pytest                               # unit tests
   uv run pytest -m slow mockstack/tests/live  # live tests against real servers on loopback sockets
   uvx pre-commit run --all-files              # ruff, mypy, and the unit tests with a 90% coverage threshold
   ```

5. **Commit your changes**:
   ```bash
   git add .
   git commit -m "Clear description of your changes"
   ```

6. **Push to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```

7. **Create a Pull Request** on GitHub with:
   - A clear title and description
   - Reference to any related issues
   - Description of what you changed and why

### Code Style

- Follow PEP 8 Python style guidelines. We use `ruff` for linting and formatting, with the rule families configured in `pyproject.toml` (bugbear, bandit, pyupgrade, simplify and more). CI and the pre-commit hooks pin the ruff version.
- Use meaningful variable and function names
- Write clear commit messages, with a conventional prefix (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `ci:`)
- Keep lines within 120 characters (enforced by `ruff`)
- Fully annotate production code: mypy runs with `disallow_untyped_defs`. Tests may leave fixture and parametrized arguments unannotated

### Testing

- Write tests for all new functionality
- Ensure all tests pass before submitting a PR
- Include both positive and negative test cases
- Test edge cases and error conditions

## Development Workflow

1. Check existing issues and PRs to avoid duplicate work
2. For significant changes, consider opening an issue first to discuss the approach
3. Create a focused branch for each feature or bug fix
4. Write clear, descriptive commit messages
5. Keep PRs reasonably sized and focused
6. Be responsive to feedback during code review

## Getting Help

- Check existing issues and documentation first
- Create a new issue if you need help or have questions
- Be patient and respectful in all interactions

## Code of Conduct

Please be respectful and constructive in all interactions. We're all here to learn and improve the project together.

See our CODE_OF_CONDUCT.md file in this repository for further details.

## License

By contributing to mockstack, you agree that your contributions will be licensed under the same license as the project.

See our LICENSE file in this repository for further details.

---

Thank you for contributing to mockstack! 🎉
