from __future__ import annotations

import functools
import json
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Any, TypeVar, cast

import typer

from pymomo.client import MomoClient
from pymomo.config import MomoConfig, ProductConfig
from pymomo.exceptions import PyMoMoError

app = typer.Typer(help="PyMoMo CLI tool.")
sandbox_app = typer.Typer(help="Sandbox provisioning commands.")
collection_app = typer.Typer(help="Collection product commands.")
disbursement_app = typer.Typer(help="Disbursement product commands.")
remittance_app = typer.Typer(help="Remittance product commands.")

app.add_typer(sandbox_app, name="sandbox")
app.add_typer(collection_app, name="collection")
app.add_typer(disbursement_app, name="disbursement")
app.add_typer(remittance_app, name="remittance")


F = TypeVar("F", bound=Callable[..., Any])


def _get_version() -> str:
    """Return the installed pymomo package version."""
    try:
        return package_version("pymomo")
    except PackageNotFoundError:
        return "0.0.0"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"pymomo {_get_version()}")
        raise typer.Exit()


@app.callback()
def main(
    _version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the PyMoMo version and exit.",
    ),
) -> None:
    """PyMoMo command-line interface."""


def handle_cli_exceptions(func: F) -> F:
    """Decorator to catch PyMoMo exceptions and exit cleanly with code 1."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except PyMoMoError as e:
            # Error message is printed to stderr in sentence case
            msg = str(e)
            msg = msg[0].upper() + msg[1:] if msg else "An unexpected error occurred."
            typer.echo(f"Error: {msg}", err=True)
            raise typer.Exit(code=1) from None
        except ValueError as e:
            msg = str(e)
            msg = msg[0].upper() + msg[1:] if msg else "Invalid input."
            typer.echo(f"Error: {msg}", err=True)
            raise typer.Exit(code=1) from None
        except Exception as e:  # noqa: BLE001
            typer.echo(
                f"Unexpected error ({type(e).__name__}). Check your inputs and try again.",
                err=True,
            )
            raise typer.Exit(code=1) from None

    return cast(F, wrapper)


@sandbox_app.command(name="provision")
@handle_cli_exceptions
def sandbox_provision(
    subscription_key: str = typer.Option(
        ...,
        "--subscription-key",
        "-k",
        envvar="PYMOMO_COLLECTION_SUBSCRIPTION_KEY",
        help="Ocp-Apim-Subscription-Key.",
    ),
    callback_host: str = typer.Option(
        "https://pymomo.aiforuganda.org",
        "--callback-host",
        "-c",
        help="Provider callback host.",
    ),
    environment: str = typer.Option(
        "sandbox",
        "--environment",
        "-e",
        envvar="PYMOMO_ENVIRONMENT",
        help="Target environment.",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        envvar="PYMOMO_BASE_URL",
        help="Override API base URL.",
    ),
) -> None:
    """Provision a new sandbox API user and API key."""
    config = MomoConfig(environment=environment, base_url=base_url)
    with MomoClient(config) as client:
        provisioner = client.create_sandbox_provisioner(subscription_key)
        result = provisioner.provision(callback_host=callback_host)
        print(json.dumps(result, indent=2))


@sandbox_app.command(name="get-user")
@handle_cli_exceptions
def sandbox_get_user(
    user_id: str = typer.Argument(..., help="The API user UUID."),
    subscription_key: str = typer.Option(
        ...,
        "--subscription-key",
        "-k",
        envvar="PYMOMO_COLLECTION_SUBSCRIPTION_KEY",
        help="Ocp-Apim-Subscription-Key.",
    ),
    environment: str = typer.Option(
        "sandbox",
        "--environment",
        "-e",
        envvar="PYMOMO_ENVIRONMENT",
        help="Target environment.",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        envvar="PYMOMO_BASE_URL",
        help="Override API base URL.",
    ),
) -> None:
    """Get information about a sandbox API user."""
    config = MomoConfig(environment=environment, base_url=base_url)
    with MomoClient(config) as client:
        provisioner = client.create_sandbox_provisioner(subscription_key)
        result = provisioner.get_api_user(user_id)
        print(json.dumps(result.model_dump(by_alias=True, mode="json"), indent=2))


@collection_app.command(name="balance")
@handle_cli_exceptions
def collection_balance(
    subscription_key: str = typer.Option(
        ...,
        "--subscription-key",
        "-k",
        envvar="PYMOMO_COLLECTION_SUBSCRIPTION_KEY",
        help="Collection subscription key.",
    ),
    api_user: str = typer.Option(
        ...,
        "--api-user",
        "-u",
        envvar="PYMOMO_COLLECTION_API_USER",
        help="Collection API user UUID.",
    ),
    api_key: str = typer.Option(
        ...,
        "--api-key",
        "-p",
        envvar="PYMOMO_COLLECTION_API_KEY",
        help="Collection API key.",
    ),
    environment: str = typer.Option(
        "sandbox",
        "--environment",
        "-e",
        envvar="PYMOMO_ENVIRONMENT",
        help="Target environment.",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        envvar="PYMOMO_BASE_URL",
        help="Override API base URL.",
    ),
) -> None:
    """Get the balance of the collection account."""
    config = MomoConfig(
        environment=environment,
        base_url=base_url,
        collection=ProductConfig(
            subscription_key=subscription_key,
            api_user=api_user,
            api_key=api_key,
        ),
    )
    with MomoClient(config) as client:
        balance = client.collection.get_balance()
        print(json.dumps(balance.model_dump(by_alias=True, mode="json"), indent=2))


@collection_app.command(name="request-to-pay")
@handle_cli_exceptions
def collection_request_to_pay(
    msisdn: str = typer.Argument(..., help="The payer MSISDN."),
    amount: str = typer.Argument(..., help="Transaction amount."),
    currency: str = typer.Argument(..., help="ISO currency code."),
    external_id: str = typer.Argument(..., help="External transaction identifier."),
    subscription_key: str = typer.Option(
        ...,
        "--subscription-key",
        "-k",
        envvar="PYMOMO_COLLECTION_SUBSCRIPTION_KEY",
        help="Collection subscription key.",
    ),
    api_user: str = typer.Option(
        ...,
        "--api-user",
        "-u",
        envvar="PYMOMO_COLLECTION_API_USER",
        help="Collection API user UUID.",
    ),
    api_key: str = typer.Option(
        ...,
        "--api-key",
        "-p",
        envvar="PYMOMO_COLLECTION_API_KEY",
        help="Collection API key.",
    ),
    payer_message: str = typer.Option(
        "",
        "--payer-message",
        help="Message to the payer.",
    ),
    payee_note: str = typer.Option(
        "",
        "--payee-note",
        help="Note to the payee.",
    ),
    reference_id: str | None = typer.Option(
        None,
        "--reference-id",
        help="Optional custom UUID reference ID.",
    ),
    environment: str = typer.Option(
        "sandbox",
        "--environment",
        "-e",
        envvar="PYMOMO_ENVIRONMENT",
        help="Target environment.",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        envvar="PYMOMO_BASE_URL",
        help="Override API base URL.",
    ),
) -> None:
    """Initiate a Request to Pay transaction."""
    config = MomoConfig(
        environment=environment,
        base_url=base_url,
        collection=ProductConfig(
            subscription_key=subscription_key,
            api_user=api_user,
            api_key=api_key,
        ),
    )
    with MomoClient(config) as client:
        ref_id = client.collection.request_to_pay(
            amount=amount,
            currency=currency,
            payer_msisdn=msisdn,
            external_id=external_id,
            payer_message=payer_message,
            payee_note=payee_note,
            reference_id=reference_id,
        )
        print(json.dumps({"reference_id": ref_id}, indent=2))


@collection_app.command(name="status")
@handle_cli_exceptions
def collection_status(
    reference_id: str = typer.Argument(
        ..., help="The Request to Pay transaction reference UUID."
    ),
    subscription_key: str = typer.Option(
        ...,
        "--subscription-key",
        "-k",
        envvar="PYMOMO_COLLECTION_SUBSCRIPTION_KEY",
        help="Collection subscription key.",
    ),
    api_user: str = typer.Option(
        ...,
        "--api-user",
        "-u",
        envvar="PYMOMO_COLLECTION_API_USER",
        help="Collection API user UUID.",
    ),
    api_key: str = typer.Option(
        ...,
        "--api-key",
        "-p",
        envvar="PYMOMO_COLLECTION_API_KEY",
        help="Collection API key.",
    ),
    environment: str = typer.Option(
        "sandbox",
        "--environment",
        "-e",
        envvar="PYMOMO_ENVIRONMENT",
        help="Target environment.",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        envvar="PYMOMO_BASE_URL",
        help="Override API base URL.",
    ),
) -> None:
    """Get the status of a Request to Pay transaction."""
    config = MomoConfig(
        environment=environment,
        base_url=base_url,
        collection=ProductConfig(
            subscription_key=subscription_key,
            api_user=api_user,
            api_key=api_key,
        ),
    )
    with MomoClient(config) as client:
        result = client.collection.get_payment_status(reference_id)
        print(json.dumps(result.model_dump(by_alias=True, mode="json"), indent=2))


@disbursement_app.command(name="balance")
@handle_cli_exceptions
def disbursement_balance(
    subscription_key: str = typer.Option(
        ...,
        "--subscription-key",
        "-k",
        envvar="PYMOMO_DISBURSEMENT_SUBSCRIPTION_KEY",
        help="Disbursement subscription key.",
    ),
    api_user: str = typer.Option(
        ...,
        "--api-user",
        "-u",
        envvar="PYMOMO_DISBURSEMENT_API_USER",
        help="Disbursement API user UUID.",
    ),
    api_key: str = typer.Option(
        ...,
        "--api-key",
        "-p",
        envvar="PYMOMO_DISBURSEMENT_API_KEY",
        help="Disbursement API key.",
    ),
    environment: str = typer.Option(
        "sandbox",
        "--environment",
        "-e",
        envvar="PYMOMO_ENVIRONMENT",
        help="Target environment.",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        envvar="PYMOMO_BASE_URL",
        help="Override API base URL.",
    ),
) -> None:
    """Get the balance of the disbursement account."""
    config = MomoConfig(
        environment=environment,
        base_url=base_url,
        disbursement=ProductConfig(
            subscription_key=subscription_key,
            api_user=api_user,
            api_key=api_key,
        ),
    )
    with MomoClient(config) as client:
        balance = client.disbursement.get_balance()
        print(json.dumps(balance.model_dump(by_alias=True, mode="json"), indent=2))


@remittance_app.command(name="balance")
@handle_cli_exceptions
def remittance_balance(
    subscription_key: str = typer.Option(
        ...,
        "--subscription-key",
        "-k",
        envvar="PYMOMO_REMITTANCE_SUBSCRIPTION_KEY",
        help="Remittance subscription key.",
    ),
    api_user: str = typer.Option(
        ...,
        "--api-user",
        "-u",
        envvar="PYMOMO_REMITTANCE_API_USER",
        help="Remittance API user UUID.",
    ),
    api_key: str = typer.Option(
        ...,
        "--api-key",
        "-p",
        envvar="PYMOMO_REMITTANCE_API_KEY",
        help="Remittance API key.",
    ),
    environment: str = typer.Option(
        "sandbox",
        "--environment",
        "-e",
        envvar="PYMOMO_ENVIRONMENT",
        help="Target environment.",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        envvar="PYMOMO_BASE_URL",
        help="Override API base URL.",
    ),
) -> None:
    """Get the balance of the remittance account."""
    config = MomoConfig(
        environment=environment,
        base_url=base_url,
        remittance=ProductConfig(
            subscription_key=subscription_key,
            api_user=api_user,
            api_key=api_key,
        ),
    )
    with MomoClient(config) as client:
        balance = client.remittance.get_balance()
        print(json.dumps(balance.model_dump(by_alias=True, mode="json"), indent=2))


if __name__ == "__main__":
    app()
