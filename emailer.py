"""Send notification emails via SMTP, with HTML + plain-text alternatives.

Configure via env vars:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM

For Resend: SMTP_HOST=smtp.resend.com SMTP_PORT=465 SMTP_USER=resend SMTP_PASSWORD=<api_key>
For Gmail app password: SMTP_HOST=smtp.gmail.com SMTP_PORT=465 SMTP_USER=<you> SMTP_PASSWORD=<app_pw>

If SMTP_HOST is unset (dev), emails are written to stdout. Production refuses.
"""

from __future__ import annotations

import html
import os
import smtplib
import ssl
from email.message import EmailMessage


# Palette matches templates/form.html
_TEAL = "#1aa692"
_NAVY = "#1f2a3c"
_INK = "#1a2432"
_MUTED = "#6a7381"
_BORDER = "#d8dde3"
_TILE_BG = "#f7f9fb"


def send(to: str, subject: str, text: str, html_body: str | None = None) -> None:
    host = os.environ.get("SMTP_HOST")
    if not host:
        if os.environ.get("JURY_ENV") == "production":
            raise RuntimeError(
                "SMTP_HOST is not set but JURY_ENV=production. Refusing to "
                "print emails to stdout in production (would leak PII to logs)."
            )
        print(f"[DEV EMAIL] To: {to}\nSubject: {subject}\n\n{text}\n")
        return

    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    sender = os.environ.get("SMTP_FROM", user)

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=ctx) as s:
        s.login(user, password)
        s.send_message(msg)


# --- Notification (group called) -------------------------------------------


def notification_body(
    group_number: int,
    court_day: str,
    time_text: str,
    location: str,
    unsubscribe_url: str | None = None,
) -> str:
    footer = f"\nUnsubscribe: {unsubscribe_url}\n" if unsubscribe_url else ""
    return (
        f"Your SF jury duty group ({group_number}) has been called to report.\n\n"
        f"Date: {court_day}\n"
        f"Time: {time_text}\n"
        f"Location: {location}\n\n"
        f"Source: https://sf.courts.ca.gov/divisions/jury-reporting-instructions\n"
        + footer
    )


def notification_html(
    group_number: int,
    court_day: str,
    time_text: str,
    location: str,
    unsubscribe_url: str | None = None,
) -> str:
    rows = _details_rows(
        [
            ("GROUP NUMBER", str(group_number)),
            ("DATE", court_day),
            ("TIME", time_text),
            ("LOCATION", location),
        ]
    )
    unsub_html = (
        f'<p style="margin:14px 0 0; font-size:12px; color:{_MUTED};">'
        f'No longer need these notifications? '
        f'<a href="{html.escape(unsubscribe_url)}" '
        f'style="color:{_TEAL}; text-decoration:underline;">Unsubscribe</a>.'
        f"</p>"
        if unsubscribe_url else ""
    )
    body = f"""
      <tr><td style="padding:0 32px;">
        <p style="margin:0 0 8px; font-size:13px; letter-spacing:.22em; color:{_MUTED}; text-transform:uppercase;">You have been called</p>
        <h1 style="margin:0 0 20px; font-size:22px; line-height:1.25; color:{_INK}; font-weight:700;">
          Your jury duty group has been called to report.
        </h1>
        <p style="margin:0 0 24px; font-size:15px; line-height:1.55; color:{_INK};">
          Please review the reporting details below and plan to arrive on time.
        </p>
        {rows}
        <p style="margin:28px 0 0; font-size:13px; color:{_MUTED};">
          Always verify on the
          <a href="https://sf.courts.ca.gov/divisions/jury-reporting-instructions"
             style="color:{_TEAL}; text-decoration:underline;">
            official court page
          </a>
          before traveling.
        </p>
        {unsub_html}
      </td></tr>
    """
    return _wrap("SF JURY DUTY · REPORTING NOTICE", body)


# --- Confirmation (signup) --------------------------------------------------


def confirmation_body(
    group_number: int,
    week_start: str,
    unsubscribe_url: str | None = None,
) -> str:
    footer = f"\nUnsubscribe: {unsubscribe_url}\n" if unsubscribe_url else ""
    return (
        "You're signed up for SF jury duty reporting notifications.\n\n"
        f"Group number: {group_number}\n"
        f"Week of service: {week_start}\n\n"
        "We'll check the SF court page every court day in the afternoon, from\n"
        "the Friday before your week through Thursday of your week. If your\n"
        "group is called, you'll receive an email with the date, time, and\n"
        "location.\n"
        + footer
    )


