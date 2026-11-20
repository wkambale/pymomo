from __future__ import annotations

import os

from py_momo_sdk.config import ProductConfig, PyMomoSDKConfig


def test_product_config_repr_redaction() -> None:
    """Verify that ProductConfig repr redacts subscription key and API key."""
    config = ProductConfig(
        subscription_key="secret-sub-key",
        api_user="test-user-id",
        api_key="secret-api-key",
    )
    repr_str = repr(config)
    assert "test-user-id" in repr_str
    assert "secret-sub-key" not in repr_str
    assert "secret-api-key" not in repr_str
    assert "api_key=<redacted>" in repr_str
    assert "subscription_key=<redacted>" in repr_str


def test_momo_config_from_env() -> None:
    """Verify that PyMomoSDKConfig.from_env reads environment variables correctly."""
    os.environ["PY_MOMO_SDK_ENVIRONMENT"] = "mtnuganda"
    os.environ["PY_MOMO_SDK_BASE_URL"] = "https://custom.momo.com"
    os.environ["PY_MOMO_SDK_TIMEOUT"] = "45.0"
    os.environ["PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY"] = "coll-sub"
    os.environ["PY_MOMO_SDK_COLLECTION_API_USER"] = "coll-user"
    os.environ["PY_MOMO_SDK_COLLECTION_API_KEY"] = "coll-key"

    try:
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
    finally:
        # Clean up environment variables
        for var in [
            "PY_MOMO_SDK_ENVIRONMENT",
            "PY_MOMO_SDK_BASE_URL",
            "PY_MOMO_SDK_TIMEOUT",
            "PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY",
            "PY_MOMO_SDK_COLLECTION_API_USER",
            "PY_MOMO_SDK_COLLECTION_API_KEY",
        ]:
            os.environ.pop(var, None)


def test_config_validation_rules() -> None:
    """Verify timeout, callback_url, environment, and AirtelConfig validations."""
    import pytest

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
    os.environ["PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY"] = "only-sub"
    try:
        with pytest.raises(MissingCredentialsError, match="Incomplete collection"):
            PyMomoSDKConfig.from_env()
    finally:
        os.environ.pop("PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY", None)

    os.environ["PY_MOMO_SDK_TIMEOUT"] = "-10"
    try:
        with pytest.raises(ValueError, match="PY_MOMO_SDK_TIMEOUT"):
            PyMomoSDKConfig.from_env()
    finally:
        os.environ.pop("PY_MOMO_SDK_TIMEOUT", None)
