from datetime import date
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper import parse  # noqa: E402


FIXTURE = Path(__file__).parent / "fixtures" / "page.html"


def test_parses_report_blocks():
    html = FIXTURE.read_text(encoding="utf-8")
    blocks = parse(html)

    assert len(blocks) == 3, f"expected 3 report-in-person blocks, got {len(blocks)}"

    civic = blocks[0]
    assert civic.group_numbers == (104, 107, 109, 116, 120)
    assert civic.court_day == date(2026, 4, 20)
    assert civic.time_text == "8:30 a.m."
    assert "400 McAllister" in civic.location

    hoj_am = blocks[1]
    assert hoj_am.group_numbers == (617, 624, 626)
    assert hoj_am.time_text == "9:00 a.m."
    assert "850 Bryant" in hoj_am.location

    hoj_pm = blocks[2]
    assert hoj_pm.group_numbers == (604, 615, 622, 627)
    assert hoj_pm.time_text == "12:30 p.m."


def test_ignores_standby_and_already_reported():
    html = FIXTURE.read_text(encoding="utf-8")
    all_groups = {g for b in parse(html) for g in b.group_numbers}
    # Standby groups from the fixture must not appear
    for standby in (101, 102, 103, 601, 602, 625):
        assert standby not in all_groups


if __name__ == "__main__":
    test_parses_report_blocks()
    test_ignores_standby_and_already_reported()
    print("scraper tests passed")