def confirmation_html(
    group_number: int,
    week_start: str,
    unsubscribe_url: str | None = None,
) -> str:
    rows = _details_rows(
        [
            ("GROUP NUMBER", str(group_number)),
            ("WEEK OF SERVICE", week_start),
        ]
    )
    unsub_html = (
        f'<p style="margin:14px 0 0; font-size:12px; color:{_MUTED};">'
        f'Changed your mind? '
        f'<a href="{html.escape(unsubscribe_url)}" '
        f'style="color:{_TEAL}; text-decoration:underline;">Unsubscribe</a>.'
        f"</p>"
        if unsubscribe_url else ""
    )
    body = f"""
      <tr><td style="padding:0 32px;">
        <p style="margin:0 0 8px; font-size:13px; letter-spacing:.22em; color:{_MUTED}; text-transform:uppercase;">Registration confirmed</p>
        <h1 style="margin:0 0 20px; font-size:22px; line-height:1.25; color:{_INK}; font-weight:700;">
          You're signed up for jury duty notifications.
        </h1>
        <p style="margin:0 0 24px; font-size:15px; line-height:1.55; color:{_INK};">
          We'll check the Superior Court website every court day in the
          afternoon, from the Friday before your week through Thursday of your
          week. If your group is called, we'll email you the date, time, and
          location.
        </p>
        {rows}
        {unsub_html}
      </td></tr>
    """
    return _wrap("SF JURY DUTY · REGISTRATION CONFIRMED", body)


# --- Weekly summary (owner) ------------------------------------------------


def summary_body(summary: dict) -> str:
    def row(label: str, d: dict) -> str:
        return f"{label:<22} week: {d['week']:<5}  all-time: {d['all_time']}"

    return (
        "sfjuryalert.com weekly summary\n\n"
        + row("Site views", summary["views"]) + "\n"
        + row("Registrations", summary["registrations"]) + "\n"
        + row("Emails sent", summary["emails_sent"]) + "\n"
        + row("Notifications (calls)", summary["notifications"]) + "\n"
    )


def summary_html(summary: dict) -> str:
    header = f"""
      <tr>
        <th style="padding:12px 16px; border:1px solid {_BORDER}; background:{_TILE_BG};
                   text-align:left; font-size:11px; letter-spacing:.2em; color:{_MUTED};
                   text-transform:uppercase; font-weight:600;">Metric</th>
        <th style="padding:12px 16px; border:1px solid {_BORDER}; background:{_TILE_BG};
                   text-align:right; font-size:11px; letter-spacing:.2em; color:{_MUTED};
                   text-transform:uppercase; font-weight:600; width:22%;">This week</th>
        <th style="padding:12px 16px; border:1px solid {_BORDER}; background:{_TILE_BG};
                   text-align:right; font-size:11px; letter-spacing:.2em; color:{_MUTED};
                   text-transform:uppercase; font-weight:600; width:22%;">All time</th>
      </tr>
    """

    def row(label: str, d: dict) -> str:
        return f"""
          <tr>
            <td style="padding:14px 16px; border:1px solid {_BORDER};
                       font-size:15px; color:{_INK};">{html.escape(label)}</td>
            <td style="padding:14px 16px; border:1px solid {_BORDER};
                       font-size:18px; color:{_INK}; text-align:right; font-variant-numeric:tabular-nums;">
              {d['week']}
            </td>
            <td style="padding:14px 16px; border:1px solid {_BORDER};
                       font-size:18px; color:{_MUTED}; text-align:right; font-variant-numeric:tabular-nums;">
              {d['all_time']}
            </td>
          </tr>
        """

    table = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%; border-collapse:collapse; margin:8px 0 0;">'
        + header
        + row("Site views", summary["views"])
        + row("Registrations", summary["registrations"])
        + row("Emails sent", summary["emails_sent"])
        + row("Notifications (groups called)", summary["notifications"])
        + "</table>"
    )

    body = f"""
      <tr><td style="padding:0 32px;">
        <p style="margin:0 0 8px; font-size:13px; letter-spacing:.22em; color:{_MUTED}; text-transform:uppercase;">Weekly summary</p>
        <h1 style="margin:0 0 20px; font-size:22px; line-height:1.25; color:{_INK}; font-weight:700;">
          sfjuryalert.com usage
        </h1>
        <p style="margin:0 0 20px; font-size:15px; line-height:1.55; color:{_INK};">
          Counts for the last 7 days alongside the all-time totals.
        </p>
        {table}
      </td></tr>
    """
    return _wrap("SF JURY DUTY · WEEKLY SUMMARY", body)


# --- Structure-change alert (owner) ----------------------------------------


def structure_change_body(old_fp: str | None, new_fp: str) -> str:
    return (
        "The SF court jury reporting page's HTML structure has changed.\n\n"
        "The scraper may or may not still work. Please verify by visiting:\n"
        "https://sf.courts.ca.gov/divisions/jury-reporting-instructions\n\n"
        f"Previous fingerprint: {old_fp or '(none — first recording)'}\n"
        f"New fingerprint:      {new_fp}\n\n"
        "This alert fires once per distinct structural fingerprint, so you\n"
        "won't get spammed for routine content updates (dates, group numbers).\n"
    )


