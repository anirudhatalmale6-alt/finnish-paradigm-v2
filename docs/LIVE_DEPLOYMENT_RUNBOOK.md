# Live Deployment Runbook

## 1. Server
Provision Ubuntu 22.04+ VPS with 2 CPU, 4GB RAM minimum. Install Docker and Docker Compose.

## 2. Upload package
Upload this folder to `/opt/finnish-paradigm`.

## 3. Configure environment
Copy `.env.example` to `.env` and set real values. Never commit `.env`.

## 4. Start services
```bash
docker compose up -d --build
docker compose logs -f
```

## 5. Nginx / SSL
Point domain A record to server. Configure Nginx reverse proxy to the app container. Use Certbot for HTTPS.

## 6. Stripe
Create products/prices in Stripe or use price_data checkout. Add webhook endpoint: `/api/stripe/webhook`. Configure events: `checkout.session.completed`.

## 7. SMTP
Set SMTP host, username, password and sender address. Test booking and checkout emails.

## 8. Admin
Log in as the admin email/password from `.env`; immediately rotate password if necessary.

## 9. Verification
- Register a learner
- Buy test product in Stripe test mode
- Verify webhook changes order status to paid
- Verify enrolment access is created
- Complete assessment
- Submit booking
- Download PDF resource
- Open admin dashboard

## 10. Backups
Back up `/app/data` daily or migrate to managed PostgreSQL before scaling.
