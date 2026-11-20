---
hide:
  - toc
---

<section class="pm-hero">
  <svg class="pm-hero__rings" viewBox="0 0 240 240" fill="none" aria-hidden="true">
    <circle cx="150" cy="90" r="52" stroke="rgba(251, 191, 36, 0.32)" stroke-width="1.5"/>
    <circle cx="166" cy="102" r="82" stroke="rgba(226, 232, 240, 0.22)" stroke-width="1.5"/>
    <circle cx="138" cy="78" r="110" stroke="rgba(226, 232, 240, 0.12)" stroke-width="1.5"/>
  </svg>
  <div class="pm-hero__eyebrow">
    <span class="pm-hero__eyebrow-line" aria-hidden="true"></span>
    <span>Python SDK version 1.0.5</span>
  </div>
  <h1 class="pm-hero__title">Py MoMo API for MTN Mobile Money and Airtel Money</h1>
  <p class="pm-hero__lead">A strictly typed, production-grade Python client for MTN MoMo and Airtel Money. Built with synchronous and asynchronous parity, automatic token caching, strict input validation, and verified webhook security.</p>
  <div class="pm-hero__actions">
    <a class="pm-btn-primary" href="quickstart/">Get started</a>
    <a class="pm-btn-secondary" href="authentication/">Configure authentication</a>
  </div>
  <svg class="pm-hero__chevron" viewBox="0 0 1200 18" preserveAspectRatio="none" aria-hidden="true">
    <defs>
      <pattern id="pm-chevron-pattern" width="36" height="18" patternUnits="userSpaceOnUse">
        <path d="M0 18 L18 4 L36 18" fill="none" stroke="rgba(251, 191, 36, 0.32)" stroke-width="1.5"/>
      </pattern>
    </defs>
    <rect width="1200" height="18" fill="url(#pm-chevron-pattern)"/>
  </svg>
</section>

## Supported products

Py MoMo API covers every product exposed by the MTN MoMo Developer portal alongside Airtel Money collections and disbursements.

<div class="pm-card-grid">
  <article class="pm-card">
    <p class="pm-card__eyebrow">MTN MoMo</p>
    <div class="pm-card__body">
      <h3 class="pm-card__title">Collection</h3>
      <p class="pm-card__text">Request payments, initiate withdrawals, query balances, and exchange CIBA OAuth2 consent tokens.</p>
      <a class="pm-card__link" href="collection/">Explore collection</a>
    </div>
  </article>
  <article class="pm-card">
    <p class="pm-card__eyebrow">MTN MoMo</p>
    <div class="pm-card__body">
      <h3 class="pm-card__title">Disbursement</h3>
      <p class="pm-card__text">Execute subscriber transfers, v2 deposits, refunds, and account holder validation checks.</p>
      <a class="pm-card__link" href="disbursement/">Explore disbursement</a>
    </div>
  </article>
  <article class="pm-card">
    <p class="pm-card__eyebrow">MTN MoMo</p>
    <div class="pm-card__body">
      <h3 class="pm-card__title">Remittance</h3>
      <p class="pm-card__text">Send domestic and international wallet-to-wallet transfers with automatic reference tracking.</p>
      <a class="pm-card__link" href="remittance/">Explore remittance</a>
    </div>
  </article>
  <article class="pm-card">
    <p class="pm-card__eyebrow">Airtel Open API</p>
    <div class="pm-card__body">
      <h3 class="pm-card__title">Airtel Money</h3>
      <p class="pm-card__text">Initiate USSD Push collections, disbursement payouts, status inquiries, and wallet balance checks.</p>
      <a class="pm-card__link" href="airtel/">Explore Airtel Money</a>
    </div>
  </article>
</div>

<div class="pm-band pm-band--sand" markdown="1">

<div class="pm-band__eyebrow">
  <span class="pm-band__eyebrow-line" aria-hidden="true"></span>
  <span>Quickstart</span>
</div>

## Install and query a balance in ten lines

Install `py-momo-api` from PyPI and import the `py_momo_api` package:

```bash
pip install py-momo-api
```

```python
from py_momo_api import ProductConfig, PyMomoAPI, PyMomoAPIConfig

config = PyMomoAPIConfig(
    environment="sandbox",
    collection=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
    ),
)

with PyMomoAPI(config) as client:
    balance = client.collection.get_balance()
    print(f"Balance: {balance.available_balance} {balance.currency}")
```

</div>

<div class="pm-spotlight-grid">
  <div class="pm-spotlight pm-spotlight--accent">
    <h3>Sync and async parity</h3>
    <p>Switch cleanly between <code>PyMomoAPI</code> and <code>AsyncPyMomoAPI</code> with identical method signatures, Pydantic v2 models, and thread-safe or async-safe token refresh locking.</p>
  </div>
  <div class="pm-spotlight pm-spotlight--brand">
    <h3>Security by default</h3>
    <p>Every client enforces HTTPS endpoints, disables automatic HTTP redirects, validates canonical UUID v4 references, redacts credentials from logs and tracebacks, and verifies webhook HMAC signatures and source IPs.</p>
  </div>
</div>

<div class="pm-band pm-band--mist" markdown="1">

<div class="pm-band__eyebrow">
  <span class="pm-band__eyebrow-line" aria-hidden="true"></span>
  <span>Documentation directory</span>
</div>

## Explore the guides

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

</div>
