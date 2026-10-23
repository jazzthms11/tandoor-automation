"""Die Rückfrage vor dem Einkauf.

Geprüft wird, wer gefragt wird und was die Antwort auslöst. Ein Fehler darin bleibt still: eine
Frage zu wenig kauft nichts nach, eine Frage zu viel nervt, und beides fällt erst im Laden auf.
"""

from datetime import date, timedelta
from decimal import Decimal

from tandoor_automation.classes import Placement, StockFood, unclassified
from tandoor_automation.models import Food, InventoryEntry, PlannedMeal, RecipeDetail
from tandoor_automation.shopping import (
    buy_list,
    confirmed_until,
    describe_need,
    needs,
    parse_intervals,
    review,
)

TODAY = date(2026, 9, 22)
UNITS = {1: "Stück"}
TOMATEN, BEEREN, BUTTER, SALAT = 10, 20, 30, 40
STOCK = {
    TOMATEN: StockFood("Passierte Tomaten", "Küchenschrank", "rezept"),
    BEEREN: StockFood("TK-Beeren", "Gefrierschrank", "rezept"),
    BUTTER: StockFood("Butter", "Kühlschrank", "vorrat"),
}
FRESH = {SALAT: StockFood("Kopfsalat", "", "frisch")}


def _entry(entry_id: int, food_id: int, amount: str, expires: date | None = None) -> InventoryEntry:
    return InventoryEntry.model_validate(
        {
            "id": entry_id,
            "food": {"id": food_id},
            "unit": {"id": 1},
            "amount": amount,
            "expires": expires.isoformat() if expires else None,
        }
    )


def _review(planned: set[int], entries: list[InventoryEntry]):
    return review(planned, entries, STOCK, FRESH, UNITS, TODAY)


def test_rezeptware_wird_nur_gefragt_wenn_die_woche_sie_braucht():
    entries = [_entry(1, TOMATEN, "8"), _entry(2, BEEREN, "2")]
    found = _review({TOMATEN}, entries)
    assert [question.food_id for question in found.questions] == [TOMATEN]


def test_vorratsware_fragt_die_zeit_und_nicht_der_plan():
    getragen = _entry(1, BUTTER, "1", TODAY + timedelta(days=7))
    assert _review(set(), [getragen]).questions == []
    durch = _entry(1, BUTTER, "1", TODAY - timedelta(days=1))
    assert [question.food_id for question in _review(set(), [durch]).questions] == [BUTTER]


def test_ungebuchte_vorratsware_wird_beim_ersten_mal_gefragt():
    assert len(_review(set(), [_entry(1, BUTTER, "1")]).questions) == 1


def test_die_staffel_kommt_aus_der_gebuchten_menge():
    [frage] = _review({TOMATEN}, [_entry(1, TOMATEN, "8")]).questions
    assert [choice.amount for choice in frage.choices] == [Decimal(8), Decimal(4), Decimal(1), 0]
    assert [choice.buys for choice in frage.choices] == [False, False, True, True]


def test_kleine_bestaende_bekommen_keine_doppelten_stufen():
    [frage] = _review({BEEREN}, [_entry(1, BEEREN, "2")]).questions
    assert [choice.label for choice in frage.choices] == ["noch 2", "nur noch 1", "leer"]


def test_letzte_packung_rezeptware_wird_nicht_gefragt_sondern_gekauft():
    found = _review({TOMATEN}, [_entry(1, TOMATEN, "1")])
    assert found.questions == []
    assert [item.food_id for item in found.unasked] == [TOMATEN]


def test_frischware_der_woche_geht_ungefragt_auf_die_liste():
    found = _review({SALAT}, [])
    assert found.questions == []
    assert [item.food_id for item in found.unasked] == [SALAT]


def test_unbeantwortete_frage_kauft():
    found = _review({TOMATEN}, [_entry(1, TOMATEN, "8")])
    assert [item.food_id for item in buy_list(found, {})] == [TOMATEN]


def test_bestaetigter_bestand_kommt_nicht_auf_die_liste():
    found = _review({TOMATEN}, [_entry(1, TOMATEN, "8")])
    [frage] = found.questions
    assert buy_list(found, {frage.entry_id: frage.choices[0]}) == []


def test_geleerter_bestand_kommt_auf_die_liste():
    found = _review({TOMATEN}, [_entry(1, TOMATEN, "8")])
    [frage] = found.questions
    assert [item.food_id for item in buy_list(found, {frage.entry_id: frage.choices[-1]})] == [
        TOMATEN
    ]


def test_ungefuehrte_lebensmittel_bleiben_aussen_vor():
    assert _review({99}, []) == _review(set(), [])


