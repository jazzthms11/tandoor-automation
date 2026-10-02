"""Der Schritt, der wirklich schreibt.

Zwei Dinge sind hier teuer, wenn sie still schiefgehen: ein Zeitstempel ohne Uhrzeit landet als
Mahlzeit um Mitternacht in Tandoor, und ein nicht erkannter Zwilling legt die Woche ein zweites
Mal an. Beides fällt erst auf, wenn der Plan schon steht.
"""

from datetime import date, datetime, time

from tandoor_automation.apply import (
    clearable,
    describe,
    match_existing,
    note_of,
    payload,
    share_problems,
    slot_of,
    split_groups,
    together_of,
    unfold,
    without,
)
from tandoor_automation.bundle import PlanBundle
from tandoor_automation.models import MealType, PlannedMeal, Recipe
from tandoor_automation.proposal import MARKS, Proposal, ProposalEntry, validate_proposal

MITTAG, ABEND = 1, 2
ICH = 1
MITTAGESSEN = MealType(id=MITTAG, name="Mittagessen", served_at=time(12, 0))
ABENDESSEN = MealType(id=ABEND, name="Abendessen", served_at=time(19, 0))


def _bundle(occupied: list[PlannedMeal]) -> PlanBundle:
    return PlanBundle(
        week="2026-W39",
        days=[date(2026, 9, day) for day in range(21, 28)],
        meal_types=[MITTAGESSEN, ABENDESSEN],
        occupied=occupied,
        history=[],
        recipes=[
            Recipe(id=1, name="Lasagne", working_time=20, waiting_time=10, servings=4),
            Recipe(id=2, name="Linsencurry", working_time=20, waiting_time=10, servings=4),
        ],
    )


def _entry() -> ProposalEntry:
    """Ein Mittagessen von Montag bis Freitag, fünf Portionen."""
    return ProposalEntry(
        recipe_id=1,
        recipe_name="Lasagne",
        meal_type_id=MITTAG,
        from_date=date(2026, 9, 21),
        to_date=date(2026, 9, 25),
        servings=5,
    )


def _meal() -> PlannedMeal:
    """Derselbe Eintrag, wie Tandoor ihn nach dem Schreiben zurückgibt."""
    return PlannedMeal(
        id=7,
        from_date=datetime(2026, 9, 21, 12).astimezone(),
        to_date=datetime(2026, 9, 25, 12).astimezone(),
        meal_type_name="Mittagessen",
        recipe_id=1,
        recipe_name="Lasagne",
        servings=5.0,
    )


def test_uhrzeit_der_mahlzeit_steht_im_zeitstempel() -> None:
    body = payload(_entry(), MITTAGESSEN)
    assert body["from_date"] == datetime(2026, 9, 21, 12).astimezone().isoformat()
    assert body["to_date"] == datetime(2026, 9, 25, 12).astimezone().isoformat()


def test_rezept_und_mahlzeit_gehen_verschachtelt_hinein() -> None:
    body = payload(_entry(), MITTAGESSEN)
    assert body["recipe"] == {"id": 1, "name": "Lasagne"}
    assert body["meal_type"] == {"id": MITTAG, "name": "Mittagessen"}


def test_termin_ohne_rezept_geht_ohne_rezept_hinein() -> None:
    entry = _entry().model_copy(
        update={"recipe_id": None, "recipe_name": "", "title": "Urlaub", "servings": 0}
    )
    assert payload(entry, ABENDESSEN)["recipe"] is None


def test_gleicher_eintrag_wird_nicht_zweimal_geschrieben() -> None:
    proposal = Proposal(week="2026-W39", entries=[_entry()])
    matches = match_existing(proposal, _bundle([_meal()]))
    assert matches[0][1] is not None


def test_abweichende_portionen_sind_kein_zwilling() -> None:
    proposal = Proposal(week="2026-W39", entries=[_entry()])
    matches = match_existing(proposal, _bundle([_meal().model_copy(update={"servings": 4.0})]))
    assert matches[0][1] is None


def test_ein_planeintrag_deckt_nur_einen_vorschlagseintrag() -> None:
    proposal = Proposal(week="2026-W39", entries=[_entry(), _entry()])
    matches = match_existing(proposal, _bundle([_meal()]))
    assert [twin is None for _, twin in matches] == [False, True]


def test_der_eigene_erste_lauf_ist_keine_doppelbelegung() -> None:
    proposal = Proposal(week="2026-W39", entries=[_entry()])
    bundle = _bundle([_meal()])
    assert any("trifft auf" in problem for problem in validate_proposal(proposal, bundle))
    twins = [twin for _, twin in match_existing(proposal, bundle) if twin]
    rest = validate_proposal(proposal, without(bundle, twins))
    assert not any("trifft auf" in problem for problem in rest)


