"""Scrape the page, match against active subscriptions, send emails."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import db
import emailer
import scraper

log = logging.getLogger(__name__)


def run_all(today: Optional[date] = None) -> int:
    """Fetch the page and notify every matching active subscription.

    Returns the number of emails sent.
    """
    today = today or date.today()
    blocks = _fetch_and_parse()
    if blocks is None:
        return 0

    sent = 0
    for sub in db.active_subscriptions(today.isoformat()):
        sent += _notify_subscription(
            sub_id=sub["id"],
            email=sub["email"],
            group_number=sub["group_number"],
            week_start=sub["week_start"],
            blocks=blocks,
        )
    return sent


def run_for_subscription(subscription_id: int) -> int:
    """Scrape and notify for a single subscription (used on sign-up)."""
    blocks = _fetch_and_parse()
    if blocks is None:
        return 0

    sub = db.get_subscription(subscription_id)
    if sub is None:
        return 0

    return _notify_subscription(
        sub_id=sub["id"],
        email=sub["email"],
        group_number=sub["group_number"],
        week_start=sub["week_start"],
        blocks=blocks,
    )


def _fetch_and_parse() -> Optional[list]:
    try:
        html = scraper.fetch_html()
    except Exception as exc:  # noqa: BLE001
        log.exception("scrape fetch failed")
        db.log_scrape(status="http_error", error=str(exc))
        return None
    try:
        blocks = scraper.parse(html)
    except Exception as exc:  # noqa: BLE001
        log.exception("scrape parse failed")
        db.log_scrape(status="parse_error", error=str(exc))
        return None
    db.log_scrape(status="ok", blocks=len(blocks))
    return blocks


def _notify_subscription(
    sub_id: int,
    email: str,
    group_number: int,
    week_start: date,
    blocks: list,
) -> int:
    week_end = week_start + timedelta(days=4)  # Mon..Fri inclusive
    sent = 0
    for block in blocks:
        if group_number not in block.group_numbers:
            continue
        if not (week_start <= block.court_day <= week_end):
            continue
        if db.already_notified(sub_id, block.court_day):
            continue

        emailer.send(
            to=email,
            subject=f"SF jury duty: report on {block.court_day.strftime('%A, %B %d')}",
            text=emailer.notification_body(
                group_number=group_number,
                court_day=block.court_day.strftime("%A, %B %d, %Y"),
                time_text=block.time_text,
                location=block.location,
            ),
            html_body=emailer.notification_html(
                group_number=group_number,
                court_day=block.court_day.strftime("%A, %B %d, %Y"),
                time_text=block.time_text,
                location=block.location,
            ),
        )
        db.record_notification(sub_id, block.court_day)
        sent += 1
    return sent
