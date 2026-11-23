# Contributing

Contributions are welcome. Follow these guidelines to set up your environment, follow code styling standards, and write tests.

## Development setup

Clone the repository and install the development dependencies:

```bash
git clone https://github.com/wkambale/pymomo.git
cd pymomo
pip install -e ".[all,dev]"
```

## Styling rules

We enforce strict formatting and quality rules to maintain codebase quality:
- Formatting: Black with a line limit of 88.
- Import ordering: Isort configured with the Black profile.
- Linters: Ruff (`E`, `F`, `B`, `UP`, `SIM`, `RUF`, `S`).
- Security: Bandit (`-ll`) and `pip-audit` must report zero findings.

### Formatting commands

Verify your format and style before submitting a pull request:

```bash
ruff check .
black --check .
isort --check-only .
bandit -r py_momo_sdk/ -ll
```

## Type safety

The library and test suite are checked with mypy:

```bash
mypy py_momo_sdk/ tests/
```

## Writing and running tests

All new methods and error handlers must be verified by unit tests under `tests/`.

### Intercepting external requests

No tests should make live connection requests to MTN, Airtel, or third-party payment gateway servers. Use `pytest-httpx` to register mock responses.

### Running the test suite

Run the test suite and verify test coverage using:

```bash
pytest --cov=py_momo_sdk --cov-report=term-missing
```

The coverage threshold is **90%** minimum.