def test_fremder_platz_bleibt_eine_doppelbelegung() -> None:
    proposal = Proposal(week="2026-W39", entries=[_entry()])
    urlaub = _meal().model_copy(
        update={"recipe_id": None, "recipe_name": "", "title": "Urlaub", "servings": 0.0}
    )
    bundle = _bundle([urlaub])
    twins = [twin for _, twin in match_existing(proposal, bundle) if twin]
    assert any(
        "trifft auf" in problem for problem in validate_proposal(proposal, without(bundle, twins))
    )


def test_beschreibung_nennt_zeitraum_und_gericht() -> None:
    assert describe(_entry(), MITTAGESSEN) == "2026-09-21 bis 2026-09-25 Mittagessen: Lasagne"
    einer = _entry().model_copy(update={"to_date": date(2026, 9, 21)})
    assert describe(einer, MITTAGESSEN) == "2026-09-21 Mittagessen: Lasagne"


def _planned(meal_id: int, first: int, last: int, owner: int | None) -> PlannedMeal:
    return PlannedMeal(
        id=meal_id,
        title="Reste",
        from_date=datetime(2026, 9, first, 19).astimezone(),
        to_date=datetime(2026, 9, last, 19).astimezone(),
        meal_type_name="Abendessen",
        servings=2.0,
        created_by=owner,
    )


def test_geloescht_wird_nur_was_in_der_woche_beginnt() -> None:
    woche = [date(2026, 9, day) for day in range(19, 26)]
    vorher = _planned(1, 18, 19, ICH)
    drin = _planned(2, 25, 26, ICH)
    danach = _planned(3, 26, 27, ICH)
    mine, others = clearable([vorher, drin, danach], woche, ICH, set())
    assert [meal.id for meal in mine] == [2]
    assert others == []


def test_fremde_eintraege_bleiben_stehen() -> None:
    woche = [date(2026, 9, day) for day in range(19, 26)]
    eigener = _planned(1, 20, 20, ICH)
    fremder = _planned(2, 21, 21, ICH + 1)
    ohne = _planned(3, 22, 22, None)
    mine, others = clearable([eigener, fremder, ohne], woche, ICH, set())
    assert [meal.id for meal in mine] == [1]
    assert [meal.id for meal in others] == [2, 3]


def test_einzelne_ids_schraenken_die_woche_ein() -> None:
    woche = [date(2026, 9, day) for day in range(19, 26)]
    meals = [_planned(1, 20, 20, ICH), _planned(2, 21, 21, ICH)]
    mine, others = clearable(meals, woche, ICH, {2})
    assert [meal.id for meal in mine] == [2]
    assert others == []


LEO, JAZZ = MARKS


def _lunches() -> Proposal:
    """Die beiden vorgekochten Mittagessen, je ein Eintrag von Montag bis Freitag."""
    lasagne = _entry()
    curry = _entry().model_copy(update={"recipe_id": 2, "recipe_name": "Linsencurry"})
    return Proposal(week="2026-W39", entries=[lasagne, curry])


def test_geteilter_platz_zerfaellt_in_einen_eintrag_je_tag_und_esser() -> None:
    entries = unfold(_lunches(), {ABEND}, {}).entries
    assert len(entries) == 10
    assert all(entry.from_date == entry.to_date for entry in entries)
    assert all(entry.servings == 1 for entry in entries)
    assert sorted({tuple(entry.marks) for entry in entries}) == [(JAZZ,), (LEO,)]


def test_jeder_tag_traegt_beide_gerichte_einmal() -> None:
    entries = unfold(_lunches(), {ABEND}, {}).entries
    for day in (date(2026, 9, day) for day in range(21, 26)):
        am_tag = [entry for entry in entries if entry.from_date == day]
        assert sorted(entry.recipe_id or 0 for entry in am_tag) == [1, 2]
        assert sorted(entry.marks[0] for entry in am_tag) == sorted(MARKS)


def test_das_fuehrende_gericht_kommt_bei_fuenf_tagen_dreimal() -> None:
    proposal = _lunches()
    slot = slot_of(proposal.entries[0])
    for lead, name in enumerate(["Lasagne", "Linsencurry"]):
        entries = unfold(proposal, {ABEND}, {slot: lead}).entries
        meins = [entry.recipe_name for entry in entries if entry.marks == [LEO]]
        assert meins.count(name) == 3
        assert len(meins) == 5


