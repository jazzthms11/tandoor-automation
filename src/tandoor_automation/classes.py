"""Welche Klasse und welchen Ort ein Lebensmittel hat.

Beides hängt an der Supermarkt-Kategorie und steht in der Tabelle `klassen`, einzelne Ausreißer
in `ausnahmen`. Bestand führen nur die Klassen `rezept` und `vorrat`; alles andere hat keinen
Abgangsweg und würde im Inventar liegen bleiben.

Der Ort wird hier gelesen und nicht aus Tandoor: nach einem Umräumen genügt dann die Tabelle, und
die Einträge, die noch auf den alten Schrank zeigen, laufen von selbst aus.
"""

from dataclasses import dataclass

from tandoor_automation.models import Food

NONE_GIVEN = "-"
KEEPS_STOCK = frozenset({"rezept", "vorrat"})
BUYS_FRESH = frozenset({"frisch"})
"""Frischware führt keinen Bestand: Der Plan setzt sie ungefragt auf die Liste."""


@dataclass(frozen=True)
class Placement:
    """Klasse und Ort, wie sie in den Tabellen stehen. Ein leerer Ort heißt: erbt von der Klasse."""

    stock_class: str
    location: str


@dataclass(frozen=True)
class StockFood:
    """Ein Lebensmittel, das Bestand führt, samt Ort und Klasse.

    Die Klasse sagt zweierlei: was die Rückfrage auslöst (`rezept` der Wochenplan, `vorrat` die
    Zeit) und in welcher Form gefragt wird.
    """

    name: str
    location: str
    stock_class: str


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
        Name, Ort und Klasse je Lebensmittel, das Bestand führt.
    """
    return _in_classes(foods, categories, exceptions, KEEPS_STOCK)


def fresh_foods(
    foods: list[Food], categories: dict[str, Placement], exceptions: dict[int, Placement]
) -> dict[int, StockFood]:
    """Sucht die Frischware heraus, die der Plan ungefragt auf die Liste setzt.

    Args:
        foods: Alle Lebensmittel aus Tandoor.
        categories: Klasse und Ort je Kategorie.
        exceptions: Klasse und Ort je abweichendem Lebensmittel.

    Returns:
        Name, Ort und Klasse je Lebensmittel, das je Plan gekauft wird.
    """
    return _in_classes(foods, categories, exceptions, BUYS_FRESH)


def unclassified(
    foods: list[Food], categories: dict[str, Placement], exceptions: dict[int, Placement]
) -> dict[int, str]:
    """Sucht die Lebensmittel heraus, die weder Kategorie noch Ausnahme eine Klasse gibt.

    Sie fallen sonst durch jede Auswahl: nicht gefragt, nicht ungefragt gekauft, und kein Fehler
    sagt es. Ein neu angelegtes Lebensmittel ohne Supermarkt-Kategorie ist der übliche Fall.

    Args:
        foods: Alle Lebensmittel aus Tandoor.
        categories: Klasse und Ort je Kategorie.
        exceptions: Klasse und Ort je abweichendem Lebensmittel.

    Returns:
        Name je Lebensmittel ohne Klasse.
    """
    found = {}
    for food in foods:
        placement = _resolve(food, categories, exceptions)
        if placement is None or not placement.stock_class:
            found[food.id] = food.name
    return found


def _in_classes(
    foods: list[Food],
    categories: dict[str, Placement],
    exceptions: dict[int, Placement],
    wanted: frozenset[str],
) -> dict[int, StockFood]:
    """Sucht die Lebensmittel heraus, deren Klasse in `wanted` steht."""
    found = {}
    for food in foods:
        placement = _resolve(food, categories, exceptions)
        if placement is not None and placement.stock_class in wanted:
            found[food.id] = StockFood(food.name, placement.location, placement.stock_class)
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
