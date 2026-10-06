"""Die Tabellen von Hand als TSV-Datei, hin und zurück.

Bis die Oberfläche eine Seite dafür hat, ist die Datei der Weg, eine Tabelle durchzusehen und zu
ändern: `plan data export` schreibt sie, von Hand wird sie geändert, `plan data import` liest sie
zurück. Die Datei ist dabei ganz die Quelle: eine Zeile, die fehlt, wird gelöscht.

Die Dateien sehen aus wie früher im Repo, mit Kopf, Abschnitten und Gedächtnisstützen, damit der
Umzug sie unverändert einlesen kann. Geprüft wird beim Einlesen mit denselben Parsern wie früher.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from sqlmodel import SQLModel, select

from tandoor_automation import store
from tandoor_automation.classes import NONE_GIVEN, parse_categories, parse_exceptions
from tandoor_automation.mapping import parse_mapping
from tandoor_automation.rating import parse_ratings
from tandoor_automation.shopping import parse_intervals

SECTION = "# ---"
STAMPS = frozenset({"changed_at", "booked_at", "position"})
"""Felder, die beim Vergleich nicht zählen: wann eine Zeile geändert wurde, ist keine Änderung."""

RATINGS_HEADER = """\
# Grundbewertung der Rezepte. Nur die erste Spalte ausfüllen.
#
#   5  geht quasi immer
#   4  sehr gut, aber nicht jede Woche
#   3  kann man mal essen, nur wenn es lange her ist
#   2  eigentlich nicht gut
#   1  nie
#   0  nicht bewertet, bleibt so
#
# Spalten: sterne, id, name, schlagworte, beschreibung. Tab oder Leerzeichen, beides geht.
# Gelesen werden nur sterne und id, der Rest der Zeile ist Gedaechtnisstuetze.
#
# Zurück in die Datenbank mit `plan data import bewertung`, nach Tandoor mit `plan rate`.
"""
CLASSES_HEADER = """\
# Bestandsklasse und Ort je Supermarkt-Kategorie. Nur die ersten beiden Spalten aendern.
#
#   frisch     kein Bestand. Der Wochenplan setzt es direkt auf die Liste.
#   rezept     Bestand. Der Wochenplan loest die Rueckfrage aus.
#   vorrat     Bestand. Das Intervall loest die Rueckfrage aus.
#   immer_da   kein Bestand, nie automatisch auf der Liste. Nur ueber den Tag oder von Hand.
#   genuss     kein Bestand, nie automatisch auf der Liste.
#   gekocht    haengt an einem Rezept, wird nie gekauft.
#
# Der Ort steht nur, wo die Klasse Bestand fuehrt, sonst `-`. Er sortiert die Rueckfrage,
# damit der Kuehlschrank einmal aufgeht und nicht fuenfmal. Gefragt wird nach dieser Spalte
# und nicht nach dem, was in Tandoor steht: ein Umraeumen kostet dann nur diese Tabelle.
#
# Spalten: klasse, ort, kategorie. Gelesen wird die Zeile ganz, alle drei Spalten zaehlen.
# Einzelne Lebensmittel, die hier falsch landen, stehen in ausnahmen.tsv.
#
# Zurück in die Datenbank mit `plan data import klassen`.
"""
EXCEPTIONS_HEADER = """\
# Lebensmittel, deren Klasse oder Ort nicht zur Kategorie passt. Schlaegt klassen.tsv.
#
# Nur eintragen, wo die Klasse der Art nach falsch ist, also frisch gegen haltbar
# oder fuehrt Bestand gegen fuehrt keinen. Nur zu frueh oder zu spaet gefragt ist
# keine Ausnahme, das regelt das Intervall.
#
# Der Ort steht nur, wo die Kategorie der Zeile keinen hergibt, sonst `-`.
#
# Spalten: klasse, ort, id, name, grund. Gelesen werden klasse, ort und id.
#
# Zurück in die Datenbank mit `plan data import ausnahmen`.
"""
INTERVALS_HEADER = """\
# Wie lange eine Antwort traegt: so viele Tage nach der Bestaetigung fragt die Rueckfrage
# wieder nach diesem Lebensmittel. Nur die erste Spalte ausfuellen.
#
# Gebraucht wird die Zahl allein fuer die Klasse `vorrat`, die die Zeit ausloest. Rezeptware
# loest der Wochenplan aus, sie steht hier nicht. Leere Zeile heisst: Rueckfall auf 14 Tage.
#
# Erlaubt ist jede ganze Zahl. Gefragt wird aber nur, wenn `plan shop` laeuft, also einmal die
# Woche: unter 7 Tagen aendert sich nichts mehr, und 21 und 23 sind dieselbe Angabe.
#
# Die Spalte `gemessen` ist eine Lesehilfe und wird nicht gelesen. Sie zeigt den mittleren
# Abstand zwischen zwei Kaeufen aus der Bonhistorie und wie viele Kaeufe dahinterstehen.
#
# Spalten: tage, id, name, gemessen. Gelesen werden tage und id.
#
# Zurück in die Datenbank mit `plan data import intervalle`.
"""
BOOKED_HEADER = """\
# Bons, die im Bestand angekommen oder übersprungen sind, eine ID je Zeile.
# Eingelesen wird nur dazu, gelöscht wird nichts: ein vergessener Bon würde doppelt gebucht.
"""


@dataclass(frozen=True)
class Table:
    """Eine Tabelle, wie sie als Datei aussieht."""

    name: str
    file: str
    model: type[SQLModel]
    parse: Callable[[str], list[Any]]
    render: Callable[[list[Any]], str] | None
    """Ohne heißt: der Export braucht mehr als die Tabelle und geht anders."""


@dataclass(frozen=True)
class Diff:
    """Was ein Einlesen an einer Tabelle ändert."""

    added: int
    changed: int
    removed: int


def _lines(text: str) -> Iterator[tuple[int, str, str]]:
    """Liefert die Datenzeilen mit Platz in der Datei und dem Abschnitt, unter dem sie stehen."""
    section = ""
    for position, line in enumerate(text.splitlines()):
        if line.lstrip().startswith(SECTION):
            section = line.strip()
        elif line.strip() and not line.lstrip().startswith("#"):
            yield position, section, line


def _cells(line: str) -> list[str]:
    """Die gefüllten Felder einer Zeile, getrennt an Tabulatoren."""
    return [cell.strip() for cell in line.split("\t") if cell.strip()]


def _given(cell: str) -> str:
    """Ein leeres Feld steht in der Datei als `-`."""
    return "" if cell == NONE_GIVEN else cell


def _parse_ratings(text: str) -> list[store.Rating]:
    parse_ratings(text)
    rows = []
    for position, section, line in _lines(text):
        fields = line.split(None, 2)
        rows.append(
            store.Rating(
                recipe_id=int(fields[1]),
                stars=int(fields[0]),
                note=fields[2].rstrip() if len(fields) > 2 else "",
                section=section,
                position=position,
            )
        )
    return rows


def _parse_categories(text: str) -> list[store.CategoryClass]:
    parse_categories(text)
    rows = []
    for position, section, line in _lines(text):
        cells = _cells(line)
        rows.append(
            store.CategoryClass(
                category=cells[2],
                stock_class=_given(cells[0]),
                location=_given(cells[1]),
                note="\t".join(cells[3:]),
                section=section,
                position=position,
            )
        )
    return rows


def _parse_exceptions(text: str) -> list[store.FoodException]:
    parse_exceptions(text)
    rows = []
    for position, section, line in _lines(text):
        cells = _cells(line)
        rows.append(
            store.FoodException(
                food_id=int(cells[2]),
                stock_class=_given(cells[0]),
                location=_given(cells[1]),
                note="\t".join(cells[3:]),
                section=section,
                position=position,
            )
        )
    return rows


def _parse_intervals(text: str) -> list[store.FoodInterval]:
    """Liest Spalte für Spalte, eine leere erste Spalte heißt: kein eigenes Intervall."""
    parse_intervals(text)
    rows = []
    for position, section, line in _lines(text):
        cells = line.split("\t")
        days = cells[0].strip()
        rows.append(
            store.FoodInterval(
                food_id=int(cells[1]),
                days=int(days) if days else None,
                note="\t".join(cells[2:]).rstrip(),
                section=section,
                position=position,
            )
        )
    return rows


def _parse_mapping(text: str) -> list[store.ReceiptMapping]:
    return [
        store.ReceiptMapping(
            store=entry.store,
            receipt_name=entry.receipt_name,
            food_id=entry.food_id,
            discarded=entry.discarded,
        )
        for entry in parse_mapping(text)
    ]


def _parse_booked(text: str) -> list[store.BookedReceipt]:
    lines = (line.strip() for line in text.splitlines())
    ids = {line for line in lines if line and not line.startswith("#")}
    return [store.BookedReceipt(receipt_id=receipt_id) for receipt_id in sorted(ids)]


def _sectioned(header: str, rows: list[Any], line: Callable[[Any], str]) -> str:
    """Setzt eine Datei aus Kopf und Zeilen, eine Abschnittszeile, wo der Abschnitt wechselt."""
    lines = [header]
    section = ""
    for row in sorted(rows, key=lambda row: row.position):
        if row.section != section:
            section = row.section
            lines += ["", section]
        lines.append(line(row).rstrip())
    return "\n".join(lines) + "\n"


def _render_ratings(rows: list[store.Rating]) -> str:
    return _sectioned(RATINGS_HEADER, rows, lambda r: f"{r.stars}\t{r.recipe_id}\t{r.note}")


def _render_categories(rows: list[store.CategoryClass]) -> str:
    return _sectioned(
        CLASSES_HEADER,
        rows,
        lambda r: (
            f"{r.stock_class or NONE_GIVEN}\t\t{r.location or NONE_GIVEN}\t\t{r.category}\t{r.note}"
        ),
    )


def _render_exceptions(rows: list[store.FoodException]) -> str:
    return _sectioned(
        EXCEPTIONS_HEADER,
        rows,
        lambda r: (
            f"{r.stock_class or NONE_GIVEN}\t\t{r.location or NONE_GIVEN}\t\t{r.food_id}\t{r.note}"
        ),
    )


def _render_intervals(rows: list[store.FoodInterval]) -> str:
    return _sectioned(
        INTERVALS_HEADER,
        rows,
        lambda r: f"{'' if r.days is None else r.days}\t{r.food_id}\t{r.note}",
    )


def _render_booked(rows: list[store.BookedReceipt]) -> str:
    return BOOKED_HEADER + "".join(f"{row.receipt_id}\n" for row in sorted(rows, key=_key))


TABLES = {
    table.name: table
    for table in (
        Table("bewertung", "bewertung.tsv", store.Rating, _parse_ratings, _render_ratings),
        Table("klassen", "klassen.tsv", store.CategoryClass, _parse_categories, _render_categories),
        Table(
            "ausnahmen", "ausnahmen.tsv", store.FoodException, _parse_exceptions, _render_exceptions
        ),
        Table(
            "intervalle", "intervalle.tsv", store.FoodInterval, _parse_intervals, _render_intervals
        ),
        Table("zuordnung", "zuordnung.tsv", store.ReceiptMapping, _parse_mapping, None),
        Table("importiert", "importiert.txt", store.BookedReceipt, _parse_booked, _render_booked),
    )
}
"""Die Zuordnung braucht für ihre Lesehilfe Tandoor und die Bons, ihr Export ist `bon map`."""


def _key(row: SQLModel) -> tuple[Any, ...]:
    """Der Primärschlüssel einer Zeile."""
    columns = row.__table__.primary_key.columns  # ty: ignore[unresolved-attribute]
    return tuple(getattr(row, column.name) for column in columns)


def _content(row: SQLModel) -> tuple[Any, ...]:
    """Was an einer Zeile zählt, ohne Zeitstempel und Platz."""
    return tuple(sorted(row.model_dump(exclude=set(STAMPS)).items()))


def rows(table: Table) -> list[Any]:
    """Alle Zeilen einer Tabelle aus der Datenbank."""
    with store.session() as db:
        return list(db.exec(select(table.model)).all())


def unimported(table: Table, text: str) -> int:
    """Zählt die Zeilen einer Datei, die so nicht in der Datenbank stehen.

    Vor dem Überschreiben einer Datei geprüft: sie kann Änderungen tragen, die noch nicht
    eingelesen sind, und die wären sonst weg.

    Args:
        table: Die Tabelle.
        text: Inhalt der vorhandenen Datei.

    Returns:
        Wie viele Zeilen der Datei in der Datenbank fehlen oder dort anders stehen, dazu die
        Zeilen der Datenbank, die in der Datei gelöscht wurden.
    """
    stored = rows(table)
    given = table.parse(text)
    known = {_content(row) for row in stored}
    gone = {_key(row) for row in stored} - {_key(row) for row in given}
    return sum(1 for row in given if _content(row) not in known) + len(gone)


def load(table: Table, text: str, dry_run: bool) -> Diff:
    """Liest eine Datei in ihre Tabelle ein, in einer Transaktion.

    Die Datei ersetzt die Tabelle. Ausgenommen ist der Stand der Bons, dort kommt nur dazu: ein
    gelöschter Eintrag würde einen Bon beim nächsten Lauf doppelt buchen.

    Zeilen, die unverändert bleiben, behalten ihren Zeitstempel, damit `changed_at` sagt, seit
    wann eine Entscheidung so steht.

    Args:
        table: Die Tabelle.
        text: Inhalt der Datei.
        dry_run: Nur zählen, nichts schreiben.

    Returns:
        Wie viele Zeilen dazukommen, sich ändern und wegfallen.

    Raises:
        ValueError: Wenn die Datei nicht lesbar ist oder ein Schlüssel zweimal vorkommt.
    """
    fresh = table.parse(text)
    keys = [_key(row) for row in fresh]
    if len(set(keys)) != len(keys):
        twice = sorted({key for key in keys if keys.count(key) > 1})
        raise ValueError(f"{table.file}: steht mehrfach drin: {twice}")
    additive = table.model is store.BookedReceipt
    with store.session() as db:
        old = {_key(row): row for row in db.exec(select(table.model))}
        added = changed = 0
        for row in fresh:
            before = old.pop(_key(row), None)
            if before is None:
                added += 1
                db.add(row)
                continue
            changed += _update(before, row)
            db.add(before)
        removed = 0 if additive else len(old)
        if not additive:
            for row in old.values():
                db.delete(row)
        if not dry_run:
            db.commit()
    return Diff(added, changed, removed)


def _update(before: Any, row: Any) -> bool:  # noqa: ANN401
    """Übernimmt eine eingelesene Zeile in die vorhandene und sagt, ob sich Inhalt änderte.

    Der Platz in der Datei wird immer übernommen, zählt aber nicht als Änderung: wer eine Zeile
    nur verschiebt, hat nichts entschieden.
    """
    if hasattr(before, "position"):
        before.position = row.position
    if _content(before) == _content(row):
        return False
    for field, value in row.model_dump(exclude=set(STAMPS)).items():
        setattr(before, field, value)
    before.changed_at = row.changed_at
    return True
