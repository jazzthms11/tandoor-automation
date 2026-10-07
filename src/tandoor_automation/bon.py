"""Einstiegspunkt `bon`. Die Abläufe stehen in `intake`, hier nur Ein- und Ausgabe."""

import argparse
import re
from datetime import date
from pathlib import Path

from tandoor_automation import intake, tables
from tandoor_automation.config import Settings
from tandoor_automation.lidl import LidlAuthError, login_url, redeem, token_file
from tandoor_automation.mapping import problems, render, spanning
from tandoor_automation.tandoor import TandoorClient

MAPPING_FILE = Path(tables.TABLES["zuordnung"].file)
"""Der Export der Zuordnung im Arbeitsordner, dort wird von Hand entschieden."""


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

    Args:
        dry_run: Nur zeigen, was geholt würde.
    """
    fetched = intake.fetch_lidl(dry_run)
    for line in fetched.lines:
        print(f"{'würde holen' if dry_run else 'geholt'}: {line}")
    print(f"{len(fetched.lines)} neue Bons, {fetched.known} lagen schon vor")


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
    mapped = intake.refresh_mapping()
    entries, counts = mapped.entries, mapped.counts
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


def _run_import(paths: list[Path], dry_run: bool) -> None:
    """Liest Kaufland-Belege und legt sie unter ihrer Bonnummer ab.

    Die Datei wird kopiert, nicht verschoben: das Original bleibt dort liegen, wo die App es
    abgelegt hat. Ein Beleg, der schon vorliegt, wird genannt und nicht überschrieben.

    Args:
        paths: Pfade der PDF-Belege.
        dry_run: Nur zeigen, was abgelegt würde.
    """
    added, failed = 0, 0
    for path in paths:
        try:
            filed = intake.file_pdf(path, dry_run)
        except ValueError as problem:
            failed += 1
            print(f"{path.name}: {problem}")
            continue
        added += filed.new
        verb = "würde ablegen" if dry_run else "abgelegt"
        print(f"{verb if filed.new else 'liegt schon vor'}: {filed.line}")
    print(f"{added} neue Belege, {failed} nicht lesbar")
    if failed:
        raise SystemExit(1)


def _run_apply(since: date | None, dry_run: bool) -> None:
    """Bucht die Zugänge aus allen Bons, die noch nicht im Bestand angekommen sind.

    Args:
        since: Nur Bons ab diesem Tag buchen, ältere gelten als abgehandelt.
        dry_run: Nur zeigen, was gebucht würde.
    """
    with TandoorClient(Settings()) as tandoor:
        result = intake.book_receipts(tandoor, since, dry_run)
    if result.first_run:
        print("Beim ersten Lauf braucht es --seit DATUM, sonst laufen alle Bons in den Bestand.")
    for name in result.open_names:
        print(f"ohne Zuordnung: {name}")
    for name, food_id in result.gone:
        print(f"{name}: Lebensmittel {food_id} gibt es nicht mehr")
    for name in result.missing:
        print(f'Tandoor kennt "{name}" nicht')
    if result.open_names or result.gone:
        print("Erst zuordnen: bon map")
    if result.blocked:
        raise SystemExit(1)
    for verb, line in result.lines:
        print(f"{verb}: {line}")
    print(
        f"{result.booked} Bons gebucht, {result.skipped} übersprungen, "
        f"{result.known} lagen schon vor"
    )


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
