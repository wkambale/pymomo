# Collection

The Collection product allows you to receive payments and withdrawal requests from mobile money subscribers.

## Initializing the collection client

Always manage `PyMomoSDK` with a `with` statement (or call `client.close()`) so HTTP connection pools are released cleanly. For live MTN MoMo One API v2 deployments, pass `base_url=ONE_API_PRODUCTION_BASE_URL` (`https://momoapi.momo.africa`); omitting `base_url` selects `SANDBOX_BASE_URL` in `sandbox` and `PRODUCTION_BASE_URL` (`https://proxy.momoapi.mtn.com`) for named country environments:

```python
from py_momo_sdk import (
    ONE_API_PRODUCTION_BASE_URL,
    ProductConfig,
    PyMomoSDK,
    PyMomoSDKConfig,
)

config = PyMomoSDKConfig(
    environment="sandbox",
    collection=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
        callback_url="https://your-app.example.com/webhooks/mtn",
    ),
)
# For MTN One API v2 live gateways: base_url=ONE_API_PRODUCTION_BASE_URL
_ = ONE_API_PRODUCTION_BASE_URL

with PyMomoSDK(config) as client:
    balance = client.collection.get_balance()
    print(f"Balance: {balance.available_balance} {balance.currency}")
```

## Request to pay

Initiate a request to collect funds from a subscriber. Pass an optional `callback_url` to override the `ProductConfig.callback_url` for a single request, and supply an explicit canonical UUID v4 `reference_id` when you want idempotent retries on transient failures:

```python
with PyMomoSDK(config) as client:
    reference_id = client.collection.request_to_pay(
        amount="1500",
        currency="UGX",
        payer_msisdn="256771234567",
        external_id="invoice-9922",
        payer_message="Invoice payment",
        payee_note="Receipt note",
        # Optional canonical UUID v4; omit to auto-generate
        reference_id="550e8400-e29b-41d4-a716-446655440000",
        # Optional per-request HTTPS webhook override
        callback_url="https://your-app.example.com/webhooks/invoice-9922",
    )
    print(f"Transaction reference: {reference_id}")
```

## Get payment status

Poll the status of a request to pay transaction using its reference ID:

```python
with PyMomoSDK(config) as client:
    result = client.collection.get_payment_status(reference_id)
    print(f"Status: {result.status}")
    if result.is_successful():
        print(f"Financial transaction ID: {result.financial_transaction_id}")
    elif result.is_failed():
        print(f"Failure code: {result.reason_code}, reason: {result.reason}")
```

## Request to withdraw

Initiate a request to withdraw funds from a subscriber wallet (collection v2):

```python
with PyMomoSDK(config) as client:
    reference_id = client.collection.request_to_withdraw(
        amount="50.00",
        currency="EUR",
        payer_msisdn="256771234567",
        external_id="withdrawal-1002",
        payer_message="Withdraw approval",
        payee_note="Agent payout",
        reference_id="550e8400-e29b-41d4-a716-446655440000",
        callback_url="https://your-app.example.com/webhooks/withdraw-1002",
    )
    print(f"Withdraw reference: {reference_id}")
```

## Get withdraw status

Check the status of a request to withdraw transaction:

```python
with PyMomoSDK(config) as client:
    result = client.collection.get_withdraw_status(reference_id)
    print(f"Withdrawal status: {result.status}")
```

## Get account balance

Retrieve the collection account balance:

```python
with PyMomoSDK(config) as client:
    balance = client.collection.get_balance()
    print(f"Available balance: {balance.available_balance} {balance.currency}")
```

## Get account balance for currency

Retrieve the account balance for a specific ISO currency code:

```python
with PyMomoSDK(config) as client:
    balance = client.collection.get_balance_for_currency("UGX")
    print(f"Balance: {balance.available_balance} {balance.currency}")
```

## Check if account holder is active

Validate whether a subscriber account exists and is active:

```python
with PyMomoSDK(config) as client:
    is_active = client.collection.is_account_holder_active(
        account_holder_id="256771234567",
        account_holder_id_type="msisdn",
    )
    print(f"Subscriber active: {is_active}")
```

## Get basic user info

Query the basic registration profile of a subscriber:

```python
with PyMomoSDK(config) as client:
    info = client.collection.get_basic_user_info("256771234567")
    print(f"Name: {info.name}")
    print(f"Locale: {info.locale}")
```

## Backchannel authorize

Initiate a CIBA backchannel authorization request (`access_type` must be `"online"` or `"offline"`):

```python
with PyMomoSDK(config) as client:
    auth_response = client.collection.bc_authorize(
        login_hint="256771234567",
        scope="profile",
        access_type="offline",
        callback_url="https://your-app.example.com/webhooks/ciba",
    )
    print(f"Auth request ID: {auth_response.auth_req_id}")
    print(f"Expires in: {auth_response.expires_in} seconds")
```

## Create or refresh OAuth2 token

Exchange the `auth_req_id` returned by `bc_authorize` for a user OAuth2 token, or refresh an existing token with `grant_type="refresh_token"`:

```python
with PyMomoSDK(config) as client:
    oauth_token = client.collection.create_oauth2_token(
        auth_req_id=auth_response.auth_req_id,
    )
    print(f"Token type: {oauth_token.token_type}")
    print(f"Expires in: {oauth_token.expires_in} seconds")

    if oauth_token.refresh_token:
        refreshed = client.collection.create_oauth2_token(
            grant_type="refresh_token",
            refresh_token=oauth_token.refresh_token,
        )
        print(f"Refreshed expires in: {refreshed.expires_in} seconds")
```

## Get basic user info by reference

Retrieve a user profile using the reference ID of a consent query:

```python
with PyMomoSDK(config) as client:
    user_info = client.collection.get_basic_user_info_by_reference(
        "550e8400-e29b-41d4-a716-446655440000"
    )
    print(f"Name: {user_info.name}")
    print(f"Gender: {user_info.gender}")
```

## Get user info with OAuth2 consent

Retrieve consented subscriber KYC profile details using the user `access_token` returned by `create_oauth2_token()` (`GET /collection/oauth2/v1_0/userinfo`):

```python
with PyMomoSDK(config) as client:
    consented_profile = client.collection.get_user_info_with_consent(
        oauth_token.access_token
    )
    print(f"Sub: {consented_profile.sub}, Name: {consented_profile.name}")
```

## Send delivery notification

Send an additional SMS or push delivery notification for an existing Request to Pay (`POST /collection/v1_0/requesttopay/{referenceId}/deliverynotification`). UTF-8 messages (including French and accented local languages) are serialized in the JSON body:

```python
with PyMomoSDK(config) as client:
    client.collection.send_delivery_notification(
        reference_id="550e8400-e29b-41d4-a716-446655440000",
        notification_message="Paiement reçu, merci pour votre commande",
        language="fr",
    )
```

## PreApproval lifecycle

Create, inspect, and cancel recurring or pre-authorized subscriber mandates (`POST`, `GET`, and `DELETE /collection/v2_0/preapproval`):

```python
with PyMomoSDK(config) as client:
    preapproval_id = client.collection.create_preapproval(
        payer_msisdn="256771234567",
        payer_currency="UGX",
        validity_time=3600,
        payer_message="Authorize monthly subscription",
        party_id_type="MSISDN",
    )
    preapproval = client.collection.get_preapproval_status(preapproval_id)
    print(f"PreApproval status: {preapproval.status}")

    client.collection.cancel_preapproval(preapproval_id)
```

Next step: [Explore Disbursement](disbursement.md).
