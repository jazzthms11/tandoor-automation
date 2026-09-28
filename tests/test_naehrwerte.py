"""Was beim Nachtragen der Nährwerte still falsch werden kann.

Zwei Stellen, beide unsichtbar bis lange danach. Tandoor löscht am Lebensmittel jede Eigenschaft,
die im PATCH fehlt: eine unvollständige Liste nimmt Kalorien, Fett, Protein und Kohlenhydrate mit,
und übrig bleibt ein Lebensmittel, dessen Rezepte nichts mehr rechnen. Und FDC führt seine Werte je
100 g, die Basis eines Lebensmittels ist aber nicht immer 100 g: der Römersalat steht auf 500 g und
käme unskaliert mit dem Fünffachen in den Bestand der Nährwerte.
"""

from decimal import Decimal

import pytest

from naehrwerte import basis_factor, payload

TYPES = {"Zucker": {"id": 98, "name": "Zucker"}, "Ballaststoffe": {"id": 99}}

TOMATO = {
    "id": 7,
    "name": "Tomate",
    "properties_food_amount": 100.0,
    "properties_food_unit": {"id": 13, "name": "g"},
    "properties": [
        {"id": 1024, "property_amount": 0.82, "property_type": {"id": 2, "name": "Proteine"}},
        {"id": 1027, "property_amount": 20.0, "property_type": {"id": 1, "name": "Kalorien"}},
    ],
}


def test_payload_keeps_what_it_does_not_change():
    rows = payload(TOMATO, {"Zucker": Decimal("2.63")}, TYPES)
    assert [row["property_type"]["name"] for row in rows] == ["Proteine", "Kalorien", "Zucker"]
    assert [row.get("id") for row in rows] == [1024, 1027, None]
    assert [row["property_amount"] for row in rows] == ["0.82", "20.0", "2.63"]


def test_payload_overwrites_a_value_that_already_exists():
    rows = payload(TOMATO, {"Kalorien": Decimal("18")}, TYPES)
    assert len(rows) == 2
    assert rows[1] == {
        "id": 1027,
        "property_amount": "18",
        "property_type": {"id": 1, "name": "Kalorien"},
    }


@pytest.mark.parametrize(
    ("amount", "unit", "expected"),
    [(100.0, "g", Decimal(1)), (500.0, "g", Decimal(5)), (30.0, "g", Decimal("0.3"))],
)
def test_basis_factor_rechnet_auf_die_basis(amount, unit, expected):
    food = {"properties_food_amount": amount, "properties_food_unit": {"name": unit}}
    assert basis_factor(food) == expected


@pytest.mark.parametrize("unit", ["Stück", "Scheiben", "Bund", "Pck."])
def test_basis_factor_verweigert_was_kein_gewicht_ist(unit):
    food = {"properties_food_amount": 1.0, "properties_food_unit": {"name": unit}}
    assert basis_factor(food) is None
