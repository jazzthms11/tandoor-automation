"""Der Schritt, der wirklich schreibt.

Zwei Dinge sind hier teuer, wenn sie still schiefgehen: ein Zeitstempel ohne Uhrzeit landet als
Mahlzeit um Mitternacht in Tandoor, und ein nicht erkannter Zwilling legt die Woche ein zweites
Mal an. Beides fällt erst auf, wenn der Plan schon steht.
"""

from datetime import date, datetime, time

from tandoor_automation.apply import describe, match_existing, payload, without
from tandoor_automation.bundle import PlanBundle
from tandoor_automation.models import MealType, PlannedMeal, Recipe
from tandoor_automation.proposal import Proposal, ProposalEntry, validate_proposal

MITTAG, ABEND = 1, 2
MITTAGESSEN = MealType(id=MITTAG, name="Mittagessen", served_at=time(12, 0))
ABENDESSEN = MealType(id=ABEND, name="Abendessen", served_at=time(19, 0))


def _bundle(occupied: list[PlannedMeal]) -> PlanBundle:
    return PlanBundle(
        week="2026-W39",
        days=[date(2026, 9, day) for day in range(21, 28)],
        meal_types=[MITTAGESSEN, ABENDESSEN],
        occupied=occupied,
        history=[],
        recipes=[Recipe(id=1, name="Lasagne", working_time=20, waiting_time=10, servings=4)],
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