def test_einzelnes_mittagessen_traegt_beide_marken() -> None:
    """Der Sonntagmittag: SyncHealth hält ein Mittagessen ohne Marke an."""
    sonntag = _entry().model_copy(update={"to_date": date(2026, 9, 21), "servings": 2})
    entries = unfold(Proposal(week="2026-W39", entries=[sonntag]), {ABEND}, {}).entries
    assert entries[0].marks == list(MARKS)


def test_abendessen_bleibt_ohne_marke() -> None:
    """SyncHealth teilt es auf den Haushalt auf, eine Marke stäche das Feld."""
    abend = _entry().model_copy(
        update={"meal_type_id": ABEND, "to_date": date(2026, 9, 22), "servings": 4}
    )
    plan = unfold(Proposal(week="2026-W39", entries=[abend]), {ABEND}, {})
    assert plan.entries[0].marks == []
    assert share_problems(plan) == []
    knapp = plan.entries[0].model_copy(update={"servings": 2})
    assert len(share_problems(plan.model_copy(update={"entries": [knapp]}))) == 1


def test_abendessen_erkennt_sich_am_namen() -> None:
    assert together_of(_bundle([])) == {ABEND}


def test_termin_ohne_rezept_bleibt_ohne_marke() -> None:
    termin = _entry().model_copy(
        update={"recipe_id": None, "recipe_name": "", "title": "Urlaub", "servings": 0}
    )
    assert unfold(Proposal(week="2026-W39", entries=[termin]), {ABEND}, {}).entries[0].marks == []


def test_beilage_neben_dem_hauptgericht_wird_nicht_entfaltet() -> None:
    """Zwei Einträge auf einem Platz, aber je zwei Portionen am Tag: beide essen beides."""
    haupt = _entry().model_copy(update={"to_date": date(2026, 9, 21), "servings": 2})
    beilage = haupt.model_copy(update={"recipe_id": 2, "recipe_name": "Linsencurry"})
    proposal = Proposal(week="2026-W39", entries=[haupt, beilage])
    assert split_groups(proposal) == {}
    assert [entry.marks for entry in unfold(proposal, {ABEND}, {}).entries] == [
        list(MARKS),
        list(MARKS),
    ]


def test_marken_stehen_in_der_ersten_zeile_der_notiz() -> None:
    entry = _entry().model_copy(update={"marks": [LEO], "note": "mit Sojagranulat"})
    assert payload(entry, MITTAGESSEN)["note"] == f"{LEO}\nmit Sojagranulat"
    assert note_of(_entry().model_copy(update={"marks": list(MARKS)})) == f"{LEO} {JAZZ}"


def test_entfaltete_mittagessen_decken_ihre_tage() -> None:
    """Zehn Einträge zu einer Portion tragen die Woche genauso wie zwei zu fünf."""
    problems = validate_proposal(unfold(_lunches(), {ABEND}, {}), _bundle([]))
    gedeckt = [f"2026-09-{day} Mittagessen" for day in range(21, 26)]
    assert not [problem for problem in problems if problem.startswith(tuple(gedeckt))]


def test_eine_andere_marke_ist_kein_zwilling() -> None:
    entry = _entry().model_copy(update={"marks": [LEO]})
    meal = _meal().model_copy(update={"note": JAZZ})
    proposal = Proposal(week="2026-W39", entries=[entry])
    assert match_existing(proposal, _bundle([meal]))[0][1] is None
    assert match_existing(proposal, _bundle([meal.model_copy(update={"note": LEO})]))[0][1]


def test_beschreibung_nennt_die_marke() -> None:
    entry = _entry().model_copy(update={"marks": [LEO], "to_date": date(2026, 9, 21)})
    assert describe(entry, MITTAGESSEN) == f"2026-09-21 Mittagessen: Lasagne {LEO}"


def test_ungleiche_zeitraeume_halbieren_keinen_anteil_still() -> None:
    """Zwei Mittagsgerichte über verschiedene Zeiträume sind kein geteilter Platz."""
    kurz = _entry().model_copy(
        update={"recipe_id": 2, "recipe_name": "Linsencurry", "to_date": date(2026, 9, 24)}
    )
    plan = unfold(Proposal(week="2026-W39", entries=[_entry(), kurz]), {ABEND}, {})
    assert [entry.marks for entry in plan.entries] == [list(MARKS), list(MARKS)]
    assert len(share_problems(plan)) == 2


def test_der_normalfall_meldet_keinen_anteil() -> None:
    assert share_problems(unfold(_lunches(), {ABEND}, {})) == []
