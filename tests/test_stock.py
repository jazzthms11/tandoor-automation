"""Was vom Bon in den Bestand geht und mit welcher Menge.

Hier lohnen Tests, weil beides still falsch werden kann. Fällt der Klassenfilter aus, wachsen
Gurken und Bier im Inventar mit, die niemand je wieder abbucht. Und wird ein Zugang nicht auf den
vorhandenen Eintrag addiert, sondern daneben gelegt, steht dasselbe Lebensmittel zweimal da, in
Tandoors Ansicht wie in der späteren Rückfrage.
"""

from decimal import Decimal

from tandoor_automation.classes import (
    Placement,
    StockFood,
    parse_categories,
    parse_exceptions,
    stock_foods,
)
from tandoor_automation.models import Food, InventoryEntry
from tandoor_automation.receipts import Receipt, ReceiptItem
from tandoor_automation.stock import Addition, additions, twin, undecided

KLASSEN = """# Kommentar
frisch\t-\tObst und Gemüse
rezept\tKüchenschrank\tKonserven
vorrat\tGefrierschrank\tBackwaren
immer_da\t-\tKräuter und Gewürze
"""

AUSNAHMEN = """# Kommentar
vorrat\tAbstellkammer\t556\tAlufolie\tkein Lebensmittel
rezept\t-\t448\tCiabatta\tsteht in 3 Rezepten
"""

FOODS = [
    Food(id=109, name="Gurke", category="Obst und Gemüse"),
    Food(id=323, name="Stückige Tomaten", category="Konserven"),
    Food(id=448, name="Ciabatta", category="Backwaren"),
    Food(id=556, name="Alufolie", category=""),
    Food(id=391, name="Salz", category="Kräuter und Gewürze"),
]


def _receipt(day: str, items: list[tuple[str, str, str]]) -> Receipt:
    return Receipt(
        source="lidl",
        receipt_id=day,
        purchased_on=day,
        store="Musterstadt",
        items=[
            ReceiptItem(name=name, quantity=Decimal(amount), unit=unit, unit_price=Decimal("1"))
            for name, amount, unit in items
        ],
    )


def _stock() -> dict[int, StockFood]:
    return stock_foods(FOODS, parse_categories(KLASSEN), parse_exceptions(AUSNAHMEN))


def test_nur_klassen_mit_abgangsweg_fuehren_bestand():
    assert set(_stock()) == {323, 448, 556}


def test_ausnahme_erbt_den_ort_ihrer_kategorie():
    assert _stock()[448] == StockFood("Ciabatta", "Gefrierschrank", "rezept")


def test_ausnahme_ohne_kategorie_bringt_ihren_ort_selbst_mit():
    assert _stock()[556] == StockFood("Alufolie", "Abstellkammer", "vorrat")


def test_kategorie_ohne_eigene_zeile_bleibt_ohne_klasse():
    categories = parse_categories(KLASSEN)
    assert categories["Konserven"] == Placement("rezept", "Küchenschrank")
    assert "Molkereiprodukte" not in categories


def test_mengen_werden_ueber_bons_hinweg_addiert():
    bons = [
        _receipt("2026-09-01", [("Gehackte Tomaten", "2", "stk")]),
        _receipt("2026-09-08", [("Gehackte Tomaten", "3", "stk")]),
    ]
    mapping: dict[str, int | None] = {"Gehackte Tomaten": 323}
    assert additions(bons, mapping, _stock()) == [
        Addition(323, "Stückige Tomaten", "Stück", Decimal("5"), "Küchenschrank")
    ]


def test_verschiedene_einheiten_bleiben_getrennt():
    bon = _receipt("2026-09-01", [("Ciabatta", "2", "stk"), ("Ciabatta", "1.034", "kg")])
    mapping: dict[str, int | None] = {"Ciabatta": 448}
    assert [(a.unit, a.amount) for a in additions([bon], mapping, _stock())] == [
        ("Stück", Decimal("2")),
        ("kg", Decimal("1.034")),
    ]


def test_verworfenes_und_frisches_kommt_nicht_in_den_bestand():
    bon = _receipt("2026-09-01", [("Pfand 0,25 M", "1", "stk"), ("Gurken", "2", "stk")])
    mapping: dict[str, int | None] = {"Pfand 0,25 M": None, "Gurken": 109}
    assert additions([bon], mapping, _stock()) == []


def test_unentschiedene_namen_werden_gemeldet():
    bon = _receipt("2026-09-01", [("Neuer Artikel", "1", "stk"), ("Gurken", "1", "stk")])
    assert undecided([bon], {"Gurken": 109}) == ["Neuer Artikel"]


def test_zusammengefuehrt_wird_ueber_lebensmittel_und_einheit_nicht_ueber_den_ort():
    entries = [
        InventoryEntry.model_validate(
            {"id": 7, "food": {"id": 323}, "unit": {"id": 14}, "amount": "1"}
        ),
        InventoryEntry.model_validate(
            {"id": 8, "food": {"id": 323}, "unit": {"id": 10}, "amount": "1"}
        ),
    ]
    stueck = Addition(323, "Stückige Tomaten", "Stück", Decimal("2"), "Abstellkammer")
    unbekannt = Addition(448, "Ciabatta", "Stück", Decimal("1"), "Gefrierschrank")
    units = {"Stück": 14, "kg": 10}
    assert twin(stueck, entries, units) == 7
    assert twin(unbekannt, entries, units) is None
