"""Fetch and parse the SF court jury reporting page.

Returns a list of ReportBlock — one per "Please report in person" block.
Standby and already-reported blocks are intentionally ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup, Tag

PAGE_URL = "https://sf.courts.ca.gov/divisions/jury-reporting-instructions"
REPORT_MARKER = "Please report in person on the following date, time and location:"
USER_AGENT = "Mozilla/5.0 (SF Jury Duty Notifier)"


@dataclass(frozen=True)
class ReportBlock:
    group_numbers: tuple[int, ...]
    court_day: date
    time_text: str
    location: str


def fetch_html(url: str = PAGE_URL, timeout: int = 30) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def parse(html: str) -> list[ReportBlock]:
    soup = BeautifulSoup(html, "html.parser")
    blocks: list[ReportBlock] = []
    for bq in soup.select("blockquote.blockquote--alert--success"):
        text = bq.get_text(" ", strip=True)
        if REPORT_MARKER not in text:
            continue
        block = _parse_block(bq)
        if block is not None:
            blocks.append(block)
    return blocks


def _parse_block(bq: Tag) -> ReportBlock | None:
    text = bq.get_text("\n", strip=True)
    groups = _extract_field(text, "Group Number(s)")
    date_str = _extract_field(text, "Date")
    time_str = _extract_field(text, "Time")
    location = _extract_field(text, "Location")
    if not (groups and date_str and time_str and location):
        return None
    group_numbers = _parse_groups(groups)
    court_day = _parse_date(date_str)
    if not group_numbers or court_day is None:
        return None
    return ReportBlock(
        group_numbers=group_numbers,
        court_day=court_day,
        time_text=time_str,
        location=location,
    )


_FIELD_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _extract_field(text: str, label: str) -> str | None:
    pattern = _FIELD_RE_CACHE.get(label)
    if pattern is None:
        # Anchor to line start so "Location:" in the intro sentence
        # ("...date, time and location:") doesn't match before the real field.
        pattern = re.compile(
            rf"^{re.escape(label)}\s*:\s*(.+?)\s*$", re.MULTILINE
        )
        _FIELD_RE_CACHE[label] = pattern
    m = pattern.search(text)
    return m.group(1).strip() if m else None


def _parse_groups(s: str) -> tuple[int, ...]:
    # Accept "104, 107, 109, 116 and 120" or "617, 624 and 626" or "1,2,3"
    cleaned = re.sub(r"\band\b", ",", s, flags=re.IGNORECASE)
    out: list[int] = []
    for part in cleaned.split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return tuple(out)


def _parse_date(s: str) -> date | None:
    # Expected format: "Monday, April 20, 2026"
    for fmt in ("%A, %B %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None
