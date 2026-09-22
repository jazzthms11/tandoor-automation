"""Welche Klasse und welchen Ort ein Lebensmittel hat.

Beides hängt an der Supermarkt-Kategorie und steht in `klassen.tsv`, einzelne Ausreißer in
`ausnahmen.tsv`. Bestand führen nur die Klassen `rezept` und `vorrat`; alles andere hat keinen
Abgangsweg und würde im Inventar liegen bleiben.

Der Ort wird hier gelesen und nicht aus Tandoor: nach einem Umräumen genügt dann die Datei, und
die Einträge, die noch auf den alten Schrank zeigen, laufen von selbst aus.
"""

from dataclasses import dataclass
from pathlib import Path

from tandoor_automation.models import Food

CLASSES_FILE = Path("klassen.tsv")
EXCEPTIONS_FILE = Path("ausnahmen.tsv")
NONE_GIVEN = "-"
KEEPS_STOCK = frozenset({"rezept", "vorrat"})


@dataclass(frozen=True)
class Placement:
    """Klasse und Ort, wie sie in den Dateien stehen. Ein leerer Ort heißt: erbt von der Klasse."""

    stock_class: str
    location: str


@dataclass(frozen=True)
class StockFood:
    """Ein Lebensmittel, das Bestand führt, samt dem Ort, an dem es liegt."""

    name: str
    location: str


def parse_categories(text: str) -> dict[str, Placement]:
    """Liest `klassen.tsv`.

    Args:
        text: Inhalt der Datei.

    Returns:
        Klasse und Ort je Supermarkt-Kategorie.
    """
    found = {}
    for stock_class, location, category in _rows(text, 3):
        found[category] = Placement(stock_class, location)
    return found


def parse_exceptions(text: str) -> dict[int, Placement]:
    """Liest `ausnahmen.tsv`.

    Args:
        text: Inhalt der Datei.

    Returns:
        Klasse und Ort je Lebensmittel-ID, die von ihrer Kategorie abweicht.
    """
    found = {}
    for stock_class, location, food_id, _, _ in _rows(text, 5):
        found[int(food_id)] = Placement(stock_class, location)
    return found


def stock_foods(
    foods: list[Food], categories: dict[str, Placement], exceptions: dict[int, Placement]
) -> dict[int, StockFood]:
    """Sucht aus allen Lebensmitteln die heraus, die Bestand führen.

    Args:
        foods: Alle Lebensmittel aus Tandoor.
        categories: Klasse und Ort je Kategorie.
        exceptions: Klasse und Ort je abweichendem Lebensmittel.

    Returns:
        Name und Ort je Lebensmittel, das Bestand führt.
    """
    found = {}
    for food in foods:
        placement = _resolve(food, categories, exceptions)
        if placement is not None and placement.stock_class in KEEPS_STOCK:
            found[food.id] = StockFood(food.name, placement.location)
    return found


def _resolve(
    food: Food, categories: dict[str, Placement], exceptions: dict[int, Placement]
) -> Placement | None:
    """Setzt Klasse und Ort eines Lebensmittels zusammen, die Ausnahme schlägt die Kategorie."""
    from_category = categories.get(food.category)
    exception = exceptions.get(food.id)
    if exception is None:
        return from_category
    inherited = from_category or Placement("", "")
    return Placement(
        exception.stock_class or inherited.stock_class,
        exception.location or inherited.location,
    )


def _rows(text: str, columns: int) -> list[list[str]]:
    """Liest die Datenzeilen einer TSV-Datei, `-` wird zum leeren Feld."""
    rows = []
    for line in text.splitlines():
        if line.lstrip().startswith("#") or not line.strip():
            continue
        cells = [cell.strip() for cell in line.split("\t") if cell.strip()]
        rows.append(["" if cell == NONE_GIVEN else cell for cell in cells[:columns]])
    return rows