def test_leere_vorratsware_kommt_auch_ohne_rezept_auf_die_liste():
    found = _review(set(), [_entry(1, BUTTER, "0", TODAY - timedelta(days=1))])
    assert found.questions == []
    assert [item.food_id for item in found.unasked] == [BUTTER]


def test_getragene_vorratsware_kommt_auch_im_plan_nicht_auf_die_liste():
    found = _review({BUTTER}, [_entry(1, BUTTER, "1", TODAY + timedelta(days=7))])
    assert found.questions == []
    assert found.unasked == []


def test_zeile_ohne_intervall_verschiebt_die_spalten_nicht():
    intervals = parse_intervals("# Kopf\n7\t10\tQuark\tMedian 9\n\t20\tHonig\tkeine Käufe\n")
    assert intervals == {10: 7}


def test_faellig_ist_was_bis_sonntag_ablaeuft():
    """Was Freitag abläuft, gehört schon auf die Liste vom Dienstag."""
    sonntag = _entry(1, BUTTER, "1", date(2026, 9, 27))
    assert [question.food_id for question in _review(set(), [sonntag]).questions] == [BUTTER]
    montag = _entry(1, BUTTER, "1", date(2026, 9, 28))
    assert _review(set(), [montag]).questions == []


def test_intervalle_werden_auf_ganze_wochen_abgerundet():
    intervals = {10: 10, 20: 3}
    assert confirmed_until(TODAY, 10, intervals) == TODAY + timedelta(days=7)
    assert confirmed_until(TODAY, 20, intervals) == TODAY + timedelta(days=7)


def test_ohne_eigenes_intervall_gilt_der_rueckfall():
    intervals = parse_intervals("7\t10\tQuark\n")
    assert confirmed_until(TODAY, 10, intervals) == TODAY + timedelta(days=7)
    assert confirmed_until(TODAY, 99, intervals) == TODAY + timedelta(days=14)


def test_zwei_bestandseintraege_ergeben_eine_zeile_auf_der_liste():
    """Nach Gewicht und nach Stück gekauft heißt zwei Einträge, aber ein Artikel im Wagen."""
    found = _review(set(), [_entry(1, BUTTER, "0"), _entry(2, BUTTER, "0")])
    assert [item.food_name for item in buy_list(found, {})] == ["Butter"]


def _meal(recipe_id: int, servings: float) -> PlannedMeal:
    return PlannedMeal.model_validate(
        {
            "id": 1,
            "from_date": "2026-09-26T19:00:00+02:00",
            "to_date": "2026-09-26T19:00:00+02:00",
            "meal_type_name": "Abendessen",
            "recipe": {"id": recipe_id},
            "servings": servings,
        }
    )


def _detail(recipe_id: int, name: str, servings: int, amount: str, unit: str) -> RecipeDetail:
    return RecipeDetail.model_validate(
        {
            "id": recipe_id,
            "name": name,
            "servings": servings,
            "ingredients": [{"food": {"id": TOMATEN}, "amount": amount, "unit": {"name": unit}}],
        }
    )


def test_bedarf_rechnet_auf_die_geplanten_portionen_hoch():
    """Ein Rezept für vier, das mit fünf Portionen im Plan steht, braucht ein Viertel mehr."""
    details = {1: _detail(1, "Chili", 4, "400", "g")}
    found = needs([_meal(1, 5)], details)
    assert found[TOMATEN].amounts == {"g": Decimal("500")}


def test_dasselbe_gericht_zweimal_zaehlt_zweimal_und_steht_einmal():
    details = {1: _detail(1, "Chili", 4, "400", "g")}
    found = needs([_meal(1, 4), _meal(1, 2)], details)
    assert found[TOMATEN].amounts == {"g": Decimal("600")}
    assert list(found[TOMATEN].recipes) == ["Chili"]


def test_verschiedene_einheiten_bleiben_getrennt():
    details = {1: _detail(1, "Chili", 4, "400", "g"), 2: _detail(2, "Suppe", 4, "2", "Stück")}
    found = needs([_meal(1, 4), _meal(2, 4)], details)
    assert describe_need(found[TOMATEN]) == (
        "braucht diese Woche: Chili, Suppe, zusammen 400 g, 2 Stück"
    )


def test_lebensmittel_ohne_klasse_werden_gefunden():
    foods = [
        Food.model_validate({"id": 1, "name": "Sushi-Reis", "supermarket_category": None}),
        Food.model_validate({"id": 2, "name": "Salz", "supermarket_category": {"name": "Gewürz"}}),
        Food.model_validate({"id": 3, "name": "Lachs", "supermarket_category": None}),
    ]
    categories = {"Gewürz": Placement("immer_da", "")}
    exceptions = {3: Placement("frisch", "")}
    assert unclassified(foods, categories, exceptions) == {1: "Sushi-Reis"}
