from __future__ import annotations

import pytest

from py_momo_sdk.config import ProductConfig, PyMomoSDKConfig


def test_product_config_repr_redaction() -> None:
    """Verify that ProductConfig repr and str redact api_user, subscription_key, and api_key."""
    config = ProductConfig(
        subscription_key="secret-sub-key",
        api_user="test-user-id",
        api_key="secret-api-key",
    )
    for rendered in (repr(config), str(config)):
        assert "test-user-id" not in rendered
        assert "secret-sub-key" not in rendered
        assert "secret-api-key" not in rendered
        assert "api_user=<redacted>" in rendered
        assert "api_key=<redacted>" in rendered
        assert "subscription_key=<redacted>" in rendered


def test_momo_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that PyMomoSDKConfig.from_env reads environment variables correctly."""
    monkeypatch.setenv("PY_MOMO_SDK_ENVIRONMENT", "mtnuganda")
    monkeypatch.setenv("PY_MOMO_SDK_BASE_URL", "https://custom.momo.com")
    monkeypatch.setenv("PY_MOMO_SDK_TIMEOUT", "45.0")
    monkeypatch.setenv("PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY", "coll-sub")
    monkeypatch.setenv("PY_MOMO_SDK_COLLECTION_API_USER", "coll-user")
    monkeypatch.setenv("PY_MOMO_SDK_COLLECTION_API_KEY", "coll-key")

    config = PyMomoSDKConfig.from_env()
    assert config.environment == "mtnuganda"
    assert config.base_url == "https://custom.momo.com"
    assert config.timeout == 45.0
    assert config.collection is not None
    assert config.collection.subscription_key == "coll-sub"
    assert config.collection.api_user == "coll-user"
    assert config.collection.api_key == "coll-key"
    assert config.disbursement is None
    assert config.remittance is None


def test_config_validation_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify timeout, callback_url, environment, and AirtelConfig validations."""
    from py_momo_sdk.airtel.config import AirtelConfig
    from py_momo_sdk.exceptions import MissingCredentialsError

    # Invalid timeouts
    for bad_timeout in (0, -5.0, float("inf"), float("nan"), True):
        with pytest.raises(
            (TypeError, ValueError), match="Timeout must be a positive finite"
        ):
            PyMomoSDKConfig(timeout=bad_timeout)
        with pytest.raises(
            (TypeError, ValueError), match="Timeout must be a positive finite"
        ):
            AirtelConfig(
                client_id="cid",
                client_secret="sec",
                country="UG",
                currency="UGX",
                timeout=bad_timeout,
            )

    # Non-HTTPS callback_url rejected; localhost allowed
    with pytest.raises(ValueError, match="Callback URL must use HTTPS"):
        ProductConfig(
            subscription_key="sub",
            api_user="user",
            api_key="key",
            callback_url="http://example.com/webhook",
        )
    ProductConfig(
        subscription_key="sub",
        api_user="user",
        api_key="key",
        callback_url="http://localhost:8080/webhook",
    )

    # Control chars rejected in headers/environment
    with pytest.raises(ValueError, match="Environment"):
        PyMomoSDKConfig(environment="sandbox\r\nX-Injected: 1")
    with pytest.raises(ValueError, match="control characters"):
        ProductConfig(subscription_key="sub\r\n", api_user="user", api_key="key")

    # Airtel country and currency validation
    with pytest.raises(ValueError, match="Country"):
        AirtelConfig(
            client_id="cid", client_secret="sec", country="UGA", currency="UGX"
        )
    with pytest.raises(ValueError, match="ISO 4217"):
        AirtelConfig(client_id="cid", client_secret="sec", country="UG", currency="U")

    # Partial environment credentials and invalid PY_MOMO_SDK_TIMEOUT rejected
    monkeypatch.setenv("PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY", "only-sub")
    with pytest.raises(MissingCredentialsError, match="Incomplete collection"):
        PyMomoSDKConfig.from_env()
    monkeypatch.delenv("PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY", raising=False)

    monkeypatch.setenv("PY_MOMO_SDK_TIMEOUT", "-10")
    with pytest.raises(ValueError, match="PY_MOMO_SDK_TIMEOUT"):
        PyMomoSDKConfig.from_env()
    monkeypatch.delenv("PY_MOMO_SDK_TIMEOUT", raising=False)

    # Empty/blank ProductConfig fields, non-int max_retries, inf retry_backoff, bad base_url rejected
    for kwargs in (
        {"subscription_key": "", "api_user": "user", "api_key": "key"},
        {"subscription_key": "   ", "api_user": "user", "api_key": "key"},
        {"subscription_key": "sub", "api_user": "", "api_key": "key"},
        {"subscription_key": "sub", "api_user": "user", "api_key": ""},
    ):
        with pytest.raises(ValueError, match="non-empty string"):
            ProductConfig(**kwargs)

    with pytest.raises((TypeError, ValueError), match="max_retries"):
        PyMomoSDKConfig(max_retries=1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="retry_backoff"):
        PyMomoSDKConfig(retry_backoff=float("inf"))

    from py_momo_sdk.exceptions import PyMomoSDKError

    with pytest.raises(PyMomoSDKError, match="HTTPS"):
        PyMomoSDKConfig(base_url="http://insecure.example.com")
