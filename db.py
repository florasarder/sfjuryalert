"""Postgres helpers (Neon). Each call opens a short-lived connection —
suitable for serverless where function instances are short-lived and the
Neon pooler handles connection reuse.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator, Optional

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def init_db() -> None:
    with connect() as conn:
        conn.execute(SCHEMA_PATH.read_text())


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL env var is not set")
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True) as conn:
        yield conn


def add_subscription(email: str, group_number: int, week_start: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO subscriptions (email, group_number, week_start) "
            "VALUES (%s, %s, %s) RETURNING id",
            (email, group_number, week_start),
        ).fetchone()
        return int(row["id"])


def active_subscriptions(today_iso: str) -> list[dict]:
    """Subscriptions whose monitoring window (Fri-before .. Fri-of-week)
    overlaps today."""
    with connect() as conn:
        return conn.execute(
            "SELECT id, email, group_number, week_start "
            "FROM subscriptions "
            "WHERE week_start - INTERVAL '3 days' <= %s::date "
            "  AND week_start + INTERVAL '4 days' >= %s::date",
            (today_iso, today_iso),
        ).fetchall()


def get_subscription(subscription_id: int) -> Optional[dict]:
    with connect() as conn:
        return conn.execute(
            "SELECT id, email, group_number, week_start "
            "FROM subscriptions WHERE id = %s",
            (subscription_id,),
        ).fetchone()


def already_notified(subscription_id: int, court_day: date) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM notifications_sent "
            "WHERE subscription_id = %s AND court_day = %s",
            (subscription_id, court_day),
        ).fetchone()
        return row is not None


def record_notification(subscription_id: int, court_day: date) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO notifications_sent (subscription_id, court_day) "
            "VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (subscription_id, court_day),
        )


def log_scrape(
    status: str, blocks: Optional[int] = None, error: Optional[str] = None
) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO scrape_log (status, blocks, error) VALUES (%s, %s, %s)",
            (status, blocks, error),
        )


def delete_expired(cutoff_iso: str) -> int:
    """Delete subscriptions whose week ended more than 7 days ago.
    FK cascade handles notifications_sent cleanup."""
    with connect() as conn:
        result = conn.execute(
            "DELETE FROM subscriptions "
            "WHERE week_start + INTERVAL '7 days' < %s::date",
            (cutoff_iso,),
        )
        return result.rowcount or 0


def log_event(event_type: str) -> None:
    """Record a privacy-safe activity event. Best-effort — swallows errors."""
    try:
        with connect() as conn:
            conn.execute("INSERT INTO events (type) VALUES (%s)", (event_type,))
    except Exception:  # noqa: BLE001
        pass  # never let analytics take down the request


def event_counts(types: list[str]) -> dict[str, dict[str, int]]:
    """Return {type: {'week': N, 'all_time': N}} for each requested type."""
    out: dict[str, dict[str, int]] = {t: {"week": 0, "all_time": 0} for t in types}
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT type,
                   COUNT(*) FILTER (WHERE occurred_at >= NOW() - INTERVAL '7 days')
                     AS week,
                   COUNT(*) AS all_time
            FROM events
            WHERE type = ANY(%s)
            GROUP BY type
            """,
            (types,),
        ).fetchall()
    for row in rows:
        out[row["type"]] = {"week": int(row["week"]), "all_time": int(row["all_time"])}
    return out
