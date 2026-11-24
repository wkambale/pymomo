from __future__ import annotations

import functools
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar, cast

import typer
from pydantic import ValidationError

from py_momo_sdk import __version__
from py_momo_sdk.airtel.client import AirtelClient
from py_momo_sdk.airtel.config import AirtelConfig, encrypt_airtel_pin
from py_momo_sdk.client import PyMomoSDK
from py_momo_sdk.config import ProductConfig, PyMomoSDKConfig
from py_momo_sdk.exceptions import PyMomoSDKError
from py_momo_sdk.mock_server import create_mock_server
from py_momo_sdk.utils import detect_carrier_from_msisdn
from py_momo_sdk.webhooks import WebhookHandler

app = typer.Typer(help="Py MoMo SDK CLI tool.")
sandbox_app = typer.Typer(help="Sandbox provisioning commands.")
collection_app = typer.Typer(help="Collection product commands.")
disbursement_app = typer.Typer(help="Disbursement product commands.")
remittance_app = typer.Typer(help="Remittance product commands.")
airtel_app = typer.Typer(help="Airtel Money commands.")
webhook_app = typer.Typer(help="Webhook verification utilities.")

app.add_typer(sandbox_app, name="sandbox")
app.add_typer(collection_app, name="collection")
app.add_typer(disbursement_app, name="disbursement")
app.add_typer(remittance_app, name="remittance")
app.add_typer(airtel_app, name="airtel")
app.add_typer(webhook_app, name="webhook")


F = TypeVar("F", bound=Callable[..., Any])


def _get_version() -> str:
    """Return the installed py-momo-sdk package version."""
    return __version__


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"py-momo-sdk {_get_version()}")
        raise typer.Exit()


def _clean_opt(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _clean_env(value: str | None, default: str = "sandbox") -> str:
    return _clean_opt(value) or default


def _resolve_secret(
    direct: str | None,
    *,
    file_path: str | None = None,
    field_name: str,
    prompt_if_tty: bool = True,
) -> str:
    """Resolve a secret from direct option/env, file path (or '-' for stdin), or TTY prompt."""
    cleaned_file = _clean_opt(file_path)
    if cleaned_file is not None:
        if cleaned_file == "-":
            val = sys.stdin.read().strip()
        else:
            val = Path(cleaned_file).read_text(encoding="utf-8").strip()
        if not val:
            raise ValueError(f"{field_name} file must not be empty")
        return val
    cleaned_direct = _clean_opt(direct)
    if cleaned_direct is not None:
        return cleaned_direct
    if prompt_if_tty and sys.stdin.isatty():
        prompted = str(typer.prompt(field_name, hide_input=True)).strip()
        if prompted:
            return prompted
    raise ValueError(
        f"{field_name} is required (provide via environment variable, --*-file, or option)"
    )


def _format_validation_error(exc: ValidationError) -> str:
    """Format Pydantic ValidationError without echoing raw input values or docs URLs."""
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        msg = str(err.get("msg", "Invalid value"))
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) if parts else "Invalid input."


def _echo_json(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2))


@app.callback()
def main(
    _version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the Py MoMo SDK version and exit.",
    ),
) -> None:
    """Py MoMo SDK command-line interface."""


