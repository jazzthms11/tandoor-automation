"""Einstiegspunkt `bon`."""

import argparse
import json
import re
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from tandoor_automation import store, tables
from tandoor_automation.classes import stock_foods
from tandoor_automation.config import Settings
from tandoor_automation.lidl import (
    LidlAuthError,
    LidlClient,
    login_url,
    redeem,
    token_file,
)
from tandoor_automation.mapping import (
    Counts,
    Decisions,
    merge,
    problems,
    render,
    resolve,
    spanning,
)
from tandoor_automation.models import InventoryLocation
from tandoor_automation.receipts import Receipt, parse_kaufland, parse_lidl
from tandoor_automation.shopping import confirmed_until
from tandoor_automation.stock import (
    Addition,
    additions,
    dangling,
    describe,
    payload,
    twin,
    undecided,
)
from tandoor_automation.tandoor import TandoorClient

PDFTOTEXT = "pdftotext"
UNKNOWN_DATE = "ohne-datum"
MAPPING_FILE = Path(tables.TABLES["zuordnung"].file)
"""Der Export der Zuordnung im Arbeitsordner, dort wird von Hand entschieden."""


def _lidl_dir() -> Path:
    """Die Rohbons aus Lidl Plus, je Bon die Antwort der API."""
    return store.bons_dir() / "lidl"


def _kaufland_dir() -> Path:
    """Kaufland gibt nichts her, was sich abholen ließe.

    Sein Beleg kommt als PDF aus der App und wird hier eingeworfen; abgelegt wird die Datei
    unverändert, gelesen bei jedem Lauf neu.
    """
    return store.bons_dir() / "kaufland"


def _known_ids() -> set[str]:
    """Liest den Stand aus den abgelegten Dateien.

    Ein eigener Stand wäre eine zweite Wahrheit, die von der Ablage abweichen kann. Der
    Dateiname trägt die ID, damit genügt der Ordner selbst.

    Returns:
        Die IDs aller Bons, die schon vorliegen.
    """
    return {path.stem.split("_", 1)[1] for path in _lidl_dir().glob("*_*.json")}


def _target(summary: dict[str, Any]) -> Path:
    """Baut den Ablagepfad: das Datum sortiert den Ordner, die ID erkennt den Bon wieder."""
    day = str(summary.get("date") or "")[:10] or UNKNOWN_DATE
    return _lidl_dir() / f"{day}_{summary['id']}.json"


def _describe(summary: dict[str, Any]) -> str:
    """Fasst einen Bon in eine Zeile: Tag, Summe, ID."""
    day = str(summary.get("date") or "?")[:10]
    return f"{day}  {summary.get('totalAmount', '?'):>8}  {summary['id']}"


def _run_login() -> None:
    """Führt einmalig durch die Anmeldung bei Lidl Plus.

    Der Anmeldebildschirm gehört Lidl und läuft im eigenen Browser, hier geht nur der Code über
    den Tisch, den Lidl danach zurückgibt. Er steckt in einer Adresse, die der Browser nicht
    öffnen kann, weil sie der App gehört: sichtbar wird sie in der Adresszeile oder im
    Netzwerk-Tab der Entwicklerwerkzeuge.
    """
    url, verifier = login_url()
    print(f"\nIm Browser anmelden:\n\n{url}\n")
    answer = input("Adresse oder Code nach der Anmeldung einfügen: ").strip()
    match = re.search(r"code=([0-9A-Za-z]+)", answer)
    redeem(match.group(1) if match else answer, verifier)
    print(f"Zugang steht, abgelegt in {token_file()}.")


def _run_fetch(dry_run: bool) -> None:
    """Holt alle Bons, die noch nicht vorliegen, und legt sie unverändert ab.

    Gespeichert wird die Antwort der API, nicht eine Auslese daraus: was ein Bon für den Bestand
    hergibt, entscheidet erst die Zuordnung, und ein Fehler dort soll keinen neuen Abruf kosten.

    Args:
        dry_run: Nur zeigen, was geholt würde.
    """
    known = _known_ids()
    _lidl_dir().mkdir(parents=True, exist_ok=True)
    fetched = 0
    with LidlClient() as lidl:
        for summary in lidl.tickets():
            ticket_id = str(summary["id"])
            if ticket_id in known:
                continue
            fetched += 1
            if dry_run:
                print(f"würde holen: {_describe(summary)}")
                continue
            raw = lidl.ticket(ticket_id)
            _target(summary).write_text(
                json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"geholt: {_describe(summary)}")
    print(f"{fetched} neue Bons, {len(known)} lagen schon vor")


