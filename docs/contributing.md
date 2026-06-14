# Contributing

Contributions are welcome. Follow these guidelines to set up your environment, follow code styling standards, and write tests.

## Development setup

Clone the repository and install the development dependencies:

```bash
git clone https://github.com/pymomo/pymomo.git
cd pymomo
pip install -e ".[dev]"
```

## Styling rules

We enforce strict formatting rules to maintain codebase quality:
- Formatting: Black format tool with a line limit of 88.
- Import ordering: Isort tool configured to Black profile.
- Linters: Ruff check defaults.
- Security: Bandit scans must raise zero findings.

### Formatting commands

Verify your format and style before submitting a pull request:

```bash
ruff check .
black --check .
isort --check .
```

---

## Type safety

The library is strictly typed. Run mypy to ensure there are no validation warnings:

```bash
mypy pymomo/
```

---

## Writing and running tests

All new methods and error handlers must be verified by unit tests under `tests/`.

### Intercepting external requests

No tests should make live connection requests to MTN servers. Use `pytest-httpx` to register mock responses.

### Running the test suite

Run the test suite and verify test coverage using:

```bash
pytest --cov=pymomo --cov-report=term-missing
```

The coverage threshold is **90%** minimum.
