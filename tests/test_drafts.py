"""Tests für den Entwurf über das Modell und seine Änderung von Hand.

Still teuer wird hier zweierlei: ein Mangel, der nicht ans Modell zurückgeht und im Entwurf
stehen bleibt, und eine Tauschliste, die gegen die Abstände der Bewertung verstößt. Die zweite
sieht man ihr nicht an, man glaubt ihr.
"""

import json
from datetime import date, datetime
from typing import cast

import pytest

from tandoor_automation import drafts
from tandoor_automation.bundle import PlanBundle
from tandoor_automation.chooser import Answer, ChosenEntry
from tandoor_automation.models import MealType, PlannedMeal, Recipe
from tandoor_automation.tandoor import TandoorClient

MITTAG, ABEND = 1, 2
WOCHE = "2026-W42"
NOTEN = {1: 5, 2: 5, 3: 5, 4: 5, 5: 5, 6: 5, 7: 5, 9: 4, 10: 5, 11: 1, 12: 5, 13: 3}
SCHLAGWORTE = {12: ["Beilage"], 13: ["Vegetarisch"]}
WOCHE_DAVOR = datetime(2026, 10, 5, 19)


@pytest.fixture(autouse=True)
def datenordner(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))


def _bundle() -> PlanBundle:
    """Samstag, der 10., bis Freitag, der 16. Oktober 2026, 9 und 10 standen letzte Woche da."""
    return PlanBundle(
        week=WOCHE,
        days=[date(2026, 10, day) for day in range(10, 17)],
        meal_types=[
            MealType(id=MITTAG, name="Mittagessen", served_at="12:00:00"),
            MealType(id=ABEND, name="Abendessen", served_at="19:00:00"),
        ],
        occupied=[],
        history=[
            PlannedMeal(
                id=100 + recipe_id,
                from_date=WOCHE_DAVOR,
                to_date=WOCHE_DAVOR,
                meal_type_name="Abendessen",
                recipe_id=recipe_id,
                recipe_name=f"Gericht {recipe_id}",
                servings=2,
            )
            for recipe_id in (9, 10)
        ],
        recipes=[
            Recipe(
                id=recipe_id,
                name=f"Gericht {recipe_id}",
                keywords=SCHLAGWORTE.get(recipe_id, []),
                working_time=20,
                waiting_time=0,
                servings=2,
                rating=stars,
            )
            for recipe_id, stars in NOTEN.items()
        ],
    )


def _eintrag(recipe_id: int, meal_type: int, first: int, last: int, servings: float):
    return ChosenEntry(
        recipe_id=recipe_id,
        recipe_name=f"Gericht {recipe_id}",
        meal_type_id=meal_type,
        from_date=date(2026, 10, first),
        to_date=date(2026, 10, last),
        servings=servings,
    )


WOCHENFORM = [
    _eintrag(1, MITTAG, 10, 10, 2),
    _eintrag(2, ABEND, 10, 10, 2),
    _eintrag(2, MITTAG, 11, 11, 2),
    _eintrag(3, ABEND, 11, 12, 4),
    _eintrag(4, MITTAG, 12, 16, 5),
    _eintrag(5, MITTAG, 12, 16, 5),
    _eintrag(6, ABEND, 13, 14, 4),
    _eintrag(7, ABEND, 15, 16, 4),
]


class Modell:
    """Antwortet der Reihe nach mit den vorbereiteten Einträgen und merkt sich die Verläufe."""

    def __init__(self, *antworten):
        self.antworten = list(antworten)
        self.verlaeufe = []

    def __call__(self, system, turns, schema):
        self.verlaeufe.append(turns)
        entries = self.antworten.pop(0)
        return Answer(reasoning="Begründung", entries=entries).model_dump_json()


def _entwurf(monkeypatch, *antworten):
    monkeypatch.setattr(drafts, "build_bundle", lambda tandoor, week: _bundle())
    modell = Modell(*antworten)
    return drafts.create(cast(TandoorClient, None), modell, WOCHE, ""), modell


def test_maengel_gehen_einmal_ans_modell_zurueck(monkeypatch):
    entwurf, modell = _entwurf(monkeypatch, WOCHENFORM[:-1], WOCHENFORM)
    assert entwurf.problems == []
    assert len(modell.verlaeufe) == 2
    assert "2026-10-16 Abendessen" in modell.verlaeufe[1][-1].text


def test_bleibende_maengel_stehen_im_entwurf(monkeypatch):
    entwurf, _ = _entwurf(monkeypatch, WOCHENFORM[:-1], WOCHENFORM[:-1])
    assert entwurf.problems
    gespeichert = drafts.store.draft(WOCHE)
    assert gespeichert is not None
    assert json.loads(gespeichert.problems) == entwurf.problems


def test_tauschliste_haelt_abstand_und_sperren_ein(monkeypatch):
    entwurf, _ = _entwurf(monkeypatch, WOCHENFORM)
    namen = [kandidat.recipe.id for kandidat in drafts.candidates(entwurf, 6)]
    assert namen == [13, 10]
    gesucht = {k.recipe.id: k.allowed for k in drafts.candidates(entwurf, 6, "gericht")}
    assert gesucht[9] is False
    assert gesucht[11] is False


def test_tausch_nimmt_das_paar_vom_wochenende_mit(monkeypatch):
    entwurf, _ = _entwurf(monkeypatch, WOCHENFORM)
    neu = drafts.replace_recipe(WOCHE, entwurf.version, 1, 13)
    assert [entry.recipe_id for entry in neu.proposal.entries[1:3]] == [13, 13]
    with pytest.raises(drafts.store.StaleDraftError):
        drafts.replace_recipe(WOCHE, entwurf.version, 1, 10)