def _receipt_names() -> Counts:
    """Zählt, wie oft jeder Artikelname vorkommt, je Laden getrennt."""
    counts: Counts = Counter()
    for receipt in _receipts():
        counts.update((receipt.source, item.name) for item in receipt.items)
    return counts


def _run_map(catalogue: bool) -> None:
    """Bringt die Zuordnung auf den Stand der Bons und prüft sie gegen Tandoor.

    Neue Bonnamen kommen unentschieden in die Datenbank, zum Entscheiden geht die ganze
    Zuordnung als Datei in den Arbeitsordner. Geschrieben wird sie auch bei Mängeln: die stecken
    in der ersten Spalte, und die ist von Hand zu berichtigen. Eine Datei mit Entscheidungen,
    die noch nicht eingelesen sind, bleibt dagegen liegen.

    Args:
        catalogue: Statt der Zuordnung die Lebensmittel aus Tandoor ausgeben.
    """
    with TandoorClient(Settings()) as tandoor:
        foods = tandoor.foods()
    if catalogue:
        for food in foods:
            print(f"{food.id}\t{food.name}\t{food.category}")
        return
    table = tables.TABLES["zuordnung"]
    if MAPPING_FILE.exists() and tables.unimported(table, MAPPING_FILE.read_text("utf-8")):
        print(f"{MAPPING_FILE} trägt Entscheidungen, die noch nicht eingelesen sind:")
        print("erst plan data import zuordnung, oder die Datei löschen")
        raise SystemExit(1)
    counts = _receipt_names()
    entries = merge(store.mapping(), counts)
    store.add_mapping(entries)
    names = {food.id: food.name for food in foods}
    MAPPING_FILE.write_text(render(entries, names), encoding="utf-8")
    open_names = [entry.receipt_name for entry in entries if not entry.decided]
    discarded = sum(1 for entry in entries if entry.discarded)
    print(
        f"{MAPPING_FILE}: {len(entries)} Zeilen, {len(entries) - len(open_names) - discarded} "
        f"zugeordnet, {discarded} verworfen, {len(open_names)} offen"
    )
    for line in spanning(entries, counts):
        print(line)
    found = problems(entries, names)
    for problem in found:
        print(problem)
    if open_names or found:
        print(f"In {MAPPING_FILE} entscheiden, dann: plan data import zuordnung")
    if found:
        raise SystemExit(1)


def _receipts() -> list[Receipt]:
    """Liest alle abgelegten Bons beider Quellen, den ältesten zuerst."""
    parsed = [
        parse_lidl(json.loads(p.read_text(encoding="utf-8"))) for p in _lidl_dir().glob("*.json")
    ]
    parsed += [parse_kaufland(_pdf_text(p)) for p in _kaufland_dir().glob("*.pdf")]
    return sorted(parsed, key=lambda receipt: receipt.purchased_on)


def _pdf_text(path: Path) -> str:
    """Holt die Textebene eines PDF, die Spalten so wie gedruckt.

    Gelesen wird mit `pdftotext` aus poppler-utils. Ein Fremdpaket dafür wäre eine Abhängigkeit
    mehr für einen Aufruf, den das System schon kann.

    Args:
        path: Pfad des PDF.

    Returns:
        Der Text des Belegs.

    Raises:
        ValueError: Wenn die Datei fehlt oder `pdftotext` sie nicht lesen kann.
    """
    if not path.is_file():
        raise ValueError("Datei nicht gefunden")
    try:
        done = subprocess.run(
            [PDFTOTEXT, "-layout", str(path), "-"], capture_output=True, text=True, check=True
        )
    except FileNotFoundError as missing:
        raise ValueError(f"{PDFTOTEXT} fehlt, steckt in poppler-utils") from missing
    except subprocess.CalledProcessError as broken:
        raise ValueError(f"{PDFTOTEXT} bricht ab: {broken.stderr.strip()}") from broken
    return done.stdout


