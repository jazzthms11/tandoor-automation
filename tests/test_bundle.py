"""Woche zu Tagen und Überschneidung von Planeinträgen.

Beides scheitert still: eine falsch gerechnete Woche plant sieben richtige Gerichte auf die
falschen Tage, und eine übersehene Überschneidung überschreibt einen belegten Platz.
"""

from datetime import date

import pytest

from kueche.bundle import next_week, overlaps, parse_week, week_days
from kueche.models import PlannedMeal


def meal(from_date: str, to_date: str) -> PlannedMeal:
    return PlannedMeal(
        id=1,
        from_date=f"{from_date}T12:00:00+02:00",
        to_date=f"{to_date}T12:00:00+02:00",
        meal_type_name="Mittagessen",
        servings=2,
    )


def test_woche_beginnt_montag_und_endet_sonntag():
    days = week_days("2026-W38")
    assert days[0] == date(2026, 9, 14)
    assert days[-1] == date(2026, 9, 20)
    assert len(days) == 7


def test_woche_ueber_den_jahreswechsel():
    assert week_days("2027-W01")[0] == date(2027, 1, 4)


@pytest.mark.parametrize("week", ["2026-38", "2026-W", "W38-2026", "2026-W99"])
def test_unbrauchbare_woche_wirft(week):
    with pytest.raises(ValueError):
        parse_week(week)


def test_naechste_woche_ueber_den_jahreswechsel():
    assert next_week(date(2026, 12, 29)) == "2027-W01"


def test_eintrag_ragt_mit_seinem_ende_in_die_woche():
    assert overlaps(meal("2026-09-11", "2026-09-15"), date(2026, 9, 14), date(2026, 9, 20))


def test_eintrag_ragt_mit_seinem_anfang_in_die_woche():
    assert overlaps(meal("2026-09-20", "2026-09-23"), date(2026, 9, 14), date(2026, 9, 20))


def test_eintrag_umschliesst_die_woche():
    assert overlaps(meal("2026-09-01", "2026-09-30"), date(2026, 9, 14), date(2026, 9, 20))


@pytest.mark.parametrize(
    ("from_date", "to_date"),
    [("2026-09-08", "2026-09-13"), ("2026-09-21", "2026-09-25")],
)
def test_eintrag_daneben_ragt_nicht_hinein(from_date, to_date):
    assert not overlaps(meal(from_date, to_date), date(2026, 9, 14), date(2026, 9, 20))
