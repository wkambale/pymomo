# PyMoMo

PyMoMo is a fully-typed, production-grade Python client library for the MTN Mobile Money (MoMo) Open API. It is designed to be highly secure, reliable, and developer-friendly.

## Supported products and environments

The library provides complete coverage of all MTN MoMo Developer portal products as well as Airtel Money:
- **Collection**: Request payments, withdrawals, balances, and OAuth2 consent tokens from users.
- **Disbursement**: Send transfers, deposits, and refunds to payees.
- **Remittance**: Send international and domestic transfers.
- **Airtel Money**: Initiate Airtel collections, disbursement transfers, status inquiries, and wallet balance checks.
- **Sandbox**: Auto-provision sandbox accounts, API users, and API keys.

It supports both the **sandbox** environment for developer integration testing and all standard MTN **production** environments across African countries (e.g. Ghana, Uganda, Congo, Ivory Coast, Cameroon, Zambia, Benin, Swaziland, Guinea Conakry, South Africa, Liberia).

## Installation

Install PyMoMo using pip:

```bash
pip install pymomo
```

## Quickstart

A ten-line example showing how to initialize a client and get the collection balance:

```python
from pymomo import MomoClient, MomoConfig, ProductConfig

config = MomoConfig(
    environment="sandbox",
    collection=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="your-api-user-uuid",
        api_key="your-api-key",
    ),
)

with MomoClient(config) as client:
    balance = client.collection.get_balance()
    print(f"Balance: {balance.available_balance} {balance.currency}")
```

## Documentation links

- [Quickstart guide](quickstart.md)
- [Authentication configuration](authentication.md)
- [Collection API reference](collection.md)
- [Disbursement API reference](disbursement.md)
- [Remittance API reference](remittance.md)
- [Airtel Money reference](airtel.md)
- [Sandbox provisioning](sandbox.md)
- [Webhook processing](webhooks.md)
- [Asynchronous client support](async.md)
- [Error handling](error-handling.md)
- [Command line interface reference](cli.md)
- [Contributing guide](contributing.md)
