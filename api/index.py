"""Vercel entry point. Single Flask app serves form, subscribe, and cron endpoints.

File layout: modules (db, emailer, notifier, scraper, privacy) live at the
project root; this file imports them via a sys.path hack so the same modules
work both locally and on Vercel.
"""

from __future__ import annotations

import hmac
import os
import re
import secrets
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(_PROJECT_ROOT / ".env")

import pytz
from flask import Flask, Response, abort, jsonify, make_response, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import db
import emailer
import notifier

PACIFIC = pytz.timezone("America/Los_Angeles")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CSRF_COOKIE = "csrf_token"
TESTING_EMAIL = os.environ.get("TESTING_EMAIL", "flammeus@gmail.com").lower()

app = Flask(
    __name__,
    template_folder=str(_PROJECT_ROOT / "templates"),
)

# In-memory limiter is best-effort in serverless (each function instance has
# its own memory). For stronger limits, swap storage_uri to a shared store
# like Upstash Redis.
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


@app.route("/", methods=["GET"])
def index():
    db.log_event("page_view")
    return _render_form(form={}, message=None, error=None)


@app.route("/subscribe", methods=["POST"])
@limiter.limit("5/hour;20/day")
def subscribe():
    wants_json = request.headers.get("X-Requested-With") == "fetch"

    if not _csrf_ok(request):
        if wants_json:
            return jsonify({"ok": False, "error": "Invalid session. Please refresh and try again."}), 400
        abort(400, description="Invalid or missing CSRF token.")

    form = {
        "email": (request.form.get("email") or "").strip().lower(),
        "group_number": (request.form.get("group_number") or "").strip(),
        "week_start": (request.form.get("week_start") or "").strip(),
    }

    error = _validate(form)
    if error:
        if wants_json:
            return jsonify({"ok": False, "error": error}), 400
        return _render_form(form=form, error=error, message=None)

    group_num = int(form["group_number"])

    # Dedupe: one subscription per (email, group, week). Exception for the
    # testing email so the owner can still re-subscribe during QA.
    existing = db.find_subscription(form["email"], group_num, form["week_start"])
    if existing and form["email"] != TESTING_EMAIL:
        msg = (
            f"You're already signed up. We'll email {form['email']} if "
            f"group {form['group_number']} is called."
        )
        if wants_json:
            return jsonify({"ok": True, "message": msg}), 200
        return _render_form(form={}, error=None, message=msg)

    token = secrets.token_urlsafe(24)
    sub_id = db.add_subscription(
        email=form["email"],
        group_number=group_num,
        week_start=form["week_start"],
        unsubscribe_token=token,
    )
    db.log_event("registration")

    unsub_url = _unsubscribe_url(token)
    try:
        emailer.send(
            to=form["email"],
            subject="You're signed up for SF jury duty notifications",
            text=emailer.confirmation_body(
                group_num, form["week_start"], unsubscribe_url=unsub_url
            ),
            html_body=emailer.confirmation_html(
                group_num, form["week_start"], unsubscribe_url=unsub_url
            ),
            list_unsubscribe_url=unsub_url,
        )
    except Exception:  # noqa: BLE001
        app.logger.exception("confirmation email failed for sub_id=%s", sub_id)

    _maybe_immediate_scrape(sub_id, form["week_start"])

    msg = (
        f"Subscribed. We'll email {form['email']} if group "
        f"{form['group_number']} is called."
    )
    if wants_json:
        return jsonify({"ok": True, "message": msg}), 200
    return _render_form(form={}, error=None, message=msg)


@app.route("/unsubscribe", methods=["GET", "POST"])
def unsubscribe():
    # GET: user clicked the link — render confirmation UI.
    # POST: Gmail/Outlook one-click (RFC 8058) — no UI, just return 200.
    token = (
        (request.args.get("t") or "").strip()
        or (request.form.get("t") or "").strip()
    )
    removed = db.delete_by_token(token) if token else None

    if request.method == "POST":
        return ("", 200) if removed else ("", 404)

    return _render_form(
        form={}, error=None, message=None,
        unsubscribed=bool(removed),
        unsubscribe_failed=(not removed),
    )


@app.route("/robots.txt", methods=["GET"])
def robots_txt() -> Response:
    base = _public_base_url()
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "Disallow: /unsubscribe\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml", methods=["GET"])
def sitemap_xml() -> Response:
    base = _public_base_url()
    today = date.today().isoformat()
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{base}/</loc><lastmod>{today}</lastmod>"
        "<changefreq>weekly</changefreq><priority>1.0</priority></url>\n"
        "</urlset>\n"
    )
    return Response(body, mimetype="application/xml")


@app.route("/api/scrape", methods=["GET", "POST"])
def cron_scrape():
    """Daily cron: run scrape + notify, then clean up expired subscriptions.

    Cleanup is consolidated here so we stay within Vercel Hobby's 2-cron cap
    (scrape + weekly summary).
    """
    _require_cron_auth()
    sent = notifier.run_all()
    deleted = db.delete_expired(date.today().isoformat())
    return jsonify({"sent": sent, "deleted": deleted}), 200


