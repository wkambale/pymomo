# Contributing

Contributions are welcome. Follow these guidelines to set up your environment, follow code styling standards, and write tests.

## Development setup

Clone the repository and install the development dependencies:

```bash
git clone https://github.com/wkambale/pymomo.git
cd pymomo
pip install -e ".[dev]"
```

## Styling rules

We enforce strict formatting rules to maintain codebase quality:
- Formatting: Black with a line limit of 88.
- Import ordering: Isort configured with the Black profile.
- Linters: Ruff default ruleset.
- Security: Bandit scans must report zero high-severity findings.

### Formatting commands

Verify your format and style before submitting a pull request:

```bash
ruff check .
black --check .
isort --check .
```

## Type safety

The library is strictly typed. Run mypy to ensure there are no errors:

```bash
mypy pymomo/
```

## Writing and running tests

All new methods and error handlers must be verified by unit tests under `tests/`.

### Intercepting external requests

No tests should make live connection requests to MTN or Airtel servers. Use `pytest-httpx` to register mock responses.

### Running the test suite

Run the test suite and verify test coverage using:

```bash
pytest --cov=pymomo --cov-report=term-missing
```

The coverage threshold is **90%** minimum.
