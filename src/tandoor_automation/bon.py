"""Einstiegspunkt `bon`."""

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from tandoor_automation.config import Settings
from tandoor_automation.lidl import (
    TOKEN_FILE,
    LidlAuthError,
    LidlClient,
    login_url,
    redeem,
)
from tandoor_automation.mapping import MAPPING_FILE, merge, parse_mapping, problems, render
from tandoor_automation.receipts import parse_lidl
from tandoor_automation.tandoor import TandoorClient

BONS_DIR = Path("bons/lidl")
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
    args = parser.parse_args()
    try:
        if args.command == "login":
            _run_login()
        elif args.command == "map":
            _run_map(args.katalog)
        else:
            _run_fetch(args.dry_run)
    except LidlAuthError as problem:
        print(f"{problem}\nZugang herstellen mit: bon login")
        raise SystemExit(1) from None
