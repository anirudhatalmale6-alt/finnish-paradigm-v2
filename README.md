# The Finnish Paradigm™ — Commercial Deployment Build

This package contains a production-oriented commercial EdTech platform build for The Finnish Paradigm™.

## Included functions

- Responsive commercial website
- Public course catalogue and product pages
- User registration and login
- Password hashing and signed bearer-token authentication
- Teacher/learner/manager/admin role structure
- Learner dashboard
- Course enrolment and lesson progress tracking
- PDF resource/toolkit downloads
- Booking/demo request system
- Admin dashboard APIs
- Item bank
- Adaptive assessment/testing engine
- Intervention case/escalation engine
- Stripe-ready checkout and webhook endpoint
- SMTP-ready transactional email confirmations
- Legal page templates
- Dockerfile and Docker Compose
- Production launch guide, live runbook and operations manual
- Automated tests

## What must be configured by the owner before live commercial launch

No code package can contain owner-specific live credentials or legal approvals. Before accepting real payments, configure:

1. Domain and SSL
2. Production `.env` values
3. Strong `JWT_SECRET`
4. New admin password
5. Stripe live secret key and webhook secret
6. SMTP credentials
7. Completed legal pages reviewed by qualified counsel
8. Video hosting links after AI presenter videos are rendered
9. Backup and monitoring service
10. Final end-to-end payment test

## Local run

```bash
cp .env.example .env
docker compose up -d --build
```

Open: `http://localhost:8000`

## Tests

```bash
python -m pytest -q
```

Current package test result at build time: `5 passed`.

## Commercial readiness statement

The software is commercially deployable after owner-specific configuration is added. It includes the operational code paths and templates for a live platform, but the owner must supply legal, payment, domain, email and video-hosting credentials.


## Stripe Live Readiness Upgrade

This package now includes live-ready Stripe commerce logic except for the owner-specific `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET`, which must be added only in the live environment. It supports one-time Checkout, subscription Checkout, Stripe Product/Price IDs, inline price fallback, promotion codes, optional Stripe Tax, webhook event verification, automatic course access activation, customer billing portal, subscription status tracking, refunds, failed-payment status updates, dispute markers and audit logging of Stripe events. See `docs/STRIPE_LIVE_READINESS.md`.

Verification command:

```bash
PYTHONPATH=. pytest -q
```

Current local result after this upgrade: `6 passed`.
