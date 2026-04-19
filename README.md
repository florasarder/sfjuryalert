# SF Jury Duty Notifier

Small Flask app (Vercel-deployable) that monitors the SF Superior Court jury
reporting page and emails a user when their group is called.

See `PROJECT.md` for the full spec.

## Architecture

- `api/index.py` — Flask app entry (form, subscribe, cron endpoints)
- `scraper.py` — fetch + parse the court page (BeautifulSoup)
- `notifier.py` — run scrape, match subscriptions, send emails
- `emailer.py` — SMTP sender (HTML + plain text), prints to stdout in dev
- `db.py` + `schema.sql` — Postgres (Neon) storage
- `privacy.py` — PII redaction helpers
- `templates/form.html` — single-page form (matches landing-page design)
- `vercel.json` — rewrites all routes to the Flask app, cron schedule
- `tests/` — scraper tests + fixture

## Env vars

| Name | Purpose |
|---|---|
| `DATABASE_URL` | Neon Postgres connection string |
| `SMTP_HOST` | e.g. `smtp.resend.com` |
| `SMTP_PORT` | e.g. `465` |
| `SMTP_USER` | e.g. `resend` |
| `SMTP_PASSWORD` | Resend API key |
| `SMTP_FROM` | From address, e.g. `jury@yourdomain.com` |
| `CRON_SECRET` | Random token; Vercel Cron sends it as `Authorization: Bearer ...` |
| `JURY_ENV` | Set to `production` to block email printing on dev-mode misconfig |

## Local development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# .env already created with your Resend creds. Add DATABASE_URL from Neon:
# echo "DATABASE_URL=postgresql://..." >> .env

# Bootstrap schema once:
.venv/bin/python -c "from api.index import db; db.init_db()"

.venv/bin/python api/index.py
# open http://127.0.0.1:5000
```

Tests:
```bash
.venv/bin/python tests/test_scraper.py
```

## Deploy to Vercel

1. Push this directory to a GitHub repo.
2. On Vercel: **New Project** → import the repo.
3. Under **Environment Variables**, add every name in the table above.
4. Deploy.
5. First deploy only: call `POST https://<your-app>.vercel.app/api/init`
   with `Authorization: Bearer $CRON_SECRET` to create the schema.
   (Or run `db.init_db()` locally against your Neon URL.)

Vercel Cron will hit `/api/scrape` daily at **00:30 UTC** (= 4:30pm PST or
5:30pm PDT — always after the court updates the page) and `/api/cleanup`
at 11:00 UTC.

### Note on cron and DST

Vercel Cron schedules are UTC-only. `00:30 UTC` converts to:
- **4:30pm PT** (during PST — late Nov through mid-March)
- **5:30pm PT** (during PDT — rest of the year)

Either way we scrape *after* the court's 4:30pm local-time posting, which is
what we want.

## Security

- All SQL uses parameterized queries.
- `/subscribe` is rate-limited (best-effort in serverless).
- Emails are redacted in logs via `privacy.redact_email()`.
- `JURY_ENV=production` + missing `SMTP_HOST` → boot refuses, preventing
  PII in logs.
- Subscriptions auto-delete 7 days after their week ends via the daily
  cleanup cron.
- Cron endpoints require `CRON_SECRET` in the Authorization header.

## Notes

- `python-dotenv` loads `.env` at startup (see `api/index.py`).
- Postgres FK cascade deletes `notifications_sent` rows when a
  subscription is removed — no manual cleanup needed.
