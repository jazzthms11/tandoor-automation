"""Die Zuordnung von Bonnamen zu Tandoor-Lebensmitteln.

Lidl druckt abgekürzte Markennamen, Tandoor führt Lebensmittel. Dass `Gehackte Tomaten` und
`Stückige Tomaten (Konserve)` dasselbe meinen, ist keine Ableitung, sondern eine Entscheidung.
Sie wird einmal getroffen und steht danach in `zuordnung.tsv`.

Die Klasse des Lebensmittels spielt hier keine Rolle. `-` heißt genau eine Sache, nämlich dass es
das Lebensmittel in Tandoor nicht gibt. Ob ein zugeordnetes Lebensmittel in den Bestand kommt,
entscheidet die Klasse, und die darf sich ändern, ohne diese Datei zu entwerten.
"""

from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

MAPPING_FILE = Path("zuordnung.tsv")
DISCARD = "-"
TAB_WIDTH = 8
COLUMNS = (8, 24, 48)
"""Breite der Spalten vor der letzten, in Zeichen. Gefüllt wird mit Tabulatoren, damit die Datei
neben `klassen.tsv` und `ausnahmen.tsv` gleich aussieht."""

HEADER = """# Bonname zu Tandoor-Lebensmittel. Nur die erste Spalte aendern.
#
#   <id>   die ID des Lebensmittels in Tandoor
#   -      kein Lebensmittel in Tandoor, wird verworfen
#   leer   noch nicht entschieden, haelt bon apply an
#
# Die Klasse steht hier nicht. Zugeordnet wird auch, was nie in den Bestand kommt; was davon
# gefuehrt wird, entscheidet klassen.tsv. Das `-` heisst deshalb nie "fuehrt keinen Bestand".
#
# Geschrieben wird die Datei von `bon map`, von Hand kommt allein die erste Spalte dazu.
# Spalten: id, bonname, lebensmittel, anzahl. Gelesen werden id und bonname.
"""


@dataclass(frozen=True)
class Entry:
    """Eine Zeile der Zuordnung: was auf dem Bon steht und was es in Tandoor ist."""

    receipt_name: str
    food_id: int | None = None
    discarded: bool = False
    count: int = 0

    @property
    def decided(self) -> bool:
        """Sagt, ob die Zeile entschieden ist, ob also zugeordnet oder verworfen wurde."""
        return self.food_id is not None or self.discarded


def parse_mapping(text: str) -> list[Entry]:
    """Liest `zuordnung.tsv`.

    Args:
        text: Inhalt der Datei.

    Returns:
        Alle Zeilen in der Reihenfolge der Datei, auch die noch nicht entschiedenen.
    """
    entries = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        cells = line.split("\t")
        rest = [cell.strip() for cell in cells[1:] if cell.strip()]
        if not rest:
            continue
        decision = cells[0].strip()
        entries.append(
            Entry(
                receipt_name=rest[0],
                food_id=int(decision) if decision.isdigit() else None,
                discarded=decision == DISCARD,
            )
        )
    return entries


def merge(known: list[Entry], counts: Counter[str]) -> list[Entry]:
    """Bringt die Zuordnung auf den Stand der vorliegenden Bons.

    Entscheidungen bleiben, auch wenn ein Name auf keinem Bon mehr vorkommt: einmal entschieden
    ist entschieden, und ein späterer Kauf desselben Artikels soll nicht neu fragen.

    Args:
        known: Die Zeilen, wie sie in der Datei stehen.
        counts: Wie oft jeder Bonname in allen Bons vorkommt.

    Returns:
        Die Zeilen nach Bonnamen sortiert, samt der neu hinzugekommenen.
    """
    merged = [replace(entry, count=counts.get(entry.receipt_name, 0)) for entry in known]
    seen = {entry.receipt_name for entry in merged}
    merged += [
        Entry(receipt_name=name, count=count) for name, count in counts.items() if name not in seen
    ]
    return sorted(merged, key=lambda entry: entry.receipt_name.casefold())


def render(entries: list[Entry], foods: dict[int, str]) -> str:
    """Schreibt die Zuordnung als Datei.

    Args:
        entries: Die Zeilen, sortiert wie sie stehen sollen.
        foods: Name je Lebensmittel-ID aus Tandoor.

    Returns:
        Der vollständige Inhalt der Datei.
    """
    lines = [HEADER]
    for entry in entries:
        decision = (
            DISCARD if entry.discarded else ("" if entry.food_id is None else str(entry.food_id))
        )
        food = DISCARD if entry.discarded else _food_name(entry.food_id, foods)
        cells = (decision, entry.receipt_name, food, str(entry.count))
        lines.append(_row(cells))
    return "\n".join(lines) + "\n"


def problems(entries: list[Entry], foods: dict[int, str]) -> list[str]:
    """Prüft die Zuordnung gegen Tandoor.

    Args:
        entries: Die gelesenen Zeilen.
        foods: Name je Lebensmittel-ID aus Tandoor.

    Returns:
        Alle gefundenen Mängel als Klartextzeilen.
    """
    found = []
    duplicates = [
        name for name, count in Counter(e.receipt_name for e in entries).items() if count > 1
    ]
    found += [f"{name}: steht mehrfach in der Datei" for name in sorted(duplicates)]
    for entry in entries:
        if entry.food_id is not None and entry.food_id not in foods:
            found.append(f"{entry.receipt_name}: Lebensmittel {entry.food_id} gibt es nicht")
    return found


def _food_name(food_id: int | None, foods: dict[int, str]) -> str:
    """Zeigt, wohin eine ID führt: leer wenn unentschieden, `?` wenn es sie nicht mehr gibt."""
    if food_id is None:
        return ""
    return foods.get(food_id, "?")


def _row(cells: tuple[str, ...]) -> str:
    """Setzt eine Zeile aus ihren Feldern, mit Tabulatoren bis zur nächsten Spalte."""
    row = ""
    for cell, width in zip(cells, COLUMNS, strict=False):
        row += cell + "\t" * _tabs(len(cell), width)
    return row + cells[-1]


def _tabs(length: int, width: int) -> int:
    """Sagt, wie viele Tabulatoren ein Feld bis zur nächsten Spalte braucht, mindestens einen."""
    return max(1, -(-(width - length) // TAB_WIDTH))
