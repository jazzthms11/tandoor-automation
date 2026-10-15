"""Das Lesen eines Kaufland-Belegs.

Hier lohnen Tests mehr als bei Lidl. Lidl liefert die Werte als Attribute, hier wird eine
Textspalte gelesen, und eine Zeile, die durch das Raster fällt, sieht nach nichts aus: die Ware
käme nie in den Bestand. Kaufland setzt den Artikelnamen außerdem auf die Zeile darüber, wenn er
neben der Stückrechnung nicht mehr passt.

Die Vorlage ist ein echter Beleg als `pdftotext -layout`, ohne die Kartendaten.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from tandoor_automation.receipts import KILOGRAM, PIECE, parse_kaufland

FIXTURES = Path(__file__).parent / "fixtures"
BON = (FIXTURES / "kaufland_bon.txt").read_text(encoding="utf-8")
GEWICHT = (FIXTURES / "kaufland_bon_gewicht.txt").read_text(encoding="utf-8")


def _position(name: str):
    return next(item for item in parse_kaufland(BON).items if item.name == name)


def test_kopfdaten_des_einkaufs():
    bon = parse_kaufland(BON)
    assert bon.source == "kaufland"
    assert bon.receipt_id == "20260924-1670-35-33426"
    assert str(bon.purchased_on) == "2026-09-24"
    assert bon.store == "Sinsheim"


def test_jede_position_genau_einmal():
    """Der Beleg trägt fünfzehn Artikel, sechs davon mit einer Rabattzeile darunter."""
    namen = [item.name for item in parse_kaufland(BON).items]
    assert len(namen) == 15
    assert len(set(namen)) == 15


def test_einzelne_stueckware_ohne_mengenangabe():
    brot = _position("Wurzelbrot")
    assert brot.quantity == Decimal("1")
    assert brot.unit == PIECE
    assert brot.unit_price == Decimal("1.39")


def test_stueckrechnung_neben_dem_namen():
    """`Soja Schnetzel 2 * 2,49` sind zwei Stück zu 2,49 und nicht eines zu 4,98."""
    schnetzel = _position("Soja Schnetzel")
    assert schnetzel.quantity == Decimal("2")
    assert schnetzel.unit_price == Decimal("2.49")


def test_name_von_der_zeile_darueber():
    """Passt der Name nicht neben die Stückrechnung, steht er allein auf der Zeile davor."""
    tee = _position("KBio.Kamillentee")
    assert tee.quantity == Decimal("2")
    assert tee.unit_price == Decimal("0.71")


def test_gewichtsware_in_kilo():
    """Gewogenes trägt den Namen auf der Zeile darüber und darunter nur das Gewicht.

    Ein Kilopreis steht nicht auf dem Beleg, er folgt aus Betrag und Gewicht.
    """
    kuerbis = parse_kaufland(GEWICHT).items[0]
    assert kuerbis.name == "Kürbis Hokkaido kg"
    assert kuerbis.quantity == Decimal("1.958")
    assert kuerbis.unit == KILOGRAM


def test_rabattzeile_wird_keine_eigene_position():
    """`K Card XTRA Rabatt -1,00` hängt am Artikel darüber und ist kein zweiter Artikel."""
    namen = [item.name for item in parse_kaufland(BON).items]
    assert "K Card XTRA Rabatt" not in namen


def test_eine_verschluckte_position_faellt_auf():
    """Fehlt eine Zeile im Beleg, ergeben die Positionen die gedruckte Summe nicht mehr."""
    ohne = BON.replace("Wurzelbrot                        1,39 B\n", "")
    with pytest.raises(ValueError, match="auf dem Beleg steht"):
        parse_kaufland(ohne)


def test_beleg_ohne_positionsblock():
    with pytest.raises(ValueError, match="Positionsblock"):
        parse_kaufland("Kaufland\n74889 Sinsheim\n")
