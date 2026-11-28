from __future__ import annotations

import ast
import importlib
import inspect
import pathlib
import re
from typing import Any

import pytest

import py_momo_sdk
from py_momo_sdk import (
    AirtelClient,
    AirtelConfig,
    AirtelMoneyProvider,
    AsyncAirtelClient,
    AsyncAirtelMoneyProvider,
    AsyncFlutterwaveClient,
    AsyncFlutterwaveProvider,
    AsyncMpesaClient,
    AsyncMpesaProvider,
    AsyncMtnMomoProvider,
    AsyncOrangeMoneyClient,
    AsyncOrangeMoneyProvider,
    AsyncPaymentProvider,
    AsyncPaymentRouter,
    AsyncPaystackClient,
    AsyncPaystackProvider,
    AsyncPyMomoSDK,
    AsyncSandboxProvisioner,
    AsyncWaveClient,
    AsyncWaveProvider,
    BadRequestError,
    FlutterwaveClient,
    FlutterwaveConfig,
    FlutterwaveProvider,
    MpesaClient,
    MpesaConfig,
    MpesaProvider,
    MtnMomoProvider,
    OrangeMoneyClient,
    OrangeMoneyConfig,
    OrangeMoneyProvider,
    PaymentProvider,
    PaymentRouter,
    PaystackClient,
    PaystackConfig,
    PaystackProvider,
    ProductConfig,
    PyMomoSDK,
    PyMomoSDKConfig,
    SandboxProvisioner,
    WaveClient,
    WaveConfig,
    WaveProvider,
)
from py_momo_sdk._async.airtel.auth import AsyncAirtelAuth
from py_momo_sdk._async.airtel.products.collection import AsyncAirtelCollection
from py_momo_sdk._async.airtel.products.disbursement import AsyncAirtelDisbursement
from py_momo_sdk._async.http import AsyncHttpClient
from py_momo_sdk._async.products.base import AsyncBaseProduct
from py_momo_sdk._async.products.collection import Collection as AsyncMtnCollection
from py_momo_sdk._async.products.disbursement import (
    Disbursement as AsyncMtnDisbursement,
)
from py_momo_sdk._async.products.remittance import Remittance as AsyncMtnRemittance
from py_momo_sdk.airtel.auth import AirtelAuth
from py_momo_sdk.airtel.models import AirtelTransactionRequest
from py_momo_sdk.airtel.products.collection import Collection as SyncAirtelCollection
from py_momo_sdk.airtel.products.disbursement import (
    Disbursement as SyncAirtelDisbursement,
)
from py_momo_sdk.http import HttpClient
from py_momo_sdk.products.base import BaseProduct as SyncBaseProduct
from py_momo_sdk.products.collection import Collection as SyncMtnCollection
from py_momo_sdk.products.disbursement import Disbursement as SyncMtnDisbursement
from py_momo_sdk.products.remittance import Remittance as SyncMtnRemittance
from py_momo_sdk.providers.airtel import _AIRTEL_CAPABILITIES
from py_momo_sdk.providers.flutterwave import _FLUTTERWAVE_CAPABILITIES
from py_momo_sdk.providers.mpesa import _MPESA_CAPABILITIES
from py_momo_sdk.providers.mtn import _MTN_CAPABILITIES
from py_momo_sdk.providers.orange import _ORANGE_CAPABILITIES
from py_momo_sdk.providers.paystack import _PAYSTACK_CAPABILITIES, _to_minor_units
from py_momo_sdk.providers.router import (
    _PAYSTACK_TRANSFER_REF_RE,
    _derive_candidate_reference_id,
)
from py_momo_sdk.providers.wave import _WAVE_CAPABILITIES
from py_momo_sdk.utils import (
    _CARRIER_PREFIX_MAP,
    validate_airtel_reference_id,
    validate_reference_id,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

SYNC_ASYNC_CLASS_PAIRS: tuple[tuple[type[Any], type[Any]], ...] = (
    (PyMomoSDK, AsyncPyMomoSDK),
    (HttpClient, AsyncHttpClient),
    (SandboxProvisioner, AsyncSandboxProvisioner),
    (SyncBaseProduct, AsyncBaseProduct),
    (SyncMtnCollection, AsyncMtnCollection),
    (SyncMtnDisbursement, AsyncMtnDisbursement),
    (SyncMtnRemittance, AsyncMtnRemittance),
    (AirtelClient, AsyncAirtelClient),
    (AirtelAuth, AsyncAirtelAuth),
    (SyncAirtelCollection, AsyncAirtelCollection),
    (SyncAirtelDisbursement, AsyncAirtelDisbursement),
    (PaymentProvider, AsyncPaymentProvider),
    (PaymentRouter, AsyncPaymentRouter),
    (MtnMomoProvider, AsyncMtnMomoProvider),
    (AirtelMoneyProvider, AsyncAirtelMoneyProvider),
    (WaveClient, AsyncWaveClient),
    (WaveProvider, AsyncWaveProvider),
    (MpesaClient, AsyncMpesaClient),
    (MpesaProvider, AsyncMpesaProvider),
    (PaystackClient, AsyncPaystackClient),
    (PaystackProvider, AsyncPaystackProvider),
    (FlutterwaveClient, AsyncFlutterwaveClient),
    (FlutterwaveProvider, AsyncFlutterwaveProvider),
    (OrangeMoneyClient, AsyncOrangeMoneyClient),
    (OrangeMoneyProvider, AsyncOrangeMoneyProvider),
)


def _public_members(cls: type[Any]) -> set[str]:
    return {
        name
        for name in dir(cls)
        if not name.startswith("_") and not name.startswith("__")
    }


def _param_shape(callable_obj: Any) -> list[tuple[str, Any, Any]]:
    sig = inspect.signature(callable_obj)
    return [
        (param.name, param.kind, param.default)
        for name, param in sig.parameters.items()
        if name != "self"
    ]


def test_sync_async_public_class_signature_parity() -> None:
    """Every sync/async public class pair must expose identical public methods and signatures."""
    assert len(SYNC_ASYNC_CLASS_PAIRS) >= 21
    for sync_cls, async_cls in SYNC_ASYNC_CLASS_PAIRS:
        sync_members = _public_members(sync_cls)
        async_members = _public_members(async_cls)
        # Async classes with `close()` may additionally expose `aclose()` as an async alias
        comparable_async_members = (
            async_members - {"aclose"} if "close" in sync_members else async_members
        )
        assert sync_members == comparable_async_members, (
            f"Public member mismatch between {sync_cls.__name__} and {async_cls.__name__}: "
            f"sync_only={sync_members - comparable_async_members}, "
            f"async_only={comparable_async_members - sync_members}"
        )

        init_sync = _param_shape(sync_cls.__init__)
        init_async = _param_shape(async_cls.__init__)
        assert init_sync == init_async, (
            f"__init__ parameter mismatch between {sync_cls.__name__} and {async_cls.__name__}: "
            f"{init_sync} != {init_async}"
        )

        for member_name in sorted(sync_members):
            sync_attr = inspect.getattr_static(sync_cls, member_name)
            async_attr = inspect.getattr_static(async_cls, member_name)
            if isinstance(sync_attr, property) or isinstance(async_attr, property):
                assert isinstance(sync_attr, property) and isinstance(
                    async_attr, property
                ), f"Property mismatch on {sync_cls.__name__}.{member_name}"
                continue
            sync_fn = getattr(sync_cls, member_name)
            async_fn = getattr(async_cls, member_name)
            assert callable(sync_fn) and callable(async_fn)
            assert _param_shape(sync_fn) == _param_shape(async_fn), (
                f"Signature mismatch on {sync_cls.__name__}.{member_name} vs "
                f"{async_cls.__name__}.{member_name}"
            )


def test_carrier_prefix_map_aligns_with_provider_capabilities() -> None:
    """Every built-in provider target in _CARRIER_PREFIX_MAP must support that country's currency."""
    country_to_currency = {
        "UG": "UGX",
        "GH": "GHS",
        "KE": "KES",
        "TZ": "TZS",
        "RW": "RWF",
        "ZM": "ZMW",
        "MW": "MWK",
        "CD": "CDF",
        "ET": "ETB",
        "CM": "XAF",
        "NG": "NGN",
        "ZA": "ZAR",
        "CI": "XOF",
        "SN": "XOF",
        "BJ": "XOF",
        "CG": "XAF",
        "LR": "LRD",
        "GN": "GNF",
        "SZ": "SZL",
    }
    builtin_capabilities = {
        "mtn_momo": set(_MTN_CAPABILITIES.currencies),
        "airtel_money": set(_AIRTEL_CAPABILITIES.currencies),
        "orange_money": set(_ORANGE_CAPABILITIES.currencies),
        "mpesa": set(_MPESA_CAPABILITIES.currencies),
        "wave": set(_WAVE_CAPABILITIES.currencies),
        "paystack": set(_PAYSTACK_CAPABILITIES.currencies),
        "flutterwave": set(_FLUTTERWAVE_CAPABILITIES.currencies),
    }

    for prefix, country, provider_id in _CARRIER_PREFIX_MAP:
        assert (
            country in country_to_currency
        ), f"Unmapped country {country!r} for prefix {prefix}"
        if provider_id == "moov_money":
            # External plugin provider ID detected by MSISDN helper
            continue
        if provider_id == "mpesa" and country != "KE":
            # Built-in MpesaProvider targets Safaricom Kenya Daraja (KES);
            # Vodacom M-Pesa countries (TZ, CD, ET) use custom plugins.
            continue
        assert provider_id in builtin_capabilities, f"Unknown provider {provider_id!r}"
        expected_currency = country_to_currency[country]
        assert expected_currency in builtin_capabilities[provider_id], (
            f"Prefix {prefix} routes ({country}, {provider_id}), "
            f"but {expected_currency} is missing from {provider_id} capabilities"
        )


def test_zero_decimal_fractional_amount_rejected_across_all_seven_providers() -> None:
    """Every built-in rail must reject fractional decimal strings on zero-decimal currencies."""
    # 1. MTN MoMo
    with (
        PyMomoSDK(
            PyMomoSDKConfig(
                environment="sandbox",
                collection=ProductConfig(
                    subscription_key="sub",
                    api_user="550e8400-e29b-41d4-a716-446655440000",
                    api_key="key",
                ),
            )
        ) as mtn_client,
        pytest.raises(ValueError, match="fractional"),
    ):
        mtn_client.collection.request_to_pay(
            amount="100.50",
            currency="UGX",
            payer_msisdn="256771234567",
            external_id="inv-1",
        )

    # 2. Airtel Money (both collection and disbursement)
    with pytest.raises(ValueError, match="fractional"):
        AirtelTransactionRequest(
            amount="100.50", country="UG", currency="UGX", id="ref-1"
        )
    with (
        AirtelClient(
            AirtelConfig(
                client_id="cid",
                client_secret="csec",
                country="RW",
                currency="RWF",
                pin="1234",
            )
        ) as airtel_client,
        pytest.raises(ValueError, match="fractional"),
    ):
        airtel_client.disbursement.transfer(
            amount="100.50", payee_msisdn="250721234567"
        )

    # 3. Wave
    with (
        WaveClient(
            WaveConfig(
                api_key="wave_sn_test_key",
                success_url="https://example.com/ok",
                error_url="https://example.com/err",
            )
        ) as wave_client,
        pytest.raises(ValueError, match="fractional"),
    ):
        wave_client.create_checkout_session(amount="100.50", currency="XOF")

    # 4. Safaricom M-Pesa (Daraja KES)
    with (
        MpesaClient(
            MpesaConfig(
                consumer_key="ck",
                consumer_secret="cs",
                short_code="174379",
                passkey="pk",
                callback_url="https://example.com/cb",
            )
        ) as mpesa_client,
        pytest.raises(ValueError, match="whole integer"),
    ):
        mpesa_client.stk_push(amount="100.50", phone_number="254712345678")

    # 5. Orange Money (XOF, GNF, MGA)
    with OrangeMoneyClient(
        OrangeMoneyConfig(
            client_id="oid",
            client_secret="osec",
            merchant_key="omk",
            return_url="https://example.com/ret",
            cancel_url="https://example.com/can",
            notif_url="https://example.com/not",
        )
    ) as orange_client:
        for zero_curr in ("XOF", "GNF", "MGA"):
            with pytest.raises(ValueError, match="whole-integer"):
                orange_client.create_web_payment(amount="100.50", currency=zero_curr)

    # 6. Paystack (_to_minor_units preserves *100 integer scaling while rejecting fractional zero-decimal)
    assert _to_minor_units("100", "XOF") == 10000
    assert _to_minor_units("100", "RWF") == 10000
    for zero_curr in ("XOF", "XAF", "RWF", "UGX"):
        with pytest.raises(ValueError, match="does not support fractional"):
            _to_minor_units("100.50", zero_curr)
    with (
        PaystackClient(PaystackConfig(secret_key="sk_test_123")) as ps_client,
        pytest.raises(ValueError, match="does not support fractional"),
    ):
        ps_client.initialize_transaction(
            email="buyer@example.com", amount="100.50", currency="RWF"
        )

    # 7. Flutterwave
    with (
        FlutterwaveClient(
            FlutterwaveConfig(
                secret_key="FLWSECK_TEST-123",
                default_customer_email="buyer@example.com",
            )
        ) as flw_client,
        pytest.raises(ValueError, match="fractional"),
    ):
        flw_client.create_payment(
            amount="100.50",
            currency="UGX",
            phone_number="256771234567",
        )


def test_oauth_product_requests_always_wire_token_refresher_ast() -> None:
    """Every OAuth bearer _http.request call must pass token_cache and token_refresher."""
    oauth_files = [
        *sorted((REPO_ROOT / "py_momo_sdk" / "products").glob("*.py")),
        *sorted((REPO_ROOT / "py_momo_sdk" / "_async" / "products").glob("*.py")),
        REPO_ROOT / "py_momo_sdk" / "providers" / "mpesa.py",
        REPO_ROOT / "py_momo_sdk" / "providers" / "orange.py",
    ]
    exempt_methods = {
        "_fetch_token",  # Basic-auth token acquisition helper on BaseProduct
        "_get_token",  # Basic-auth token acquisition endpoint itself
        "create_oauth2_token",  # Basic-auth CIBA user token grant endpoint
        "get_user_info_with_consent",  # Caller-supplied end-user OAuth2 Bearer token
    }

    checked_calls = 0
    for file_path in oauth_files:
        if file_path.name == "__init__.py":
            continue
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in exempt_methods:
                continue
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "request"
                    and isinstance(sub.func.value, ast.Attribute)
                    and sub.func.value.attr == "_http"
                ):
                    kw_names = {kw.arg for kw in sub.keywords if kw.arg is not None}
                    assert "token_cache" in kw_names, (
                        f"{file_path.relative_to(REPO_ROOT)}:{sub.lineno} "
                        f"({node.name}) missing token_cache on self._http.request()"
                    )
                    assert "token_refresher" in kw_names, (
                        f"{file_path.relative_to(REPO_ROOT)}:{sub.lineno} "
                        f"({node.name}) missing token_refresher on self._http.request()"
                    )
                    checked_calls += 1

    assert checked_calls >= 36