def structure_change_html(old_fp: str | None, new_fp: str) -> str:
    rows = _details_rows(
        [
            ("PREVIOUS FINGERPRINT", old_fp or "(none — first recording)"),
            ("NEW FINGERPRINT", new_fp),
        ]
    )
    body = f"""
      <tr><td style="padding:0 32px;">
        <p style="margin:0 0 8px; font-size:13px; letter-spacing:.22em; color:{_MUTED}; text-transform:uppercase;">Scraper alert</p>
        <h1 style="margin:0 0 20px; font-size:22px; line-height:1.25; color:{_INK}; font-weight:700;">
          The court page's HTML structure changed.
        </h1>
        <p style="margin:0 0 20px; font-size:15px; line-height:1.55; color:{_INK};">
          The scraper may or may not still work. Please verify by visiting
          the
          <a href="https://sf.courts.ca.gov/divisions/jury-reporting-instructions"
             style="color:{_TEAL}; text-decoration:underline;">reporting
             instructions page</a> and re-checking that the parser still
          extracts group numbers, dates, times, and locations.
        </p>
        {rows}
        <p style="margin:20px 0 0; font-size:13px; color:{_MUTED};">
          This alert fires once per distinct structural fingerprint, so
          routine content updates won't trigger it.
        </p>
      </td></tr>
    """
    return _wrap("SF JURY DUTY · SCRAPER ALERT", body)


# --- Consecutive-failure alert (owner) -------------------------------------


def scrape_failure_alert_body(streak: int, last_error: str | None) -> str:
    return (
        f"The SF court jury scraper has failed {streak} times in a row.\n\n"
        "Please check the site and the Vercel function logs:\n"
        "https://sf.courts.ca.gov/divisions/jury-reporting-instructions\n\n"
        f"Most recent error:\n{last_error or '(no error recorded)'}\n\n"
        "This alert fires once per streak of 3 and will not repeat until a\n"
        "successful scrape resets the counter.\n"
    )


def scrape_failure_alert_html(streak: int, last_error: str | None) -> str:
    rows = _details_rows(
        [
            ("CONSECUTIVE FAILURES", str(streak)),
            ("MOST RECENT ERROR", last_error or "(no error recorded)"),
        ]
    )
    body = f"""
      <tr><td style="padding:0 32px;">
        <p style="margin:0 0 8px; font-size:13px; letter-spacing:.22em; color:{_MUTED}; text-transform:uppercase;">Scraper alert</p>
        <h1 style="margin:0 0 20px; font-size:22px; line-height:1.25; color:{_INK}; font-weight:700;">
          The scraper has failed {streak} times in a row.
        </h1>
        <p style="margin:0 0 20px; font-size:15px; line-height:1.55; color:{_INK};">
          Subscribers may miss notifications until this is fixed. Check the
          <a href="https://sf.courts.ca.gov/divisions/jury-reporting-instructions"
             style="color:{_TEAL}; text-decoration:underline;">court page</a>
          and the Vercel function logs.
        </p>
        {rows}
        <p style="margin:20px 0 0; font-size:13px; color:{_MUTED};">
          This alert fires once per streak of 3 and won't repeat until a
          successful scrape resets the counter.
        </p>
      </td></tr>
    """
    return _wrap("SF JURY DUTY · SCRAPER ALERT", body)


# --- Shared layout ---------------------------------------------------------


def _details_rows(pairs: list[tuple[str, str]]) -> str:
    cells = []
    for label, value in pairs:
        cells.append(
            f"""
            <tr>
              <td style="padding:14px 16px; border:1px solid {_BORDER}; background:{_TILE_BG};
                         width:40%; font-size:11px; letter-spacing:.22em;
                         color:{_MUTED}; text-transform:uppercase; vertical-align:top;">
                {html.escape(label)}
              </td>
              <td style="padding:14px 16px; border:1px solid {_BORDER};
                         font-size:15px; color:{_INK}; vertical-align:top;">
                {html.escape(value)}
              </td>
            </tr>
            """
        )
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%; border-collapse:collapse; margin:8px 0 0;">'
        + "".join(cells)
        + "</table>"
    )


def _wrap(header_text: str, inner_rows: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SF Jury Duty</title>
</head>
<body style="margin:0; padding:0; background:#f3f5f8;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
             color:{_INK};">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0"
         width="100%" style="background:#f3f5f8; padding:32px 12px;">
    <tr><td align="center">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0"
             width="600" style="max-width:600px; width:100%; background:#ffffff;
                                 border:1px solid {_BORDER};">
        <tr>
          <td style="background:{_TEAL}; color:#ffffff; padding:18px 32px;
                     letter-spacing:.25em; font-size:13px; font-weight:600;">
            {html.escape(header_text)}
          </td>
        </tr>
        <tr><td style="height:28px; line-height:28px;">&nbsp;</td></tr>
        {inner_rows}
        <tr><td style="height:28px; line-height:28px;">&nbsp;</td></tr>
        <tr>
          <td style="background:{_NAVY}; color:#c9d1dc; padding:18px 32px;
                     font-size:12px; line-height:1.5;">
            This service is not affiliated with the San Francisco Superior Court.
            Always verify reporting requirements through official channels.
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
