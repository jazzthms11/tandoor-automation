"""Vom gelesenen Bon zum Eintrag im Bestand.

Gebucht wird nur, was einen Abgangsweg hat. Der Rest des Bons ist damit erledigt: frische Ware
wird ohnehin sofort verbraucht, und was in Tandoor kein Lebensmittel ist, war nie eins.

Zusammengeführt wird über Lebensmittel und Einheit, nicht über den Ort. Steht ein Eintrag
woanders, als die Datei sagt, ist er umgeräumt worden, und dann gewinnt der Schrank, in dem er
tatsächlich liegt.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from tandoor_automation.classes import StockFood
from tandoor_automation.models import InventoryEntry, InventoryLocation
from tandoor_automation.receipts import KILOGRAM, PIECE, Receipt

UNITS = {PIECE: "Stück", KILOGRAM: "kg"}
"""Die Einheiten des Bons unter ihrem Namen in Tandoor."""


@dataclass(frozen=True)
class Addition:
    """Ein Zugang: so viel von diesem Lebensmittel kommt in diesen Schrank."""

    food_id: int
    food_name: str
    unit: str
    amount: Decimal
    location: str


def undecided(receipts: list[Receipt], mapping: dict[str, int | None]) -> list[str]:
    """Sucht die Artikelnamen, für die noch keine Zuordnung getroffen wurde.

    Args:
        receipts: Die zu buchenden Bons.
        mapping: Lebensmittel-ID je Bonname, `None` für verworfen.

    Returns:
        Die offenen Namen, jeder einmal, alphabetisch.
    """
    names = {item.name for receipt in receipts for item in receipt.items}
    return sorted(names - set(mapping))


def additions(
    receipts: list[Receipt], mapping: dict[str, int | None], foods: dict[int, StockFood]
) -> list[Addition]:
    """Rechnet aus, was die Bons dem Bestand hinzufügen.

    Mehrere Positionen desselben Lebensmittels werden zu einer Zeile addiert, auch über Bons
    hinweg. Verschiedene Einheiten bleiben getrennt: ein Kilo Zucchini und zwei Stück sind
    zwei Zugänge.

    Args:
        receipts: Die zu buchenden Bons.
        mapping: Lebensmittel-ID je Bonname, `None` für verworfen.
        foods: Name und Ort je Lebensmittel, das Bestand führt.

    Returns:
        Die Zugänge, nach Lebensmittelnamen sortiert.
    """
    amounts: dict[tuple[int, str], Decimal] = defaultdict(Decimal)
    for receipt in receipts:
        for item in receipt.items:
            food_id = mapping.get(item.name)
            if food_id is None or food_id not in foods:
                continue
            amounts[(food_id, item.unit)] += item.quantity
    found = [
        Addition(food_id, foods[food_id].name, UNITS[unit], amount, foods[food_id].location)
        for (food_id, unit), amount in amounts.items()
    ]
    return sorted(found, key=lambda addition: (addition.food_name.casefold(), addition.unit))


def twin(addition: Addition, entries: list[InventoryEntry], units: dict[str, int]) -> int | None:
    """Sucht den Bestandseintrag, auf den ein Zugang gebucht werden kann.

    Args:
        addition: Der Zugang.
        entries: Alle Einträge, die in Tandoor stehen.
        units: ID je Einheitenname.

    Returns:
        Die ID des passenden Eintrags, oder `None`, wenn es noch keinen gibt.
    """
    for entry in entries:
        if entry.food_id == addition.food_id and entry.unit_id == units[addition.unit]:
            return entry.id
    return None


def payload(
    addition: Addition, location: InventoryLocation, unit_id: int, expires: date
) -> dict[str, object]:
    """Baut den Körper für einen neuen Bestandseintrag.

    Args:
        addition: Der Zugang.
        location: Der Ort, wie Tandoor ihn kennt.
        unit_id: Die ID der Einheit.
        expires: Bis wann der Eintrag ohne neue Bestätigung als real gilt. Der Kauf selbst ist
            die stärkste Bestätigung, die es gibt, deshalb zählt er wie eine Antwort.

    Returns:
        Der Körper der Anfrage an `/api/inventory-entry/`.
    """
    return {
        "inventory_location": {
            "id": location.id,
            "name": location.name,
            "household": location.household,
        },
        "food": {"id": addition.food_id, "name": addition.food_name},
        "unit": {"id": unit_id, "name": addition.unit},
        "amount": _plain(addition.amount),
        "expires": expires.isoformat(),
    }


def describe(addition: Addition) -> str:
    """Fasst einen Zugang in eine Zeile."""
    return f"{_plain(addition.amount)} {addition.unit} {addition.food_name} → {addition.location}"


def _plain(amount: Decimal) -> str:
    """Schreibt eine Menge ohne nachlaufende Nullen und ohne Exponent."""
    return f"{amount.normalize():f}"