def test_config_repr_and_exception_body_secret_redaction_invariants() -> None:
    """No config/auth repr or error response_body may leak credentials or reusable charge tokens."""
    sentinel_pairs: list[tuple[Any, tuple[str, ...]]] = [
        (
            ProductConfig(
                subscription_key="SENTINEL_MTN_SUB",
                api_user="SENTINEL_MTN_USER",
                api_key="SENTINEL_MTN_KEY",
            ),
            ("SENTINEL_MTN_SUB", "SENTINEL_MTN_USER", "SENTINEL_MTN_KEY"),
        ),
        (
            PyMomoSDKConfig(
                environment="sandbox",
                collection=ProductConfig(
                    subscription_key="SENTINEL_CFG_SUB",
                    api_user="SENTINEL_CFG_USER",
                    api_key="SENTINEL_CFG_KEY",
                ),
            ),
            ("SENTINEL_CFG_SUB", "SENTINEL_CFG_USER", "SENTINEL_CFG_KEY"),
        ),
        (
            AirtelConfig(
                client_id="SENTINEL_AIRTEL_CID",
                client_secret="SENTINEL_AIRTEL_CSEC",
                country="UG",
                currency="UGX",
                pin="9876",
                webhook_secret="SENTINEL_AIRTEL_WHSEC",
            ),
            (
                "SENTINEL_AIRTEL_CID",
                "SENTINEL_AIRTEL_CSEC",
                "9876",
                "SENTINEL_AIRTEL_WHSEC",
            ),
        ),
        (
            AirtelAuth(
                client_id="SENTINEL_AUTH_CID",
                client_secret="SENTINEL_AUTH_CSEC",
                base_url="https://openapiuat.airtel.africa",
            ),
            ("SENTINEL_AUTH_CID", "SENTINEL_AUTH_CSEC"),
        ),
        (
            AsyncAirtelAuth(
                client_id="SENTINEL_AAUTH_CID",
                client_secret="SENTINEL_AAUTH_CSEC",
                base_url="https://openapiuat.airtel.africa",
            ),
            ("SENTINEL_AAUTH_CID", "SENTINEL_AAUTH_CSEC"),
        ),
        (
            WaveConfig(
                api_key="SENTINEL_WAVE_KEY",
                webhook_secret="SENTINEL_WAVE_WH",
                signing_secret="SENTINEL_WAVE_SIGN",
            ),
            ("SENTINEL_WAVE_KEY", "SENTINEL_WAVE_WH", "SENTINEL_WAVE_SIGN"),
        ),
        (
            MpesaConfig(
                consumer_key="SENTINEL_MPESA_CK",
                consumer_secret="SENTINEL_MPESA_CS",
                short_code="174379",
                passkey="SENTINEL_MPESA_PK",
                security_credential="SENTINEL_MPESA_SC",
            ),
            (
                "SENTINEL_MPESA_CK",
                "SENTINEL_MPESA_CS",
                "SENTINEL_MPESA_PK",
                "SENTINEL_MPESA_SC",
            ),
        ),
        (
            PaystackConfig(secret_key="sk_test_SENTINEL_PS_KEY"),
            ("sk_test_SENTINEL_PS_KEY",),
        ),
        (
            FlutterwaveConfig(
                secret_key="FLWSECK_TEST_SENTINEL_FLW",
                webhook_hash="SENTINEL_FLW_HASH",
            ),
            ("FLWSECK_TEST_SENTINEL_FLW", "SENTINEL_FLW_HASH"),
        ),
        (
            OrangeMoneyConfig(
                client_id="SENTINEL_OM_CID",
                client_secret="SENTINEL_OM_CSEC",
                merchant_key="SENTINEL_OM_MKEY",
            ),
            ("SENTINEL_OM_CID", "SENTINEL_OM_CSEC", "SENTINEL_OM_MKEY"),
        ),
    ]

    for obj, secrets in sentinel_pairs:
        for rendered in (repr(obj), str(obj)):
            for secret in secrets:
                assert (
                    secret not in rendered
                ), f"{type(obj).__name__} leaked {secret!r} in {rendered!r}"

    sensitive_payload = {
        "access_token": "tok-1",
        "refresh_token": "rtok-1",
        "api_key": "akey-1",
        "client_secret": "csec-1",
        "consumer_secret": "consec-1",
        "subscription_key": "subkey-1",
        "signing_secret": "sigsec-1",
        "webhook_secret": "whsec-1",
        "verif_hash": "vhash-1",
        "passkey": "pkey-1",
        "security_credential": "seccred-1",
        "merchant_key": "mkey-1",
        "pay_token": "ptok-1",
        "notif_token": "ntok-1",
        "authorization_code": "AUTH_reusable_ps_code",
        "encryption_key": "FLWSECK_ENC_key",
        "private_key": "priv-1",
        "nested": {
            "authorizationCode": "AUTH_camel_code",
            "encryptionKey": "FLW_camel_enc",
            "pin": "1234",
        },
    }
    err = BadRequestError("Upstream error", response_body=sensitive_payload)
    for k, v in err.response_body.items():
        if k == "nested":
            assert v == {
                "authorizationCode": "<redacted>",
                "encryptionKey": "<redacted>",
                "pin": "<redacted>",
            }
        else:
            assert v == "<redacted>", f"Key {k!r} was not redacted in response_body"