def _run_import(paths: list[Path], dry_run: bool) -> None:
    """Liest Kaufland-Belege und legt sie unter ihrer Bonnummer ab.

    Die Datei wird kopiert, nicht verschoben: das Original bleibt dort liegen, wo die App es
    abgelegt hat. Ein Beleg, der schon vorliegt, wird genannt und nicht überschrieben.

    Args:
        paths: Pfade der PDF-Belege.
        dry_run: Nur zeigen, was abgelegt würde.
    """
    _kaufland_dir().mkdir(parents=True, exist_ok=True)
    added, failed = 0, 0
    for path in paths:
        try:
            added += _import_pdf(path, dry_run)
        except ValueError as problem:
            failed += 1
            print(f"{path.name}: {problem}")
    print(f"{added} neue Belege, {failed} nicht lesbar")
    if failed:
        raise SystemExit(1)


def _import_pdf(path: Path, dry_run: bool) -> int:
    """Legt einen Beleg ab und sagt über den Rückgabewert, ob er neu war."""
    receipt = parse_kaufland(_pdf_text(path))
    target = _kaufland_dir() / f"{receipt.receipt_id}.pdf"
    line = (
        f"{receipt.purchased_on}  {receipt.store}  {len(receipt.items)} Positionen  {target.name}"
    )
    if target.exists():
        print(f"liegt schon vor: {line}")
        return 0
    if dry_run:
        print(f"würde ablegen: {line}")
        return 1
    target.write_bytes(path.read_bytes())
    print(f"abgelegt: {line}")
    return 1


def _decided(receipts: list[Receipt]) -> Decisions:
    """Legt für jede Position der Bons die geltende Entscheidung fest.

    Args:
        receipts: Die Bons, um die es geht.

    Returns:
        Lebensmittel-ID je Laden und Bonname, ohne die noch nicht entschiedenen.
    """
    entries = store.mapping()
    keys = {(receipt.source, item.name) for receipt in receipts for item in receipt.items}
    return resolve(entries, keys)


def _run_apply(since: date | None, dry_run: bool) -> None:
    """Bucht die Zugänge aus allen Bons, die noch nicht im Bestand angekommen sind.

    Welche Bons angekommen sind, trägt die Ablage nicht: ein gebuchter Bon sieht aus wie ein
    ungebuchter, und ein zweiter Lauf würde die Mengen verdoppeln. Gemerkt werden deshalb in der
    Datenbank auch die übersprungenen, sonst holte der nächste Lauf sie nach.

    Args:
        since: Nur Bons ab diesem Tag buchen, ältere gelten als abgehandelt.
        dry_run: Nur zeigen, was gebucht würde.
    """
    known = store.booked()
    if not known and since is None:
        print("Beim ersten Lauf braucht es --seit DATUM, sonst laufen alle Bons in den Bestand.")
        raise SystemExit(1)
    fresh = [receipt for receipt in _receipts() if receipt.receipt_id not in known]
    skipped = {r.receipt_id for r in fresh if since is not None and r.purchased_on < since}
    todo = [r for r in fresh if r.receipt_id not in skipped]
    mapping = _decided(todo)
    open_names = undecided(todo, mapping)
    for name in open_names:
        print(f"ohne Zuordnung: {name}")
    if open_names:
        print("Erst zuordnen: bon map")
        raise SystemExit(1)
    _book(todo, mapping, dry_run)
    if not dry_run:
        store.remember({receipt.receipt_id for receipt in fresh})
    print(f"{len(todo)} Bons gebucht, {len(skipped)} übersprungen, {len(known)} lagen schon vor")


