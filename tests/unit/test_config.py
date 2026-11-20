from __future__ import annotations

import os

from pymomo.config import MomoConfig, ProductConfig


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
    """Verify that MomoConfig.from_env reads environment variables correctly."""
    os.environ["PYMOMO_ENVIRONMENT"] = "mtnuganda"
    os.environ["PYMOMO_BASE_URL"] = "https://custom.momo.com"
    os.environ["PYMOMO_TIMEOUT"] = "45.0"
    os.environ["PYMOMO_COLLECTION_SUBSCRIPTION_KEY"] = "coll-sub"
    os.environ["PYMOMO_COLLECTION_API_USER"] = "coll-user"
    os.environ["PYMOMO_COLLECTION_API_KEY"] = "coll-key"

    try:
        config = MomoConfig.from_env()
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
            "PYMOMO_ENVIRONMENT",
            "PYMOMO_BASE_URL",
            "PYMOMO_TIMEOUT",
            "PYMOMO_COLLECTION_SUBSCRIPTION_KEY",
            "PYMOMO_COLLECTION_API_USER",
            "PYMOMO_COLLECTION_API_KEY",
        ]:
            os.environ.pop(var, None)


def test_config_validation_rules() -> None:
    """Verify timeout, callback_url, environment, and AirtelConfig validations."""
    import pytest

    from pymomo.airtel.config import AirtelConfig
    from pymomo.exceptions import MissingCredentialsError

    # Invalid timeouts
    for bad_timeout in (0, -5.0, float("inf"), float("nan"), True):
        with pytest.raises(
            (TypeError, ValueError), match="Timeout must be a positive finite"
        ):
            MomoConfig(timeout=bad_timeout)
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
        MomoConfig(environment="sandbox\r\nX-Injected: 1")
    with pytest.raises(ValueError, match="control characters"):
        ProductConfig(subscription_key="sub\r\n", api_user="user", api_key="key")

    # Airtel country & currency validation
    with pytest.raises(ValueError, match="Country"):
        AirtelConfig(
            client_id="cid", client_secret="sec", country="UGA", currency="UGX"
        )
    with pytest.raises(ValueError, match="ISO 4217"):
        AirtelConfig(client_id="cid", client_secret="sec", country="UG", currency="U")

    # Partial environment credentials and invalid PYMOMO_TIMEOUT rejected
    os.environ["PYMOMO_COLLECTION_SUBSCRIPTION_KEY"] = "only-sub"
    try:
        with pytest.raises(MissingCredentialsError, match="Incomplete collection"):
            MomoConfig.from_env()
    finally:
        os.environ.pop("PYMOMO_COLLECTION_SUBSCRIPTION_KEY", None)

    os.environ["PYMOMO_TIMEOUT"] = "-10"
    try:
        with pytest.raises(ValueError, match="PYMOMO_TIMEOUT"):
            MomoConfig.from_env()
    finally:
        os.environ.pop("PYMOMO_TIMEOUT", None)
