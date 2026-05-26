# Stripe Live Readiness

This build contains live-ready Stripe integration code except for the owner-specific secrets that must never be bundled in a ZIP package.

## What is included

- Stripe Checkout session creation for one-time products.
- Stripe Checkout session creation for subscriptions and annual licences.
- Support for Stripe Product/Price IDs through environment variables.
- Inline price-data fallback when Product/Price IDs are not configured.
- Stripe webhook endpoint with signature verification.
- Payment confirmation, order status update and automatic course access activation.
- Subscription table and webhook handling for created, updated, deleted and failed subscription payments.
- Customer Billing Portal endpoint for subscription/card/invoice management.
- Admin refund endpoint for full or partial refunds.
- Webhook event recording for auditability.
- Stripe Tax toggle and promotion-code support.
- Order failure, expiry, refund, dispute and payment-failed statuses.
- `/api/stripe/readiness` endpoint to verify configuration before launch.

## Owner-specific values still required

Add these values in production only:

```env
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

Optional but recommended Stripe Price IDs:

```env
STRIPE_PRICE_TEACHER_STARTER=price_...
STRIPE_PRICE_TEACHER_CERTIFICATE=price_...
STRIPE_PRICE_EARLY_INTERVENTION=price_...
STRIPE_PRICE_RETIRED_MENTOR=price_...
STRIPE_PRICE_SCHOOL_LEADERSHIP=price_...
STRIPE_PRICE_LEADERSHIP_DIPLOMA=price_...
STRIPE_PRICE_TOOLKIT_BUNDLE=price_...
STRIPE_PRICE_MEMBERSHIP_MONTHLY=price_...
STRIPE_PRICE_SCHOOL_LICENSE=price_...
```

## Required Stripe webhook events

Configure these events in the Stripe Dashboard and point them to:

```text
https://yourdomain.com/api/stripe/webhook
```

Events:

- `checkout.session.completed`
- `checkout.session.expired`
- `checkout.session.async_payment_failed`
- `payment_intent.payment_failed`
- `charge.refunded`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.paid`
- `invoice.payment_failed`
- `charge.dispute.created`

## Pre-launch Stripe test checklist

```text
[ ] Add test STRIPE_SECRET_KEY
[ ] Add test STRIPE_WEBHOOK_SECRET
[ ] Configure webhook endpoint in Stripe test mode
[ ] Run one-time product checkout
[ ] Run subscription checkout
[ ] Confirm course access activates after webhook
[ ] Confirm failed payment status updates
[ ] Confirm refund endpoint creates a Stripe refund
[ ] Confirm Billing Portal link opens for a paid customer
[ ] Switch to live keys only after all tests pass
```