def _book(receipts: list[Receipt], mapping: Decisions, dry_run: bool) -> None:
    """Rechnet die Zugänge aus und schreibt sie nach Tandoor.

    Args:
        receipts: Die zu buchenden Bons.
        mapping: Lebensmittel-ID je Laden und Bonname.
        dry_run: Nur zeigen, was gebucht würde.
    """
    with TandoorClient(Settings()) as tandoor:
        catalogue = tandoor.foods()
        _check_mapping(receipts, mapping, {food.id for food in catalogue})
        foods = stock_foods(catalogue, store.categories(), store.exceptions())
        todo = additions(receipts, mapping, foods)
        units = tandoor.units()
        locations = {place.name: place for place in tandoor.inventory_locations()}
        _check(todo, units, locations)
        inventory = tandoor.inventory()
        intervals = store.intervals()
        for addition in todo:
            entry_id = twin(addition, inventory, units)
            trusted_until = confirmed_until(date.today(), addition.food_id, intervals)
            if dry_run:
                print(f"würde buchen: {describe(addition)}")
            elif entry_id is not None:
                entry = next(e for e in inventory if e.id == entry_id)
                tandoor.update_inventory_entry(
                    entry_id, entry.amount + addition.amount, trusted_until
                )
                print(f"dazu: {describe(addition)}")
            else:
                tandoor.create_inventory_entry(
                    payload(
                        addition,
                        locations[addition.location],
                        units[addition.unit],
                        trusted_until,
                    )
                )
                print(f"neu: {describe(addition)}")


def _check_mapping(receipts: list[Receipt], mapping: Decisions, ids: set[int]) -> None:
    """Hält den Lauf an, wenn ein zugeordnetes Lebensmittel in Tandoor gelöscht wurde."""
    gone = dangling(receipts, mapping, ids)
    for name, food_id in gone:
        print(f"{name}: Lebensmittel {food_id} gibt es nicht mehr")
    if gone:
        print("Erst die Zuordnung berichtigen: bon map")
        raise SystemExit(1)


def _check(
    todo: list[Addition], units: dict[str, int], locations: dict[str, InventoryLocation]
) -> None:
    """Prüft, dass Tandoor jeden Ort und jede Einheit kennt, die gebucht werden soll."""
    missing = {a.location for a in todo if a.location not in locations}
    missing |= {a.unit for a in todo if a.unit not in units}
    for name in sorted(missing):
        print(f'Tandoor kennt "{name}" nicht')
    if missing:
        raise SystemExit(1)


def main() -> None:
    """Liest die Kommandozeile und führt den gewählten Befehl aus."""
    parser = argparse.ArgumentParser(prog="bon", description="Kassenbons für den Bestand")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("login", help="Einmalig den Zugang zu Lidl Plus herstellen")
    fetch = commands.add_parser("fetch", help="Bons aus Lidl Plus holen, die noch fehlen")
    fetch.add_argument("--dry-run", action="store_true", help="Nur zeigen, was geholt würde")
    imports = commands.add_parser("import-pdf", help="Kaufland-Belege als PDF einlesen")
    imports.add_argument("dateien", type=Path, nargs="+", help="Pfade der PDF-Belege")
    imports.add_argument("--dry-run", action="store_true", help="Nur zeigen, was abgelegt würde")
    mapping = commands.add_parser("map", help="Neue Bonnamen aufnehmen und zum Zuordnen ausgeben")
    mapping.add_argument(
        "--katalog",
        action="store_true",
        help="Statt der Zuordnung die Lebensmittel aus Tandoor ausgeben",
    )
    apply_ = commands.add_parser("apply", help="Zugänge aus den Bons in den Bestand buchen")
    apply_.add_argument(
        "--seit",
        type=date.fromisoformat,
        help="Nur Bons ab diesem Tag buchen, ältere gelten als abgehandelt",
    )
    apply_.add_argument("--dry-run", action="store_true", help="Nur zeigen, was gebucht würde")
    args = parser.parse_args()
    try:
        if args.command == "login":
            _run_login()
        elif args.command == "map":
            _run_map(args.katalog)
        elif args.command == "apply":
            _run_apply(args.seit, args.dry_run)
        elif args.command == "import-pdf":
            _run_import(args.dateien, args.dry_run)
        else:
            _run_fetch(args.dry_run)
    except LidlAuthError as problem:
        print(f"{problem}\nZugang herstellen mit: bon login")
        raise SystemExit(1) from None
