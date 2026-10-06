"""Die Zuordnung von Bonnamen zu Tandoor-Lebensmitteln.

Die Läden drucken abgekürzte Markennamen, Tandoor führt Lebensmittel. Dass `Gehackte Tomaten` und
`Stückige Tomaten (Konserve)` dasselbe meinen, ist keine Ableitung, sondern eine Entscheidung.
Sie wird einmal getroffen und steht danach in `zuordnung.tsv`.

Entschieden wird über den Namen, nicht über den Laden: derselbe Name meint fast überall dasselbe,
und eine Zeile je Laden wäre für fast alle Namen Rauschen. Wo er widerspricht, sticht eine Zeile
mit Laden die allgemeine. `Soja Schnetzel` ist bei Lidl Granulat und bei Kaufland Schnetzel.

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
COLUMNS = (TAB_WIDTH, TAB_WIDTH, 24, 48)
"""Breite der Spalten vor der letzten, in Zeichen. Gefüllt wird mit Tabulatoren, damit die Datei
neben `klassen.tsv` und `ausnahmen.tsv` gleich aussieht.

Die beiden ersten Spalten sind genau einen Tabulator breit, und das ist keine Kosmetik: nur so
steht jedes Feld an einer festen Stelle. Eine breitere Spalte bekäme für ein kurzes Feld zwei
Tabulatoren, und der Parser läse das leere Feld dazwischen als eigene Spalte."""

Counts = Counter[tuple[str, str]]
"""Wie oft ein Bonname vorkommt, je Laden gezählt."""
Decisions = dict[tuple[str, str], int | None]
"""Die geltende Entscheidung je Laden und Bonname, die allgemeine schon eingesetzt."""

HEADER = """# Bonname zu Tandoor-Lebensmittel. Von Hand kommen Laden und ID.
#
#   id     <id>            die ID des Lebensmittels in Tandoor
#          -               kein Lebensmittel in Tandoor, wird verworfen
#          leer            noch nicht entschieden, haelt bon apply an
#
#   laden  leer            die Entscheidung gilt in jedem Laden
#          lidl, kaufland  gilt nur dort und sticht die Zeile ohne Laden
#
# Ein Laden steht nur, wo er widerspricht, wo derselbe Bonname also je Laden etwas anderes meint.
# Solange keine Ladenzeile dasteht, gilt die Entscheidung fuer jeden Laden, und `bon map` nennt
# jeden Namen, der auf mehr als einem Bon steht.
#
# Die Klasse steht hier nicht. Zugeordnet wird auch, was nie in den Bestand kommt; was davon
# gefuehrt wird, entscheidet klassen.tsv. Das `-` heisst deshalb nie "fuehrt keinen Bestand".
#
# Geschrieben wird die Datei von `bon map`, eingelesen mit `plan data import zuordnung`.
# Spalten: id, laden, bonname, lebensmittel, anzahl. Gelesen werden die ersten drei.
"""


@dataclass(frozen=True)
class Entry:
    """Eine Zeile der Zuordnung: was auf dem Bon steht und was es in Tandoor ist."""

    receipt_name: str
    store: str = ""
    """Der Laden, für den die Zeile gilt. Leer heißt: für jeden."""
    food_id: int | None = None
    discarded: bool = False
    count: int = 0

    @property
    def decided(self) -> bool:
        """Sagt, ob die Zeile entschieden ist, ob also zugeordnet oder verworfen wurde."""
        return self.food_id is not None or self.discarded

    @property
    def key(self) -> tuple[str, str]:
        """Der Schlüssel der Zeile: Laden und Bonname."""
        return self.store, self.receipt_name


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
        rest = [cell.strip() for cell in cells[2:] if cell.strip()]
        if len(cells) < 3 or not rest:
            continue
        decision = cells[0].strip()
        entries.append(
            Entry(
                receipt_name=rest[0],
                store=cells[1].strip(),
                food_id=int(decision) if decision.isdigit() else None,
                discarded=decision == DISCARD,
            )
        )
    return entries


def merge(known: list[Entry], counts: Counts) -> list[Entry]:
    """Bringt die Zuordnung auf den Stand der vorliegenden Bons.

    Entscheidungen bleiben, auch wenn ein Name auf keinem Bon mehr vorkommt: einmal entschieden
    ist entschieden, und ein späterer Kauf desselben Artikels soll nicht neu fragen. Ein neuer
    Name kommt ohne Laden hinein, denn nichts widerspricht ihm bisher.

    Args:
        known: Die Zeilen, wie sie in der Datei stehen.
        counts: Wie oft jeder Bonname je Laden vorkommt.

    Returns:
        Die Zeilen nach Bonnamen sortiert, die allgemeine vor ihren Ladenzeilen.
    """
    special = {entry.key for entry in known if entry.store}
    general = {entry.receipt_name for entry in known if not entry.store}
    merged = [replace(entry, count=_count(entry, counts, special)) for entry in known]
    fresh = sorted(
        {name for store, name in counts if (store, name) not in special and name not in general}
    )
    merged += [
        Entry(receipt_name=name, count=_count(Entry(name), counts, special)) for name in fresh
    ]
    return sorted(merged, key=lambda entry: (entry.receipt_name.casefold(), entry.store))


def resolve(entries: list[Entry], keys: set[tuple[str, str]]) -> Decisions:
    """Legt für jeden vorkommenden Laden und Bonname die geltende Entscheidung fest.

    Nachgeschlagen wird zuerst die Zeile des Ladens, dann die ohne. Was hier fehlt, ist nicht
    entschieden.

    Args:
        entries: Die gelesenen Zeilen.
        keys: Die Paare aus Laden und Bonname, die auf den Bons vorkommen.

    Returns:
        Lebensmittel-ID je Paar, `None` für verworfen.
    """
    general = {e.receipt_name: e.food_id for e in entries if not e.store and e.decided}
    special = {e.key: e.food_id for e in entries if e.store and e.decided}
    found: Decisions = {}
    for key in keys:
        if key in special:
            found[key] = special[key]
        elif key[1] in general:
            found[key] = general[key[1]]
    return found


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
        cells = (decision, entry.store, entry.receipt_name, food, str(entry.count))
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
    duplicates = [key for key, count in Counter(e.key for e in entries).items() if count > 1]
    found += [f"{_named(key)}: steht mehrfach in der Datei" for key in sorted(duplicates)]
    for entry in entries:
        if entry.food_id is not None and entry.food_id not in foods:
            found.append(f"{_named(entry.key)}: Lebensmittel {entry.food_id} gibt es nicht")
    found += [
        f"{_named(entry.key)}: kommt bei {entry.store} nicht vor"
        for entry in entries
        if entry.store and not entry.count
    ]
    return found


def spanning(entries: list[Entry], counts: Counts) -> list[str]:
    """Nennt die Namen, deren eine Entscheidung für mehrere Läden gilt.

    Ein Name, der überall dasselbe meint, braucht keine Ladenzeile. Ob er das tut, weiß der Code
    nicht: er kann nur sagen, welche Entscheidung mehr als einen Laden trägt.

    Args:
        entries: Die gelesenen Zeilen.
        counts: Wie oft jeder Bonname je Laden vorkommt.

    Returns:
        Eine Zeile je betroffenem Namen.
    """
    special = {entry.key for entry in entries if entry.store}
    lines = []
    for entry in entries:
        if entry.store or not entry.decided:
            continue
        stores = sorted(
            store
            for (store, name), count in counts.items()
            if name == entry.receipt_name and count and (store, name) not in special
        )
        if len(stores) > 1:
            lines.append(
                f"{entry.receipt_name}: steht bei {', '.join(stores)} und ist einmal entschieden"
            )
    return lines


def _count(entry: Entry, counts: Counts, special: set[tuple[str, str]]) -> int:
    """Zählt, was eine Zeile trägt: ihren Laden, oder alle ohne eigene Ladenzeile."""
    if entry.store:
        return counts.get(entry.key, 0)
    return sum(
        count
        for (store, name), count in counts.items()
        if name == entry.receipt_name and (store, name) not in special
    )


def _named(key: tuple[str, str]) -> str:
    """Nennt eine Zeile so, dass die Ladenzeile von der allgemeinen zu unterscheiden ist."""
    store, name = key
    return f"{name} ({store})" if store else name


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
