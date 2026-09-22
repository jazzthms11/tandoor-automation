"""Einstiegspunkt `bon`."""

import argparse
import json
import re
from collections import Counter
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

from tandoor_automation.classes import (
    CLASSES_FILE,
    EXCEPTIONS_FILE,
    parse_categories,
    parse_exceptions,
    stock_foods,
)
from tandoor_automation.config import Settings
from tandoor_automation.lidl import (
    TOKEN_FILE,
    LidlAuthError,
    LidlClient,
    login_url,
    redeem,
)
from tandoor_automation.mapping import MAPPING_FILE, merge, parse_mapping, problems, render
from tandoor_automation.models import InventoryLocation
from tandoor_automation.receipts import Receipt, parse_lidl
from tandoor_automation.stock import Addition, additions, describe, payload, twin, undecided
from tandoor_automation.tandoor import TandoorClient

BONS_DIR = Path("bons/lidl")
STATE_FILE = Path("bons/.importiert")
"""Welche Bons im Bestand angekommen sind. Anders als beim Holen trägt die Ablage das nicht:
ein gebuchter Bon sieht aus wie ein ungebuchter, und ein zweiter Lauf würde die Mengen
verdoppeln. Gemerkt werden auch die übersprungenen, sonst holt der nächste Lauf sie nach."""
UNKNOWN_DATE = "ohne-datum"


def _known_ids() -> set[str]:
    """Liest den Stand aus den abgelegten Dateien.

    Ein eigener Stand wäre eine zweite Wahrheit, die von der Ablage abweichen kann. Der
    Dateiname trägt die ID, damit genügt der Ordner selbst.

    Returns:
        Die IDs aller Bons, die schon vorliegen.
    """
    return {path.stem.split("_", 1)[1] for path in BONS_DIR.glob("*_*.json")}


def _target(summary: dict[str, Any]) -> Path:
    """Baut den Ablagepfad: das Datum sortiert den Ordner, die ID erkennt den Bon wieder."""
    day = str(summary.get("date") or "")[:10] or UNKNOWN_DATE
    return BONS_DIR / f"{day}_{summary['id']}.json"


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
    print(f"Zugang steht, abgelegt in {TOKEN_FILE}.")


def _run_fetch(dry_run: bool) -> None:
    """Holt alle Bons, die noch nicht vorliegen, und legt sie unverändert ab.

    Gespeichert wird die Antwort der API, nicht eine Auslese daraus: was ein Bon für den Bestand
    hergibt, entscheidet erst die Zuordnung, und ein Fehler dort soll keinen neuen Abruf kosten.

    Args:
        dry_run: Nur zeigen, was geholt würde.
    """
    known = _known_ids()
    BONS_DIR.mkdir(parents=True, exist_ok=True)
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


def _receipt_names() -> Counter[str]:
    """Zählt, wie oft jeder Artikelname über alle abgelegten Bons hinweg vorkommt."""
    counts: Counter[str] = Counter()
    for path in sorted(BONS_DIR.glob("*.json")):
        receipt = parse_lidl(json.loads(path.read_text(encoding="utf-8")))
        counts.update(item.name for item in receipt.items)
    return counts


def _run_map(catalogue: bool) -> None:
    """Bringt die Zuordnung auf den Stand der Bons und prüft sie gegen Tandoor.

    Geschrieben wird die Datei immer, auch wenn Mängel gefunden wurden: die Mängel stecken in der
    ersten Spalte, und die bleibt beim Schreiben unangetastet.

    Args:
        catalogue: Statt der Zuordnung die Lebensmittel aus Tandoor ausgeben.
    """
    with TandoorClient(Settings()) as tandoor:
        foods = tandoor.foods()
    if catalogue:
        for food in foods:
            print(f"{food.id}\t{food.name}\t{food.category}")
        return
    known = parse_mapping(MAPPING_FILE.read_text(encoding="utf-8")) if MAPPING_FILE.exists() else []
    entries = merge(known, _receipt_names())
    names = {food.id: food.name for food in foods}
    MAPPING_FILE.write_text(render(entries, names), encoding="utf-8")
    open_names = [entry.receipt_name for entry in entries if not entry.decided]
    discarded = sum(1 for entry in entries if entry.discarded)
    print(
        f"{MAPPING_FILE}: {len(entries)} Namen, {len(entries) - len(open_names) - discarded} "
        f"zugeordnet, {discarded} verworfen, {len(open_names)} offen"
    )
    found = problems(entries, names)
    for problem in found:
        print(problem)
    if found:
        raise SystemExit(1)