def test_router_cross_provider_reference_adaptation_invariants() -> None:
    """Router reference adaptation must satisfy every target rail's format rules deterministically."""
    sample_inputs = (
        "550e8400-e29b-41d4-a716-446655440000",
        "ORD-2026-01",
        "merchant_ref_with_more_than_thirty_characters_2026_0001",
        "x" * 80,
    )
    for raw_ref in sample_inputs:
        om_ref = _derive_candidate_reference_id(
            raw_ref, provider_name="orange_money", operation="collection"
        )
        assert om_ref is not None and len(om_ref) <= 30
        assert om_ref == _derive_candidate_reference_id(
            raw_ref, provider_name="orange_money", operation="collection"
        )

        mtn_ref = _derive_candidate_reference_id(
            raw_ref, provider_name="mtn_momo", operation="collection"
        )
        assert mtn_ref is not None
        validate_reference_id(mtn_ref)

        ps_ref = _derive_candidate_reference_id(
            raw_ref, provider_name="paystack", operation="disbursement"
        )
        assert ps_ref is not None and _PAYSTACK_TRANSFER_REF_RE.fullmatch(ps_ref)

        airtel_ref = _derive_candidate_reference_id(
            raw_ref, provider_name="airtel_money", operation="collection"
        )
        assert airtel_ref is not None
        validate_airtel_reference_id(airtel_ref)


def test_markdown_python_code_blocks_parse_and_import_valid_exports() -> None:
    """Every Python code snippet in README.md and docs/*.md must parse and import real SDK symbols."""
    block_re = re.compile(r"```python\n(.*?)```", re.DOTALL)
    md_files = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").glob("*.md"))]
    parsed_blocks = 0

    for md_path in md_files:
        content = md_path.read_text(encoding="utf-8")
        for idx, match in enumerate(block_re.finditer(content), 1):
            tree = ast.parse(
                match.group(1),
                filename=f"{md_path.relative_to(REPO_ROOT)}#block{idx}",
            )
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module
                    and (
                        node.module == "py_momo_sdk"
                        or node.module.startswith("py_momo_sdk.")
                    )
                ):
                    mod = importlib.import_module(node.module)
                    for alias in node.names:
                        assert hasattr(mod, alias.name), (
                            f"{md_path.relative_to(REPO_ROOT)}#block{idx} imports "
                            f"non-existent {alias.name!r} from {node.module!r}"
                        )
            parsed_blocks += 1

    assert parsed_blocks >= 70
    assert hasattr(py_momo_sdk, "__version__")