@app.route("/api/weekly-summary", methods=["GET", "POST"])
def cron_weekly_summary():
    """Email the owner a usage summary (this week + all time)."""
    _require_cron_auth()
    owner = os.environ.get("OWNER_EMAIL")
    if not owner:
        return jsonify({"error": "OWNER_EMAIL not set"}), 500

    counts = db.event_counts(["page_view", "registration", "notification"])
    # Emails sent = confirmations (= registrations) + notifications
    emails_week = counts["registration"]["week"] + counts["notification"]["week"]
    emails_all = counts["registration"]["all_time"] + counts["notification"]["all_time"]

    summary = {
        "views": counts["page_view"],
        "registrations": counts["registration"],
        "emails_sent": {"week": emails_week, "all_time": emails_all},
        "notifications": counts["notification"],
    }

    emailer.send(
        to=owner,
        subject="sfjuryalert.com — weekly summary",
        text=emailer.summary_body(summary),
        html_body=emailer.summary_html(summary),
    )
    return jsonify({"sent_to": owner, "summary": summary}), 200


@app.route("/api/init", methods=["GET", "POST"])
def api_init():
    """One-time schema bootstrap. Safe to re-run (CREATE IF NOT EXISTS)."""
    _require_cron_auth()
    db.init_db()
    return jsonify({"ok": True}), 200


def _render_form(
    form: dict,
    message: str | None,
    error: str | None,
    unsubscribed: bool = False,
    unsubscribe_failed: bool = False,
) -> Response:
    """Render the landing template and ensure a CSRF cookie is set.
    Token is generated per-visitor if absent; reused otherwise."""
    token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(24)
    html = render_template(
        "form.html",
        form=form,
        message=message,
        error=error,
        today=date.today().isoformat(),
        feedback_email=os.environ.get("FEEDBACK_EMAIL", "info@sfjuryalert.com"),
        last_check=_last_check_display(),
        csrf_token=token,
        unsubscribed=unsubscribed,
        unsubscribe_failed=unsubscribe_failed,
    )
    resp = make_response(html)
    if request.cookies.get(CSRF_COOKIE) != token:
        resp.set_cookie(
            CSRF_COOKIE, token,
            max_age=60 * 60 * 24 * 7,
            secure=not app.debug,
            httponly=False,  # template reads it via form field, not JS
            samesite="Lax",
        )
    return resp


def _csrf_ok(req) -> bool:
    cookie_tok = req.cookies.get(CSRF_COOKIE) or ""
    form_tok = (req.form.get("csrf_token") or "").strip()
    if not cookie_tok or not form_tok:
        return False
    return hmac.compare_digest(cookie_tok, form_tok)


def _public_base_url() -> str:
    base = os.environ.get("PUBLIC_BASE_URL")
    if base:
        return base.rstrip("/")
    return request.host_url.rstrip("/")


def _unsubscribe_url(token: str) -> str:
    return f"{_public_base_url()}/unsubscribe?t={token}"


def _require_cron_auth() -> None:
    """Vercel Cron sends `Authorization: Bearer $CRON_SECRET` when set.
    In dev (no secret configured), the endpoint is open."""
    expected = os.environ.get("CRON_SECRET")
    if not expected:
        return
    header = request.headers.get("Authorization", "")
    provided = header[7:] if header.startswith("Bearer ") else header
    if provided != expected:
        abort(401)


def _last_check_display() -> dict | None:
    """Return a small dict the template can render as a social-proof
    status line. Never raises — returns None if the DB is unreachable
    or has no scrape rows yet."""
    try:
        row = db.last_scrape_info()
    except Exception:  # noqa: BLE001
        return None
    if not row:
        return None
    ran_at = row["ran_at"].astimezone(PACIFIC)
    today_pt = datetime.now(PACIFIC).date()
    if ran_at.date() == today_pt:
        day = "today"
    elif ran_at.date() == today_pt - timedelta(days=1):
        day = "yesterday"
    else:
        day = ran_at.strftime("%B %d")
    time = ran_at.strftime("%-I:%M%p").lower()
    return {
        "label": f"Last check: {day} at {time} PT",
        "ok": row["status"] == "ok",
    }


def _validate(form: dict) -> str | None:
    if not EMAIL_RE.match(form["email"]):
        return "Enter a valid email address."
    if not form["group_number"].isdigit() or int(form["group_number"]) < 1:
        return "Group number must be a positive integer."
    try:
        ws = datetime.strptime(form["week_start"], "%Y-%m-%d").date()
    except ValueError:
        return "Week start must be a date."
    if ws.weekday() != 0:
        return "Week start must be a Monday."
    if ws < date.today():
        return "Week of service must be today or later."
    return None


def _maybe_immediate_scrape(subscription_id: int, week_start_iso: str) -> None:
    """Run an immediate scrape for this subscription if we're inside the
    window that daily crons would otherwise cover (Fri 16:30 PT before the
    week through Fri 00:00 PT of the week)."""
    week_start = date.fromisoformat(week_start_iso)
    now_pt = datetime.now(PACIFIC)
    monday_midnight = PACIFIC.localize(
        datetime.combine(week_start, datetime.min.time())
    )
    window_start = (
        monday_midnight - timedelta(days=3) + timedelta(hours=16, minutes=30)
    )
    window_end = monday_midnight + timedelta(days=4)
    if window_start <= now_pt <= window_end:
        try:
            notifier.run_for_subscription(subscription_id)
        except Exception:  # noqa: BLE001
            app.logger.exception("immediate scrape failed")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
