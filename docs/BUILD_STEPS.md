# Clear Build Steps for Live Deployment

## 1. Prepare the brand and domain

- Choose final domain, for example `finnishparadigm.com`.
- Prepare logo, colours, terms, privacy policy and refund policy.
- Use evidence-informed wording unless formal certification authorisation is obtained.

## 2. Build locally

```bash
docker compose up --build
```

Visit `http://localhost:8000` and test:

- Homepage navigation
- Course catalogue
- Enrolment form
- Booking form
- Adaptive assessment
- Admin dashboard
- PDF downloads

## 3. Replace demo content

Edit:

```text
backend/app/data_seed.py
content/*.json
frontend/*.html
backend/static/assets/styles.css
```

Rebuild PDFs:

```bash
python scripts/build_pdfs.py
```

## 4. Add payments

Integrate Stripe Checkout or your preferred provider.
Recommended product mapping:

- Teacher Starter Bundle
- Early Intervention Toolkit
- FCFP Course
- ASTI Course
- SELD Course
- Whole-School License

## 5. Add authentication

For production, add:

- user accounts
- admin accounts
- learner progress records
- certificate generation
- school organisation accounts
- password reset

## 6. Replace SQLite

Use PostgreSQL:

- bookings
- users
- enrolments
- course progress
- item bank
- assessment responses
- certificates

## 7. Add video hosting

Generate AI videos externally and store:

```text
backend/static/videos/
```

or use Vimeo, Bunny Stream, Cloudflare Stream or S3/CDN.

## 8. Deploy

Possible hosts:

- Render
- Railway
- Fly.io
- DigitalOcean App Platform
- AWS ECS
- Azure Container Apps
- Google Cloud Run

Example Docker command:

```bash
docker build -t finnish-paradigm .
docker run -p 8000:8000 finnish-paradigm
```

## 9. Secure

- Enable HTTPS
- Add CORS restrictions
- Add admin login
- Add rate limiting
- Store secrets in environment variables
- Add backups
- Add monitoring

## 10. Launch funnel

- Free early intervention PDF
- 5-day mini-course
- Teacher certificate
- Early Intervention Toolkit upsell
- School demo booking
- Institutional license