def _receipts() -> list[Receipt]:
    """Liest alle abgelegten Bons, den ältesten zuerst."""
    parsed = [
        parse_lidl(json.loads(p.read_text(encoding="utf-8"))) for p in BONS_DIR.glob("*.json")
    ]
    return sorted(parsed, key=lambda receipt: receipt.purchased_on)


def _imported() -> set[str]:
    """Liest, welche Bons schon abgehandelt sind."""
    if not STATE_FILE.exists():
        return set()
    return {line.strip() for line in STATE_FILE.read_text(encoding="utf-8").splitlines() if line}


def _remember(receipts: Iterable[Receipt]) -> None:
    """Hält fest, dass diese Bons abgehandelt sind."""
    with STATE_FILE.open("a", encoding="utf-8") as handle:
        for receipt in receipts:
            handle.write(f"{receipt.receipt_id}\n")


def _decided() -> dict[str, int | None]:
    """Liest die Zuordnung, ohne die Namen, über die noch nicht entschieden wurde."""
    entries = parse_mapping(MAPPING_FILE.read_text(encoding="utf-8"))
    return {entry.receipt_name: entry.food_id for entry in entries if entry.decided}


def _run_apply(since: date | None, dry_run: bool) -> None:
    """Bucht die Zugänge aus allen Bons, die noch nicht im Bestand angekommen sind.

    Args:
        since: Nur Bons ab diesem Tag buchen, ältere gelten als abgehandelt.
        dry_run: Nur zeigen, was gebucht würde.
    """
    if not STATE_FILE.exists() and since is None:
        print("Beim ersten Lauf braucht es --seit DATUM, sonst laufen alle Bons in den Bestand.")
        raise SystemExit(1)
    known = _imported()
    fresh = [receipt for receipt in _receipts() if receipt.receipt_id not in known]
    skipped = {r.receipt_id for r in fresh if since is not None and r.purchased_on < since}
    todo = [r for r in fresh if r.receipt_id not in skipped]
    mapping = _decided()
    open_names = undecided(todo, mapping)
    for name in open_names:
        print(f"ohne Zuordnung: {name}")
    if open_names:
        print(f"Erst {MAPPING_FILE} ergänzen: bon map")
        raise SystemExit(1)
    _book(todo, mapping, dry_run)
    if not dry_run:
        _remember(fresh)
    print(f"{len(todo)} Bons gebucht, {len(skipped)} übersprungen, {len(known)} lagen schon vor")


def _book(receipts: list[Receipt], mapping: dict[str, int | None], dry_run: bool) -> None:
    """Rechnet die Zugänge aus und schreibt sie nach Tandoor.

    Args:
        receipts: Die zu buchenden Bons.
        mapping: Lebensmittel-ID je Bonname.
        dry_run: Nur zeigen, was gebucht würde.
    """
    with TandoorClient(Settings()) as tandoor:
        foods = stock_foods(
            tandoor.foods(),
            parse_categories(CLASSES_FILE.read_text(encoding="utf-8")),
            parse_exceptions(EXCEPTIONS_FILE.read_text(encoding="utf-8")),
        )
        todo = additions(receipts, mapping, foods)
        units = tandoor.units()
        locations = {place.name: place for place in tandoor.inventory_locations()}
        _check(todo, units, locations)
        inventory = tandoor.inventory()
        for addition in todo:
            entry_id = twin(addition, inventory, units)
            if dry_run:
                print(f"würde buchen: {describe(addition)}")
            elif entry_id is not None:
                entry = next(e for e in inventory if e.id == entry_id)
                tandoor.update_inventory_amount(entry_id, entry.amount + addition.amount)
                print(f"dazu: {describe(addition)}")
            else:
                tandoor.create_inventory_entry(
                    payload(addition, locations[addition.location], units[addition.unit])
                )
                print(f"neu: {describe(addition)}")


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
    mapping = commands.add_parser("map", help=f"Bonnamen in {MAPPING_FILE} zuordnen")
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
        else:
            _run_fetch(args.dry_run)
    except LidlAuthError as problem:
        print(f"{problem}\nZugang herstellen mit: bon login")
        raise SystemExit(1) from None