def handle_cli_exceptions(func: F) -> F:
    """Decorator to catch Py MoMo SDK exceptions and exit cleanly with code 1."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except (typer.Exit, typer.Abort):
            raise
        except ValidationError as e:
            typer.echo(f"Error: {_format_validation_error(e)}", err=True)
            raise typer.Exit(code=1) from None
        except PyMomoSDKError as e:
            msg = str(e)
            msg = msg[0].upper() + msg[1:] if msg else "An unexpected error occurred."
            if e.reference_id and e.reference_id not in msg:
                msg = f"{msg} (reference_id: {e.reference_id})"
            typer.echo(f"Error: {msg}", err=True)
            raise typer.Exit(code=1) from None
        except ValueError as e:
            msg = str(e)
            msg = msg[0].upper() + msg[1:] if msg else "Invalid input."
            typer.echo(f"Error: {msg}", err=True)
            raise typer.Exit(code=1) from None
        except OSError as e:
            typer.echo(f"Error: I/O failure ({type(e).__name__}).", err=True)
            raise typer.Exit(code=1) from None
        except Exception as e:
            typer.echo(
                f"Unexpected error ({type(e).__name__}). Check your inputs and try again.",
                err=True,
            )
            raise typer.Exit(code=1) from None

    return cast(F, wrapper)


def _build_mtn_config(
    *,
    environment: str,
    base_url: str | None,
    timeout: float,
    max_retries: int,
    retry_backoff: float,
    collection: ProductConfig | None = None,
    disbursement: ProductConfig | None = None,
    remittance: ProductConfig | None = None,
) -> PyMomoSDKConfig:
    return PyMomoSDKConfig(
        environment=_clean_env(environment),
        base_url=_clean_opt(base_url),
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        collection=collection,
        disbursement=disbursement,
        remittance=remittance,
    )


@sandbox_app.command(name="provision")
@handle_cli_exceptions
def sandbox_provision(
    subscription_key: str | None = typer.Option(
        None,
        "--subscription-key",
        "-k",
        envvar="PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY",
        help="Ocp-Apim-Subscription-Key (prefer PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY or --subscription-key-file).",
    ),
    subscription_key_file: str | None = typer.Option(
        None,
        "--subscription-key-file",
        help="Path to file containing subscription key (or '-' for stdin).",
    ),
    callback_host: str = typer.Option(
        "example.com",
        "--callback-host",
        "-c",
        help="Provider callback host (bare hostname or HTTPS URL).",
    ),
    environment: str = typer.Option(
        "sandbox",
        "--environment",
        "-e",
        envvar="PY_MOMO_SDK_ENVIRONMENT",
        help="Target environment.",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        envvar="PY_MOMO_SDK_BASE_URL",
        help="Override API base URL.",
    ),
    timeout: float = typer.Option(30.0, "--timeout", help="HTTP timeout in seconds."),
    max_retries: int = typer.Option(0, "--max-retries", help="Max retries."),
    retry_backoff: float = typer.Option(
        0.5, "--retry-backoff", help="Retry backoff base in seconds."
    ),
    output_file: str | None = typer.Option(
        None,
        "--output-file",
        help="Write credentials JSON to a mode-0600 file instead of printing raw api_key to stdout.",
    ),
    redact_secret: bool = typer.Option(
        False,
        "--redact-secret",
        help="Redact api_key in stdout JSON output.",
    ),
) -> None:
    """Provision a new sandbox API user and API key."""
    resolved_sub = _resolve_secret(
        subscription_key,
        file_path=subscription_key_file,
        field_name="subscription_key",
    )
    config = _build_mtn_config(
        environment=environment,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
    )
    with PyMomoSDK(config) as client:
        provisioner = client.create_sandbox_provisioner(resolved_sub)
        result = provisioner.provision(callback_host=callback_host)
        out_path = _clean_opt(output_file)
        if out_path is not None:
            fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(dict(result), indent=2) + "\n")
            _echo_json(
                {
                    "api_user": result["api_user"],
                    "api_key": "<written to file>",
                    "output_file": out_path,
                }
            )
            return
        if redact_secret:
            _echo_json({"api_user": result["api_user"], "api_key": "<redacted>"})
            return
        _echo_json(dict(result))


@sandbox_app.command(name="get-user")
@handle_cli_exceptions
def sandbox_get_user(
    user_id: str = typer.Argument(..., help="The API user UUID."),
    subscription_key: str | None = typer.Option(
        None,
        "--subscription-key",
        "-k",
        envvar="PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY",
        help="Ocp-Apim-Subscription-Key (prefer PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY or --subscription-key-file).",
    ),
    subscription_key_file: str | None = typer.Option(
        None,
        "--subscription-key-file",
        help="Path to file containing subscription key (or '-' for stdin).",
    ),
    environment: str = typer.Option(
        "sandbox",
        "--environment",
        "-e",
        envvar="PY_MOMO_SDK_ENVIRONMENT",
        help="Target environment.",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        envvar="PY_MOMO_SDK_BASE_URL",
        help="Override API base URL.",
    ),
    timeout: float = typer.Option(30.0, "--timeout", help="HTTP timeout in seconds."),
    max_retries: int = typer.Option(0, "--max-retries", help="Max retries."),
    retry_backoff: float = typer.Option(
        0.5, "--retry-backoff", help="Retry backoff base in seconds."
    ),
) -> None:
    """Get information about a sandbox API user."""
    resolved_sub = _resolve_secret(
        subscription_key,
        file_path=subscription_key_file,
        field_name="subscription_key",
    )
    config = _build_mtn_config(
        environment=environment,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
    )
    with PyMomoSDK(config) as client:
        provisioner = client.create_sandbox_provisioner(resolved_sub)
        result = provisioner.get_api_user(user_id)
        _echo_json(result.model_dump(by_alias=True, mode="json"))


@collection_app.command(name="balance")
@handle_cli_exceptions
def collection_balance(
    subscription_key: str | None = typer.Option(
        None,
        "--subscription-key",
        "-k",
        envvar="PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY",
        help="Collection subscription key (prefer env var or --subscription-key-file).",
    ),
    subscription_key_file: str | None = typer.Option(
        None,
        "--subscription-key-file",
        help="Path to file containing subscription key (or '-' for stdin).",
    ),
    api_user: str = typer.Option(
        ...,
        "--api-user",
        "-u",
        envvar="PY_MOMO_SDK_COLLECTION_API_USER",
        help="Collection API user UUID.",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        "-p",
        envvar="PY_MOMO_SDK_COLLECTION_API_KEY",
        help="Collection API key (prefer env var or --api-key-file).",
    ),
    api_key_file: str | None = typer.Option(
        None,
        "--api-key-file",
        help="Path to file containing API key (or '-' for stdin).",
    ),
    currency: str | None = typer.Option(
        None,
        "--currency",
        help="Optional ISO currency code for per-currency balance lookup.",
    ),
    environment: str = typer.Option(
        "sandbox",
        "--environment",
        "-e",
        envvar="PY_MOMO_SDK_ENVIRONMENT",
        help="Target environment.",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        envvar="PY_MOMO_SDK_BASE_URL",
        help="Override API base URL.",
    ),
    timeout: float = typer.Option(30.0, "--timeout", help="HTTP timeout in seconds."),
    max_retries: int = typer.Option(0, "--max-retries", help="Max retries."),
    retry_backoff: float = typer.Option(
        0.5, "--retry-backoff", help="Retry backoff base in seconds."
    ),
) -> None:
    """Get the balance of the collection account."""
    config = _build_mtn_config(
        environment=environment,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        collection=ProductConfig(
            subscription_key=_resolve_secret(
                subscription_key,
                file_path=subscription_key_file,
                field_name="subscription_key",
            ),
            api_user=api_user.strip(),
            api_key=_resolve_secret(
                api_key, file_path=api_key_file, field_name="api_key"
            ),
        ),
    )
    with PyMomoSDK(config) as client:
        cleaned_curr = _clean_opt(currency)
        balance = (
            client.collection.get_balance_for_currency(cleaned_curr)
            if cleaned_curr is not None
            else client.collection.get_balance()
        )
        _echo_json(balance.model_dump(by_alias=True, mode="json"))


@collection_app.command(name="request-to-pay")
@handle_cli_exceptions
def collection_request_to_pay(
    msisdn: str = typer.Argument(..., help="The payer MSISDN."),
    amount: str = typer.Argument(..., help="Transaction amount."),
    currency: str = typer.Argument(..., help="ISO currency code."),
    external_id: str = typer.Argument(..., help="External transaction identifier."),
    subscription_key: str | None = typer.Option(
        None,
        "--subscription-key",
        "-k",
        envvar="PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY",
        help="Collection subscription key (prefer env var or --subscription-key-file).",
    ),
    subscription_key_file: str | None = typer.Option(
        None,
        "--subscription-key-file",
        help="Path to file containing subscription key (or '-' for stdin).",
    ),
    api_user: str = typer.Option(
        ...,
        "--api-user",
        "-u",
        envvar="PY_MOMO_SDK_COLLECTION_API_USER",
        help="Collection API user UUID.",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        "-p",
        envvar="PY_MOMO_SDK_COLLECTION_API_KEY",
        help="Collection API key (prefer env var or --api-key-file).",
    ),
    api_key_file: str | None = typer.Option(
        None,
        "--api-key-file",
        help="Path to file containing API key (or '-' for stdin).",
    ),
    payer_message: str = typer.Option(
        "", "--payer-message", help="Message to the payer."
    ),
    payee_note: str = typer.Option("", "--payee-note", help="Note to the payee."),
    reference_id: str | None = typer.Option(
        None, "--reference-id", help="Optional custom UUID reference ID."
    ),
    callback_url: str | None = typer.Option(
        None, "--callback-url", help="Optional HTTPS webhook callback URL."
    ),
    environment: str = typer.Option(
        "sandbox",
        "--environment",
        "-e",
        envvar="PY_MOMO_SDK_ENVIRONMENT",
        help="Target environment.",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        envvar="PY_MOMO_SDK_BASE_URL",
        help="Override API base URL.",
    ),
    timeout: float = typer.Option(30.0, "--timeout", help="HTTP timeout in seconds."),
    max_retries: int = typer.Option(0, "--max-retries", help="Max retries."),
    retry_backoff: float = typer.Option(
        0.5, "--retry-backoff", help="Retry backoff base in seconds."
    ),
) -> None:
    """Initiate a Request to Pay transaction."""
    config = _build_mtn_config(
        environment=environment,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        collection=ProductConfig(
            subscription_key=_resolve_secret(
                subscription_key,
                file_path=subscription_key_file,
                field_name="subscription_key",
            ),
            api_user=api_user.strip(),
            api_key=_resolve_secret(
                api_key, file_path=api_key_file, field_name="api_key"
            ),
        ),
    )
    with PyMomoSDK(config) as client:
        ref_id = client.collection.request_to_pay(
            amount=amount,
            currency=currency,
            payer_msisdn=msisdn,
            external_id=external_id,
            payer_message=payer_message,
            payee_note=payee_note,
            reference_id=_clean_opt(reference_id),
            callback_url=_clean_opt(callback_url),
        )
        _echo_json({"reference_id": ref_id})


@collection_app.command(name="status")
@handle_cli_exceptions
def collection_status(
    reference_id: str = typer.Argument(
        ..., help="The Request to Pay transaction reference UUID."
    ),
    subscription_key: str | None = typer.Option(
        None,
        "--subscription-key",
        "-k",
        envvar="PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY",
        help="Collection subscription key (prefer env var or --subscription-key-file).",
    ),
    subscription_key_file: str | None = typer.Option(
        None,
        "--subscription-key-file",
        help="Path to file containing subscription key (or '-' for stdin).",
    ),
    api_user: str = typer.Option(
        ...,
        "--api-user",
        "-u",
        envvar="PY_MOMO_SDK_COLLECTION_API_USER",
        help="Collection API user UUID.",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        "-p",
        envvar="PY_MOMO_SDK_COLLECTION_API_KEY",
        help="Collection API key (prefer env var or --api-key-file).",
    ),
    api_key_file: str | None = typer.Option(
        None,
        "--api-key-file",
        help="Path to file containing API key (or '-' for stdin).",
    ),
    environment: str = typer.Option(
        "sandbox",
        "--environment",
        "-e",
        envvar="PY_MOMO_SDK_ENVIRONMENT",
        help="Target environment.",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        envvar="PY_MOMO_SDK_BASE_URL",
        help="Override API base URL.",
    ),
    timeout: float = typer.Option(30.0, "--timeout", help="HTTP timeout in seconds."),
    max_retries: int = typer.Option(0, "--max-retries", help="Max retries."),
    retry_backoff: float = typer.Option(
        0.5, "--retry-backoff", help="Retry backoff base in seconds."
    ),
) -> None:
    """Get the status of a Request to Pay transaction."""
    config = _build_mtn_config(
        environment=environment,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        collection=ProductConfig(
            subscription_key=_resolve_secret(
                subscription_key,
                file_path=subscription_key_file,
                field_name="subscription_key",
            ),
            api_user=api_user.strip(),
            api_key=_resolve_secret(
                api_key, file_path=api_key_file, field_name="api_key"
            ),
        ),
    )
    with PyMomoSDK(config) as client:
        result = client.collection.get_payment_status(reference_id)
        _echo_json(result.model_dump(by_alias=True, mode="json"))


@disbursement_app.command(name="balance")
@handle_cli_exceptions
def disbursement_balance(
    subscription_key: str | None = typer.Option(
        None,
        "--subscription-key",
        "-k",
        envvar="PY_MOMO_SDK_DISBURSEMENT_SUBSCRIPTION_KEY",
        help="Disbursement subscription key (prefer env var or --subscription-key-file).",
    ),
    subscription_key_file: str | None = typer.Option(
        None,
        "--subscription-key-file",
        help="Path to file containing subscription key (or '-' for stdin).",
    ),
    api_user: str = typer.Option(
        ...,
        "--api-user",
        "-u",
        envvar="PY_MOMO_SDK_DISBURSEMENT_API_USER",
        help="Disbursement API user UUID.",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        "-p",
        envvar="PY_MOMO_SDK_DISBURSEMENT_API_KEY",
        help="Disbursement API key (prefer env var or --api-key-file).",
    ),
    api_key_file: str | None = typer.Option(
        None,
        "--api-key-file",
        help="Path to file containing API key (or '-' for stdin).",
    ),
    currency: str | None = typer.Option(
        None, "--currency", help="Optional ISO currency code."
    ),
    environment: str = typer.Option(
        "sandbox",
        "--environment",
        "-e",
        envvar="PY_MOMO_SDK_ENVIRONMENT",
        help="Target environment.",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        envvar="PY_MOMO_SDK_BASE_URL",
        help="Override API base URL.",
    ),
    timeout: float = typer.Option(30.0, "--timeout", help="HTTP timeout in seconds."),
    max_retries: int = typer.Option(0, "--max-retries", help="Max retries."),
    retry_backoff: float = typer.Option(
        0.5, "--retry-backoff", help="Retry backoff base in seconds."
    ),
) -> None:
    """Get the balance of the disbursement account."""
    config = _build_mtn_config(
        environment=environment,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        disbursement=ProductConfig(
            subscription_key=_resolve_secret(
                subscription_key,
                file_path=subscription_key_file,
                field_name="subscription_key",
            ),
            api_user=api_user.strip(),
            api_key=_resolve_secret(
                api_key, file_path=api_key_file, field_name="api_key"
            ),
        ),
    )
    with PyMomoSDK(config) as client:
        cleaned_curr = _clean_opt(currency)
        balance = (
            client.disbursement.get_balance_for_currency(cleaned_curr)
            if cleaned_curr is not None
            else client.disbursement.get_balance()
        )
        _echo_json(balance.model_dump(by_alias=True, mode="json"))


@disbursement_app.command(name="transfer")
@handle_cli_exceptions
def disbursement_transfer(
    msisdn: str = typer.Argument(..., help="The payee MSISDN."),
    amount: str = typer.Argument(..., help="Transaction amount."),
    currency: str = typer.Argument(..., help="ISO currency code."),
    external_id: str = typer.Argument(..., help="External transaction identifier."),
    subscription_key: str | None = typer.Option(
        None,
        "--subscription-key",
        "-k",
        envvar="PY_MOMO_SDK_DISBURSEMENT_SUBSCRIPTION_KEY",
        help="Disbursement subscription key.",
    ),
    subscription_key_file: str | None = typer.Option(
        None, "--subscription-key-file", help="Path to subscription key file (or '-')."
    ),
    api_user: str = typer.Option(
        ..., "--api-user", "-u", envvar="PY_MOMO_SDK_DISBURSEMENT_API_USER"
    ),
    api_key: str | None = typer.Option(
        None, "--api-key", "-p", envvar="PY_MOMO_SDK_DISBURSEMENT_API_KEY"
    ),
    api_key_file: str | None = typer.Option(
        None, "--api-key-file", help="Path to API key file (or '-')."
    ),
    payer_message: str = typer.Option("", "--payer-message"),
    payee_note: str = typer.Option("", "--payee-note"),
    reference_id: str | None = typer.Option(None, "--reference-id"),
    callback_url: str | None = typer.Option(None, "--callback-url"),
    environment: str = typer.Option(
        "sandbox", "--environment", "-e", envvar="PY_MOMO_SDK_ENVIRONMENT"
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", envvar="PY_MOMO_SDK_BASE_URL"
    ),
    timeout: float = typer.Option(30.0, "--timeout"),
    max_retries: int = typer.Option(0, "--max-retries"),
    retry_backoff: float = typer.Option(0.5, "--retry-backoff"),
) -> None:
    """Initiate a disbursement transfer."""
    config = _build_mtn_config(
        environment=environment,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        disbursement=ProductConfig(
            subscription_key=_resolve_secret(
                subscription_key,
                file_path=subscription_key_file,
                field_name="subscription_key",
            ),
            api_user=api_user.strip(),
            api_key=_resolve_secret(
                api_key, file_path=api_key_file, field_name="api_key"
            ),
        ),
    )
    with PyMomoSDK(config) as client:
        ref_id = client.disbursement.transfer(
            amount=amount,
            currency=currency,
            payee_msisdn=msisdn,
            external_id=external_id,
            payer_message=payer_message,
            payee_note=payee_note,
            reference_id=_clean_opt(reference_id),
            callback_url=_clean_opt(callback_url),
        )
        _echo_json({"reference_id": ref_id})


@disbursement_app.command(name="status")
@handle_cli_exceptions
def disbursement_status(
    reference_id: str = typer.Argument(..., help="Transfer reference UUID."),
    subscription_key: str | None = typer.Option(
        None,
        "--subscription-key",
        "-k",
        envvar="PY_MOMO_SDK_DISBURSEMENT_SUBSCRIPTION_KEY",
    ),
    subscription_key_file: str | None = typer.Option(None, "--subscription-key-file"),
    api_user: str = typer.Option(
        ..., "--api-user", "-u", envvar="PY_MOMO_SDK_DISBURSEMENT_API_USER"
    ),
    api_key: str | None = typer.Option(
        None, "--api-key", "-p", envvar="PY_MOMO_SDK_DISBURSEMENT_API_KEY"
    ),
    api_key_file: str | None = typer.Option(None, "--api-key-file"),
    environment: str = typer.Option(
        "sandbox", "--environment", "-e", envvar="PY_MOMO_SDK_ENVIRONMENT"
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", envvar="PY_MOMO_SDK_BASE_URL"
    ),
    timeout: float = typer.Option(30.0, "--timeout"),
    max_retries: int = typer.Option(0, "--max-retries"),
    retry_backoff: float = typer.Option(0.5, "--retry-backoff"),
) -> None:
    """Get the status of a disbursement transfer."""
    config = _build_mtn_config(
        environment=environment,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        disbursement=ProductConfig(
            subscription_key=_resolve_secret(
                subscription_key,
                file_path=subscription_key_file,
                field_name="subscription_key",
            ),
            api_user=api_user.strip(),
            api_key=_resolve_secret(
                api_key, file_path=api_key_file, field_name="api_key"
            ),
        ),
    )
    with PyMomoSDK(config) as client:
        result = client.disbursement.get_transfer_status(reference_id)
        _echo_json(result.model_dump(by_alias=True, mode="json"))


@remittance_app.command(name="balance")
@handle_cli_exceptions
def remittance_balance(
    subscription_key: str | None = typer.Option(
        None,
        "--subscription-key",
        "-k",
        envvar="PY_MOMO_SDK_REMITTANCE_SUBSCRIPTION_KEY",
        help="Remittance subscription key (prefer env var or --subscription-key-file).",
    ),
    subscription_key_file: str | None = typer.Option(
        None,
        "--subscription-key-file",
        help="Path to file containing subscription key (or '-' for stdin).",
    ),
    api_user: str = typer.Option(
        ...,
        "--api-user",
        "-u",
        envvar="PY_MOMO_SDK_REMITTANCE_API_USER",
        help="Remittance API user UUID.",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        "-p",
        envvar="PY_MOMO_SDK_REMITTANCE_API_KEY",
        help="Remittance API key (prefer env var or --api-key-file).",
    ),
    api_key_file: str | None = typer.Option(
        None,
        "--api-key-file",
        help="Path to file containing API key (or '-' for stdin).",
    ),
    currency: str | None = typer.Option(
        None, "--currency", help="Optional ISO currency code."
    ),
    environment: str = typer.Option(
        "sandbox",
        "--environment",
        "-e",
        envvar="PY_MOMO_SDK_ENVIRONMENT",
        help="Target environment.",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        envvar="PY_MOMO_SDK_BASE_URL",
        help="Override API base URL.",
    ),
    timeout: float = typer.Option(30.0, "--timeout", help="HTTP timeout in seconds."),
    max_retries: int = typer.Option(0, "--max-retries", help="Max retries."),
    retry_backoff: float = typer.Option(
        0.5, "--retry-backoff", help="Retry backoff base in seconds."
    ),
) -> None:
    """Get the balance of the remittance account."""
    config = _build_mtn_config(
        environment=environment,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        remittance=ProductConfig(
            subscription_key=_resolve_secret(
                subscription_key,
                file_path=subscription_key_file,
                field_name="subscription_key",
            ),
            api_user=api_user.strip(),
            api_key=_resolve_secret(
                api_key, file_path=api_key_file, field_name="api_key"
            ),
        ),
    )
    with PyMomoSDK(config) as client:
        cleaned_curr = _clean_opt(currency)
        balance = (
            client.remittance.get_balance_for_currency(cleaned_curr)
            if cleaned_curr is not None
            else client.remittance.get_balance()
        )
        _echo_json(balance.model_dump(by_alias=True, mode="json"))


@remittance_app.command(name="transfer")
@handle_cli_exceptions
def remittance_transfer(
    msisdn: str = typer.Argument(..., help="The payee MSISDN."),
    amount: str = typer.Argument(..., help="Transaction amount."),
    currency: str = typer.Argument(..., help="ISO currency code."),
    external_id: str = typer.Argument(..., help="External transaction identifier."),
    subscription_key: str | None = typer.Option(
        None,
        "--subscription-key",
        "-k",
        envvar="PY_MOMO_SDK_REMITTANCE_SUBSCRIPTION_KEY",
    ),
    subscription_key_file: str | None = typer.Option(None, "--subscription-key-file"),
    api_user: str = typer.Option(
        ..., "--api-user", "-u", envvar="PY_MOMO_SDK_REMITTANCE_API_USER"
    ),
    api_key: str | None = typer.Option(
        None, "--api-key", "-p", envvar="PY_MOMO_SDK_REMITTANCE_API_KEY"
    ),
    api_key_file: str | None = typer.Option(None, "--api-key-file"),
    payer_message: str = typer.Option("", "--payer-message"),
    payee_note: str = typer.Option("", "--payee-note"),
    reference_id: str | None = typer.Option(None, "--reference-id"),
    callback_url: str | None = typer.Option(None, "--callback-url"),
    environment: str = typer.Option(
        "sandbox", "--environment", "-e", envvar="PY_MOMO_SDK_ENVIRONMENT"
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", envvar="PY_MOMO_SDK_BASE_URL"
    ),
    timeout: float = typer.Option(30.0, "--timeout"),
    max_retries: int = typer.Option(0, "--max-retries"),
    retry_backoff: float = typer.Option(0.5, "--retry-backoff"),
) -> None:
    """Initiate a remittance transfer."""
    config = _build_mtn_config(
        environment=environment,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        remittance=ProductConfig(
            subscription_key=_resolve_secret(
                subscription_key,
                file_path=subscription_key_file,
                field_name="subscription_key",
            ),
            api_user=api_user.strip(),
            api_key=_resolve_secret(
                api_key, file_path=api_key_file, field_name="api_key"
            ),
        ),
    )
    with PyMomoSDK(config) as client:
        ref_id = client.remittance.transfer(
            amount=amount,
            currency=currency,
            payee_msisdn=msisdn,
            external_id=external_id,
            payer_message=payer_message,
            payee_note=payee_note,
            reference_id=_clean_opt(reference_id),
            callback_url=_clean_opt(callback_url),
        )
        _echo_json({"reference_id": ref_id})


@remittance_app.command(name="status")
@handle_cli_exceptions
def remittance_status(
    reference_id: str = typer.Argument(..., help="Remittance transfer reference UUID."),
    subscription_key: str | None = typer.Option(
        None,
        "--subscription-key",
        "-k",
        envvar="PY_MOMO_SDK_REMITTANCE_SUBSCRIPTION_KEY",
    ),
    subscription_key_file: str | None = typer.Option(None, "--subscription-key-file"),
    api_user: str = typer.Option(
        ..., "--api-user", "-u", envvar="PY_MOMO_SDK_REMITTANCE_API_USER"
    ),
    api_key: str | None = typer.Option(
        None, "--api-key", "-p", envvar="PY_MOMO_SDK_REMITTANCE_API_KEY"
    ),
    api_key_file: str | None = typer.Option(None, "--api-key-file"),
    environment: str = typer.Option(
        "sandbox", "--environment", "-e", envvar="PY_MOMO_SDK_ENVIRONMENT"
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", envvar="PY_MOMO_SDK_BASE_URL"
    ),
    timeout: float = typer.Option(30.0, "--timeout"),
    max_retries: int = typer.Option(0, "--max-retries"),
    retry_backoff: float = typer.Option(0.5, "--retry-backoff"),
) -> None:
    """Get the status of a remittance transfer."""
    config = _build_mtn_config(
        environment=environment,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        remittance=ProductConfig(
            subscription_key=_resolve_secret(
                subscription_key,
                file_path=subscription_key_file,
                field_name="subscription_key",
            ),
            api_user=api_user.strip(),
            api_key=_resolve_secret(
                api_key, file_path=api_key_file, field_name="api_key"
            ),
        ),
    )
    with PyMomoSDK(config) as client:
        result = client.remittance.get_transfer_status(reference_id)
        _echo_json(result.model_dump(by_alias=True, mode="json"))


@airtel_app.command(name="encrypt-pin")
@handle_cli_exceptions
def airtel_encrypt_pin(
    public_key_file: str = typer.Option(
        ..., "--public-key-file", help="Path to Airtel RSA PEM public key file."
    ),
    pin: str | None = typer.Option(None, "--pin", help="Plaintext Airtel PIN."),
    pin_file: str | None = typer.Option(
        None,
        "--pin-file",
        help="Path to file containing Airtel PIN (or '-' for stdin).",
    ),
) -> None:
    """Encrypt an Airtel Money disbursement PIN using an RSA public key."""
    resolved_pin = _resolve_secret(pin, file_path=pin_file, field_name="pin")
    pem = Path(public_key_file).read_text(encoding="utf-8")
    encrypted = encrypt_airtel_pin(resolved_pin, pem)
    _echo_json({"encrypted_pin": encrypted})


@airtel_app.command(name="balance")
@handle_cli_exceptions
def airtel_balance(
    client_id: str = typer.Option(
        ..., "--client-id", envvar="PY_MOMO_SDK_AIRTEL_CLIENT_ID"
    ),
    client_secret: str | None = typer.Option(
        None, "--client-secret", envvar="PY_MOMO_SDK_AIRTEL_CLIENT_SECRET"
    ),
    client_secret_file: str | None = typer.Option(None, "--client-secret-file"),
    country: str = typer.Option("UG", "--country", envvar="PY_MOMO_SDK_AIRTEL_COUNTRY"),
    currency: str = typer.Option(
        "UGX", "--currency", envvar="PY_MOMO_SDK_AIRTEL_CURRENCY"
    ),
    environment: str = typer.Option(
        "sandbox", "--environment", "-e", envvar="PY_MOMO_SDK_ENVIRONMENT"
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", envvar="PY_MOMO_SDK_BASE_URL"
    ),
) -> None:
    """Query the Airtel Money merchant balance."""
    cfg = AirtelConfig(
        client_id=client_id.strip(),
        client_secret=_resolve_secret(
            client_secret, file_path=client_secret_file, field_name="client_secret"
        ),
        country=country.strip(),
        currency=currency.strip(),
        environment=_clean_env(environment),
        base_url=_clean_opt(base_url),
    )
    with AirtelClient(cfg) as client:
        bal = client.disbursement.get_balance()
        _echo_json(bal.model_dump(mode="json"))


@webhook_app.command(name="verify")
@handle_cli_exceptions
def webhook_verify(
    signature: str = typer.Option(..., "--signature", "-s", help="Signature header."),
    payload_file: str = typer.Option(
        "-",
        "--payload-file",
        help="Path to raw webhook body bytes file (or '-' for stdin).",
    ),
    secret: str | None = typer.Option(
        None, "--secret", envvar="PY_MOMO_SDK_WEBHOOK_SECRET"
    ),
    secret_file: str | None = typer.Option(
        None, "--secret-file", help="Path to file containing webhook secret."
    ),
    algorithm: str = typer.Option("sha256", "--algorithm", help="sha256 or sha512."),
    timestamped: bool = typer.Option(
        False, "--timestamped", help="Verify t=<ts>,v1=<hex> timestamped header."
    ),
    timestamp_separator: str = typer.Option(
        ".",
        "--timestamp-separator",
        help="Timestamp separator ('.' by default, '' for Wave).",
    ),
    tolerance_seconds: float = typer.Option(
        300.0, "--tolerance-seconds", help="Replay window in seconds."
    ),
) -> None:
    """Verify an HMAC or timestamped HMAC webhook signature from the CLI."""
    resolved_secret = _resolve_secret(
        secret, file_path=secret_file, field_name="secret"
    )
    raw = (
        sys.stdin.buffer.read()
        if payload_file.strip() == "-"
        else Path(payload_file).read_bytes()
    )
    if timestamped:
        WebhookHandler.verify_timestamped_hmac_signature(
            raw,
            signature,
            resolved_secret,
            tolerance_seconds=tolerance_seconds,
            algorithm=algorithm,
            timestamp_separator=timestamp_separator,
        )
    else:
        WebhookHandler.verify_hmac_signature(
            raw, signature, resolved_secret, algorithm=algorithm
        )
    _echo_json({"verified": True})


@app.command(name="carrier")
@handle_cli_exceptions
def detect_carrier(
    msisdn: str = typer.Argument(..., help="Subscriber MSISDN to inspect."),
) -> None:
    """Detect country and mobile money provider from an MSISDN prefix."""
    match = detect_carrier_from_msisdn(msisdn)
    payload = (
        {"country": match[0], "provider": match[1]}
        if match is not None
        else {"country": None, "provider": None}
    )
    _echo_json(payload)


@app.command(name="mock")
@handle_cli_exceptions
def run_mock_gateway(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host."),
    port: int = typer.Option(8090, "--port", help="Bind port."),
    status: str = typer.Option(
        "SUCCESSFUL",
        "--status",
        help="Default transaction status returned by the mock server (PENDING, SUCCESSFUL, or FAILED).",
    ),
    allow_non_loopback: bool = typer.Option(
        False,
        "--allow-non-loopback",
        help="Explicitly allow binding the unauthenticated mock server to a non-loopback interface.",
    ),
) -> None:
    """Start a local HTTP mock gateway server for CI and sandbox testing."""
    server, _state = create_mock_server(
        host,
        port,
        default_status=status,
        allow_non_loopback=allow_non_loopback,
    )
    bound_host, bound_port = server.server_address[:2]
    typer.echo(
        f"Py MoMo SDK mock gateway listening on http://{bound_host!s}:{bound_port}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    app()
