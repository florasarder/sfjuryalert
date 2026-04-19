# SF Jury Duty Notifier

A lightweight web service that monitors the San Francisco Superior Court jury reporting page and emails users if their group number is called during their week of service.

## Problem

SF jury duty requires prospective jurors to check https://sf.courts.ca.gov/divisions/jury-reporting-instructions every day during their week of service (updated ~4:30pm PST the day before). Missing a call can lead to penalties. A simple daily scrape + email removes the need to remember.

## User flow

1. User lands on a single-page form.
2. User inputs:
   - Email address
   - Jury group number (integer)
   - Week of service (start date — Monday of their assigned week)
3. User submits; receives a confirmation email.
4. The service checks the page on the following schedule for that user:
   - **Friday before their week** at 4:30pm PST (covers the Monday call)
   - **Mon–Thu of their week** at 4:30pm PST (covers Tue–Fri calls)
   - **If the user signs up after a scheduled scrape time has already passed** (mid-week, or Friday evening after 4:30pm PST before their week), run a scrape immediately on submission, then resume the daily 4:30pm PST schedule for any remaining days.
5. If their group number appears in a "Group Number(s): ..." block that is followed by "Please report in person on the following date, time and location:", the service parses the date/time/location and emails the user.
6. Each scheduled scrape is for the **next actual court day's** call (skipping holidays). E.g. if Monday is a court holiday, the Friday 4:30pm scrape may post Tuesday's call. A group may be called on multiple days in the same week, so send an email on **every** match — do not de-duplicate across days.
7. Always run scheduled scrapes on the Fri–Thu schedule — **do not skip** based on holidays. If the page hasn't been updated (e.g. because Monday is a holiday and the court didn't post a new call that morning), the scrape simply finds no new match and no email is sent. This is safer than predicting which days the court updates the page.
8. Parse the date from the matched block to determine the **court day** the match refers to; use that as the idempotency key (see Storage).
9. After the last scheduled check of their week, the job stops for that user.

## Target page

- URL: https://sf.courts.ca.gov/divisions/jury-reporting-instructions
- Expected content pattern (to parse):
  ```
  Group Number(s): 1, 7, 23
  Please report in person on the following date, time and location:
  <date> <time> <location>
  ```
- Group numbers are comma-separated; parser must handle whitespace, "and", trailing commas.
- There may be multiple such blocks on the page (different groups, different dates). Scrape all blocks and check each.

## Scope (MVP)

- Single HTML form (one page).
- Backend: Python (FastAPI or Flask) or Node (Express) — pick whichever is fastest to ship.
- Storage: SQLite file.
  - `subscriptions`: `{id, email, group_number, week_start, created_at}`
  - `notifications_sent`: `{subscription_id, court_day, sent_at}` — keyed on `(subscription_id, court_day)` where `court_day` is **parsed from the matched block**, not the scrape day. This way: (a) retries of the same scrape never double-email, (b) different court days in the same week produce separate emails, (c) if Fri's scrape already posted Tuesday's call and Mon's scrape still shows it, we don't re-email.
- Scraper: `requests` + `BeautifulSoup` (Python) or `fetch` + `cheerio` (Node). No headless browser unless the page turns out to be JS-rendered.
- Scheduler: cron or APScheduler running once daily at 4:30pm PST, Fri–Thu (Fri before the week through Thu of the week). Plus an immediate on-submit scrape for mid-week signups.
- Email: SMTP via a transactional provider (Resend, SendGrid, or Postmark — free tier is fine).
- Deployment: single small host (Fly.io, Railway, or a $5 VPS). No need for a DB server.

## Out of scope (for MVP)

- User accounts / login
- SMS notifications
- Multiple jurisdictions (SF only)
- Editing a submission after the fact (user re-submits if needed)
- Captcha / abuse prevention (add only if it becomes a problem)

## Open questions

- Does the page's HTML structure stay stable week to week? Needs a quick inspection to lock the parser.
- Is 4:30pm PST the correct update time, or is it sometimes earlier/later? May want to run at 4:30, 5:00, and 6:00 as a safety net.
- What timezone should the "week of service" input assume? (Default: America/Los_Angeles.)
- Confirmation email on signup: yes, include unsubscribe link.

## Build steps

1. Inspect the live page HTML; confirm structure and write a parser with a saved sample.
2. Stand up the form + POST endpoint + SQLite write.
3. Add the daily scrape job; log matches locally first.
4. Wire up the email provider; send test to self.
5. Deploy; do an end-to-end dry run with a fake group number that appears on the page.

## Notes

- Keep the page and service minimal — this is a utility, not a product.
- Log every scrape (timestamp, HTTP status, number of blocks found) so silent breakage is detectable.
- If the page format changes and parsing fails, email the operator, not the user.
