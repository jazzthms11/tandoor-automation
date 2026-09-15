"""Woche zu Tagen, Überschneidung von Planeinträgen und die Lesbarkeit des Bündels.

Beides scheitert still: eine falsch gerechnete Woche plant sieben richtige Gerichte auf die
falschen Tage, und eine übersehene Überschneidung überschreibt einen belegten Platz.
"""

from datetime import date

import pytest

from tandoor_automation.bundle import (
    PlanBundle,
    build_bundle,
    next_week,
    overlaps,
    parse_week,
    week_days,
)
from tandoor_automation.models import MealType, PlannedMeal, Recipe
from tandoor_automation.tandoor import TandoorClient


def meal(from_date: str, to_date: str) -> PlannedMeal:
    return PlannedMeal(
        id=1,
        from_date=f"{from_date}T12:00:00+02:00",
        to_date=f"{to_date}T12:00:00+02:00",
        meal_type_name="Mittagessen",
        servings=2,
    )


class FakeTandoor(TandoorClient):
    """Ein Client ohne HTTP, der den letzten abgefragten Tag mitschreibt."""

    def __init__(self, meals):
        self.meals = meals
        self.last_day = date.min

    def meal_plan(self, start, end):
        self.last_day = end
        return self.meals

    def meal_types(self):
        return []

    def recipes(self):
        return []


def test_sonntagabend_der_woche_steht_schon_als_belegt_im_buendel():
    """Der Sonntagabend reicht bis zum Montag danach und fiel deshalb aus der Abfrage.

    Folge war ein `plan apply`, das beim zweiten Lauf genau diesen einen Eintrag nicht wiederfand
    und ihn ein zweites Mal anlegte.
    """
    sonntagabend = meal("2026-09-27", "2026-09-28")
    tandoor = FakeTandoor([sonntagabend])
    bundle = build_bundle(tandoor, "2026-W39")
    assert tandoor.last_day == date(2026, 9, 28)
    assert bundle.occupied == [sonntagabend]


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


def test_buendel_liest_sich_selbst_wieder_ein() -> None:
    """Die Modelle müssen beide Formen lesen, Tandoors Antwort und das daraus geschriebene Bündel.

    Fällt das auseinander, schreibt `plan bundle` eine Datei, die `plan check` nicht mehr öffnen
    kann, und der Fehler fällt erst am Donnerstag beim Planen auf.
    """
    aus_tandoor = PlanBundle(
        week="2026-W39",
        days=[date(2026, 9, day) for day in range(21, 28)],
        meal_types=[MealType.model_validate({"id": 1, "name": "Mittagessen", "time": "12:00:00"})],
        occupied=[],
        history=[
            PlannedMeal.model_validate(
                {
                    "id": 1,
                    "from_date": "2026-09-14T12:00:00+02:00",
                    "to_date": "2026-09-18T12:00:00+02:00",
                    "meal_type_name": "Mittagessen",
                    "recipe": {"id": 11},
                    "recipe_name": "Lasagne vegetarisch",
                    "servings": 5,
                }
            )
        ],
        recipes=[
            Recipe.model_validate(
                {
                    "id": 11,
                    "name": "Lasagne vegetarisch",
                    "description": None,
                    "keywords": [{"label": "Vegetarisch"}],
                    "working_time": 30,
                    "waiting_time": 35,
                    "servings": 5,
                }
            )
        ],
    )
    assert PlanBundle.model_validate_json(aus_tandoor.model_dump_json()) == aus_tandoor
