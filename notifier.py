"""Scrape the page, match against active subscriptions, send emails."""

from __future__ import annotations

import logging
import os
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
            unsubscribe_token=sub.get("unsubscribe_token"),
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
        unsubscribe_token=sub.get("unsubscribe_token"),
        blocks=blocks,
    )


def _unsubscribe_url(token: str | None) -> str | None:
    if not token:
        return None
    base = os.environ.get("PUBLIC_BASE_URL", "https://sfjuryalert.com").rstrip("/")
    return f"{base}/unsubscribe?t={token}"


def _fetch_and_parse() -> Optional[list]:
    try:
        html = scraper.fetch_html()
    except Exception as exc:  # noqa: BLE001
        log.exception("scrape fetch failed")
        db.log_scrape(status="http_error", error=str(exc))
        _alert_if_failure_streak(str(exc))
        return None

    fingerprint = scraper.structural_fingerprint(html)
    _alert_if_structure_changed(fingerprint)

    try:
        blocks = scraper.parse(html)
    except Exception as exc:  # noqa: BLE001
        log.exception("scrape parse failed")
        db.log_scrape(status="parse_error", error=str(exc), page_fingerprint=fingerprint)
        _alert_if_failure_streak(str(exc))
        return None
    db.log_scrape(status="ok", blocks=len(blocks), page_fingerprint=fingerprint)
    return blocks


def _alert_if_structure_changed(new_fp: str) -> None:
    """Email the owner the first time the page's structural fingerprint
    changes. Silently noops on failure — we never want this path to block
    the actual scraper work."""
    try:
        last_fp = db.last_page_fingerprint()
        if last_fp == new_fp:
            return
        owner = os.environ.get("OWNER_EMAIL")
        if not owner:
            return
        emailer.send(
            to=owner,
            subject="sfjuryalert.com — court page structure changed",
            text=emailer.structure_change_body(last_fp, new_fp),
            html_body=emailer.structure_change_html(last_fp, new_fp),
        )
    except Exception:  # noqa: BLE001
        log.exception("structure-change alert failed")


def _alert_if_failure_streak(last_error: str | None) -> None:
    """Alert the owner when we hit exactly 3 consecutive non-OK scrapes.
    Firing only at ==3 means one email per outage, not one per failing run."""
    try:
        streak = db.failure_streak()
        if streak != 3:
            return
        owner = os.environ.get("OWNER_EMAIL")
        if not owner:
            return
        emailer.send(
            to=owner,
            subject=f"sfjuryalert.com — scraper failed {streak}x in a row",
            text=emailer.scrape_failure_alert_body(streak, last_error),
            html_body=emailer.scrape_failure_alert_html(streak, last_error),
        )
    except Exception:  # noqa: BLE001
        log.exception("failure-streak alert failed")


def _notify_subscription(
    sub_id: int,
    email: str,
    group_number: int,
    week_start: date,
    unsubscribe_token: str | None,
    blocks: list,
) -> int:
    week_end = week_start + timedelta(days=4)  # Mon..Fri inclusive
    unsub_url = _unsubscribe_url(unsubscribe_token)
    sent = 0
    for block in blocks:
        if group_number not in block.group_numbers:
            continue
        if not (week_start <= block.court_day <= week_end):
            continue
        if db.already_notified(sub_id, block.court_day):
            continue

        try:
            emailer.send(
                to=email,
                subject=f"Report for SF jury duty on {block.court_day.strftime('%A, %B %d')}",
                text=emailer.notification_body(
                    group_number=group_number,
                    court_day=block.court_day.strftime("%A, %B %d, %Y"),
                    time_text=block.time_text,
                    location=block.location,
                    unsubscribe_url=unsub_url,
                ),
                html_body=emailer.notification_html(
                    group_number=group_number,
                    court_day=block.court_day.strftime("%A, %B %d, %Y"),
                    time_text=block.time_text,
                    location=block.location,
                    unsubscribe_url=unsub_url,
                ),
            )
        except Exception:  # noqa: BLE001
            log.exception("notification email send failed for sub_id=%s", sub_id)
            continue
        db.record_notification(sub_id, block.court_day)
        db.log_event("notification")
        sent += 1
    return sent
