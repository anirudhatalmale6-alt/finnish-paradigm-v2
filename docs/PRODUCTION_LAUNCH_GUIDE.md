# Finnish Paradigm™ Production Launch Guide

## What is included
- Responsive commercial website
- FastAPI backend
- Secure password hashing and bearer-token authentication
- Admin and manager roles
- Course catalogue and enrollment flow
- Learner dashboard and progress tracking
- Admin dashboard
- Booking system
- Item bank
- Adaptive assessment engine
- Intervention case tracking
- Payment checkout hand-off with Stripe-ready environment keys
- PDF downloads and resource library
- Dockerfile, Docker Compose, Nginx reverse proxy example and tests

## Launch steps
1. Copy `.env.example` to `.env`.
2. Replace `JWT_SECRET`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `PUBLIC_BASE_URL`, and `ALLOWED_ORIGINS`.
3. Add Stripe and SMTP credentials when available. Without Stripe keys the platform records manual invoice orders.
4. Run `docker compose up --build -d`.
5. Visit `/api/health`, then log in through `/login.html`.
6. Put Nginx or a cloud load balancer in front of port 8000 and enable SSL using your host or Certbot.
7. Upload final legal pages: Terms, Privacy, Refund, Child Safeguarding and Data Processing Agreement.

## Security checklist before real payments
- Use a 64+ character JWT secret.
- Change the default admin password.
- Restrict `ALLOWED_ORIGINS` to the production domain only.
- Enable HTTPS.
- Use a managed database/backups for commercial volume.
- Configure Stripe webhook validation before taking card payments.
- Add your jurisdiction-specific legal documents.
