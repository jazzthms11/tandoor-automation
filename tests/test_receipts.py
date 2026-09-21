"""Das Lesen eines Lidl-Belegs.

Hier lohnen Tests, weil die Menge still falsch werden kann: Lidl druckt Gewichtsware anders als
Stückware, und beide Formen stehen in derselben Zeilensorte. Wird eine Mengenzeile für eine
eigene Position gehalten, wächst der Bestand um Artikel, die es nicht gibt; wird die Einheit
verwechselt, landet ein Kilo Gurken im Schrank statt zweier Stück.

Die Vorlage ist ein echter Beleg, gekürzt auf den Artikelblock.
"""

import json
from decimal import Decimal
from pathlib import Path

from tandoor_automation.receipts import KILOGRAM, PIECE, parse_lidl

BON = json.loads((Path(__file__).parent / "fixtures" / "lidl_bon.json").read_text(encoding="utf-8"))


def _position(name: str):
    return next(item for item in parse_lidl(BON).items if item.name == name)


def test_kopfdaten_des_einkaufs():
    bon = parse_lidl(BON)
    assert bon.source == "lidl"
    assert bon.receipt_id == "23004240120260918523079"
    assert str(bon.purchased_on) == "2026-09-18"
    assert bon.store == "Musterstadt, Musterstr. 1"


def test_jede_position_genau_einmal():
    """Der Beleg trägt dreizehn Artikel, vier davon mit einer zweiten Zeile für das Gewicht."""
    namen = [item.name for item in parse_lidl(BON).items]
    assert len(namen) == 13
    assert len(set(namen)) == 13


def test_gewichtsware_behaelt_ihr_gewicht():
    zucchini = _position("Zucchini")
    assert zucchini.quantity == Decimal("1.034")
    assert zucchini.unit == KILOGRAM
    assert zucchini.unit_price == Decimal("1.39")


def test_mehrfach_gekaufte_stueckware():
    """Zwei Gurken sind zwei Stück, nicht zwei Kilo und nicht zwei Bons."""
    gurken = _position("Gurken")
    assert gurken.quantity == Decimal("2")
    assert gurken.unit == PIECE


def test_einzelne_stueckware_ohne_mengenangabe():
    """Ohne `data-art-quantity` im Beleg ist die Menge eins."""
    salat = _position("Kopfsalat mit Wurzel")
    assert salat.quantity == Decimal("1")
    assert salat.unit == PIECE


def test_die_mengenzeile_wird_keine_eigene_position():
    """Die Zeile `1,034 kg x 1,39 EUR/kg` gehört zur Zucchini und ist kein zweiter Artikel."""
    assert [item.name for item in parse_lidl(BON).items].count("Zucchini") == 1
