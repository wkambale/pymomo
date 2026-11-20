from __future__ import annotations

from dataclasses import dataclass

AIRTEL_SANDBOX_BASE_URL = "https://openapiuat.airtel.africa"
AIRTEL_PRODUCTION_BASE_URL = "https://openapi.airtel.africa"


@dataclass
class AirtelConfig:
    """Credentials and configurations for Airtel Money."""

    client_id: str
    client_secret: str
    country: str  # ISO country code (e.g. "UG")
    currency: str  # ISO currency code (e.g. "UGX")
    pin: str | None = None  # Needed for disbursements
    environment: str = "sandbox"
    base_url: str | None = None
    timeout: float = 30.0

    def __post_init__(self) -> None:
        if self.base_url is None:
            self.base_url = (
                AIRTEL_SANDBOX_BASE_URL
                if self.environment == "sandbox"
                else AIRTEL_PRODUCTION_BASE_URL
            )

    def __repr__(self) -> str:
        return (
            f"AirtelConfig(client_id={self.client_id!r}, "
            f"client_secret=<redacted>, country={self.country!r}, "
            f"currency={self.currency!r}, pin=<redacted>, "
            f"environment={self.environment!r}, base_url={self.base_url!r}, "
            f"timeout={self.timeout!r})"
        )
