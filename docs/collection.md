# Collection

The Collection product allows you to receive payments and withdrawal requests from mobile money subscribers.

## Initializing collection client

Access collection methods via the `.collection` property of a `MomoClient` instance:

```python
from pymomo import MomoClient, MomoConfig, ProductConfig

config = MomoConfig(
    environment="sandbox",
    collection=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
    ),
)

client = MomoClient(config)
collection_client = client.collection
```


## Request to pay

Initiate a request to collect funds from a subscriber.

```python
reference_id = client.collection.request_to_pay(
    amount="1500.00",
    currency="UGX",
    payer_msisdn="256771234567",
    external_id="invoice-9922",
    payer_message="Invoice payment",
    payee_note="Receipt note",
    # Optional canonical UUID v4; omit to auto-generate
    reference_id="550e8400-e29b-41d4-a716-446655440000",
)
print(f"Transaction Reference: {reference_id}")
```

## Get payment status

Poll the status of a request to pay transaction using its reference ID.

```python
result = client.collection.get_payment_status(reference_id)
print(f"Status: {result.status}")
if result.is_successful():
    print(f"Financial Transaction ID: {result.financial_transaction_id}")
```


## Request to withdraw

Initiate a request to withdraw funds from a subscriber's wallet (collection v2).

```python
reference_id = client.collection.request_to_withdraw(
    amount="50.00",
    currency="EUR",
    payer_msisdn="256771234567",
    external_id="withdrawal-1002",
    payer_message="Withdraw approval",
    payee_note="Agent payout",
    # Optional canonical UUID v4; omit to auto-generate
    reference_id="550e8400-e29b-41d4-a716-446655440000",
)
print(f"Withdraw Reference: {reference_id}")
```

## Get withdraw status

Check the status of a request to withdraw transaction.

```python
result = client.collection.get_withdraw_status(reference_id)
print(f"Withdrawal status: {result.status}")
```


## Get account balance

Retrieve the collection account balance.

```python
balance = client.collection.get_balance()
print(f"Available balance: {balance.available_balance} {balance.currency}")
```

## Get account balance for currency

Get the account balance for a specific currency code.

```python
balance = client.collection.get_balance_for_currency("UGX")
print(f"Balance: {balance.available_balance} {balance.currency}")
```


## Check if account holder is active

Validate whether a subscriber account exists and is active.

```python
is_active = client.collection.is_account_holder_active(
    account_holder_id="256771234567",
    account_holder_id_type="msisdn",
)
print(f"Subscriber active: {is_active}")
```

## Get basic user info

Query the basic user registration info of a subscriber.

```python
info = client.collection.get_basic_user_info("256771234567")
print(f"Name: {info.name}")
print(f"Locale: {info.locale}")
```


## Backchannel authorize

Initiate a CIBA backchannel authorization request.

```python
auth_response = client.collection.bc_authorize(
    login_hint="256771234567",
    scope="profile",
)
print(f"Auth request ID: {auth_response.auth_req_id}")
print(f"Expires in: {auth_response.expires_in} seconds")
```

## Create OAuth2 token

Exchange the `auth_req_id` returned by `bc_authorize` for a user OAuth2 token.

```python
oauth_token = client.collection.create_oauth2_token(
    auth_req_id=auth_response.auth_req_id,
)
print(f"Token type: {oauth_token.token_type}")
print(f"Expires in: {oauth_token.expires_in} seconds")
```

## Get basic user info by reference

Retrieve a user's profile details using the reference ID of a consent query.

```python
user_info = client.collection.get_basic_user_info_by_reference(
    "550e8400-e29b-41d4-a716-446655440000"
)
print(f"Name: {user_info.name}")
print(f"Gender: {user_info.gender}")
```
