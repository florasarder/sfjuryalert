"""Vercel entry point. Single Flask app serves form, subscribe, and cron endpoints.

File layout: modules (db, emailer, notifier, scraper, privacy) live at the
project root; this file imports them via a sys.path hack so the same modules
work both locally and on Vercel.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(_PROJECT_ROOT / ".env")

import pytz
from flask import Flask, abort, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import db
import emailer
import notifier

PACIFIC = pytz.timezone("America/Los_Angeles")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

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
    return render_template(
        "form.html", form={}, message=None, error=None,
        today=date.today().isoformat(),
    )


@app.route("/subscribe", methods=["POST"])
@limiter.limit("5/hour;20/day")
def subscribe():
    form = {
        "email": (request.form.get("email") or "").strip().lower(),
        "group_number": (request.form.get("group_number") or "").strip(),
        "week_start": (request.form.get("week_start") or "").strip(),
    }

    error = _validate(form)
    if error:
        return render_template(
            "form.html", form=form, error=error, message=None,
            today=date.today().isoformat(),
        )

    sub_id = db.add_subscription(
        email=form["email"],
        group_number=int(form["group_number"]),
        week_start=form["week_start"],
    )

    emailer.send(
        to=form["email"],
        subject="Signed up for SF jury duty notifications",
        text=emailer.confirmation_body(int(form["group_number"]), form["week_start"]),
        html_body=emailer.confirmation_html(
            int(form["group_number"]), form["week_start"]
        ),
    )

    _maybe_immediate_scrape(sub_id, form["week_start"])

    return render_template(
        "form.html", form={}, error=None,
        message=(
            f"Subscribed. We'll email {form['email']} if group "
            f"{form['group_number']} is called."
        ),
        today=date.today().isoformat(),
    )


@app.route("/api/scrape", methods=["GET", "POST"])
def cron_scrape():
    _require_cron_auth()
    sent = notifier.run_all()
    return jsonify({"sent": sent}), 200


@app.route("/api/cleanup", methods=["GET", "POST"])
def cron_cleanup():
    _require_cron_auth()
    deleted = db.delete_expired(date.today().isoformat())
    return jsonify({"deleted": deleted}), 200


@app.route("/api/init", methods=["GET", "POST"])
def api_init():
    """One-time schema bootstrap. Safe to re-run (CREATE IF NOT EXISTS)."""
    _require_cron_auth()
    db.init_db()
    return jsonify({"ok": True}), 200


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
