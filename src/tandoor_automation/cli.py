"""Einstiegspunkt `plan`."""

import argparse
from datetime import date
from pathlib import Path

from tandoor_automation.apply import describe, match_existing, meal_type_of, payload, without
from tandoor_automation.bundle import PlanBundle, build_bundle, next_week, parse_week
from tandoor_automation.config import Settings
from tandoor_automation.proposal import Proposal, validate_proposal
from tandoor_automation.rating import (
    changes,
    own_base_ratings,
    parse_ratings,
)
from tandoor_automation.rating import (
    payload as rating_payload,
)
from tandoor_automation.tandoor import TandoorClient

BUNDLE_DIR = Path("bundle")
RATINGS_FILE = Path("bewertung.tsv")


def write_bundle(week: str | None) -> Path:
    """Holt das Kontextbündel der Zielwoche und legt es als JSON-Datei ab.

    Args:
        week: Zielwoche als ISO-Woche. Ohne Angabe die kommende Woche.

    Returns:
        Pfad der geschriebenen Datei.
    """
    week = week or next_week(date.today())
    parse_week(week)
    with TandoorClient(Settings()) as tandoor:
        bundle = build_bundle(tandoor, week)
    BUNDLE_DIR.mkdir(exist_ok=True)
    target = BUNDLE_DIR / f"{week}.json"
    target.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
    return target


def check_proposal(path: Path) -> list[str]:
    """Prüft einen Vorschlag gegen das Bündel der Woche, für die er gilt.

    Args:
        path: Pfad der Vorschlagsdatei.

    Returns:
        Alle gefundenen Mängel als Klartextzeilen.

    Raises:
        FileNotFoundError: Wenn es zur Woche des Vorschlags kein Bündel gibt.
    """
    proposal = _read_proposal(path)
    source = BUNDLE_DIR / f"{proposal.week}.json"
    if not source.exists():
        raise FileNotFoundError(f"Kein Bündel für {proposal.week}, erwartet unter {source}")
    bundle = PlanBundle.model_validate_json(source.read_text(encoding="utf-8"))
    return validate_proposal(proposal, bundle)


def _read_proposal(path: Path) -> Proposal:
    """Liest eine Vorschlagsdatei."""
    return Proposal.model_validate_json(path.read_text(encoding="utf-8"))


def _report(problems: list[str]) -> None:
    """Gibt gefundene Mängel aus und bricht den Lauf ab, wenn es welche gibt."""
    for problem in problems:
        print(problem)
    if problems:
        raise SystemExit(1)


def _run_check(path: Path) -> None:
    """Prüft einen Vorschlag und meldet das Ergebnis über den Rückgabewert des Programms."""
    _report(check_proposal(path))
    print(f"{path}: in Ordnung")


def _run_apply(path: Path, dry_run: bool) -> None:
    """Prüft einen Vorschlag gegen den aktuellen Stand in Tandoor und schreibt, was noch fehlt.

    Anders als `plan check` wird das Bündel hier frisch geholt: geschrieben wird gegen den Plan,
    wie er jetzt ist, nicht gegen den, wie er beim Wählen war.

    Args:
        path: Pfad der Vorschlagsdatei.
        dry_run: Nur zeigen, was geschrieben würde.
    """
    proposal = _read_proposal(path)
    with TandoorClient(Settings()) as tandoor:
        bundle = build_bundle(tandoor, proposal.week)
        matches = match_existing(proposal, bundle)
        _report(validate_proposal(proposal, without(bundle, [twin for _, twin in matches if twin])))
        for entry, twin in matches:
            meal_type = meal_type_of(bundle, entry)
            line = describe(entry, meal_type)
            if twin is not None:
                print(f"steht schon: {line}")
            elif dry_run or meal_type is None:
                print(f"würde schreiben: {line}")
            else:
                tandoor.create_meal(payload(entry, meal_type))
                print(f"geschrieben: {line}")


def _run_rate(dry_run: bool) -> None:
    """Gleicht die Grundbewertung aus `bewertung.tsv` mit Tandoors Kochprotokoll ab.

    Die Datei ist die Quelle: eine Note, die dort auf 0 steht, wird in Tandoor gelöscht. Geändert
    wird der vorhandene Eintrag, denn Tandoor mittelt die Noten eines Rezepts, statt die neueste
    zu nehmen.

    Args:
        dry_run: Nur zeigen, was geschrieben würde.
    """
    ratings = parse_ratings(RATINGS_FILE.read_text(encoding="utf-8"))
    with TandoorClient(Settings()) as tandoor:
        names = {recipe.id: recipe.name for recipe in tandoor.recipes()}
        unknown = sorted(set(ratings) - set(names))
        if unknown:
            print(f"{RATINGS_FILE}: unbekannte Rezepte {unknown}")
            raise SystemExit(1)
        existing = own_base_ratings(tandoor.cook_logs(), tandoor.current_user_id())
        todo = changes(ratings, existing)
        for change in todo:
            verb = "löschen" if not change.stars else ("ändern" if change.log_id else "anlegen")
            print(f"{'würde ' if dry_run else ''}{verb}: {change.stars}★ {names[change.recipe_id]}")
            if dry_run:
                continue
            if not change.stars and change.log_id is not None:
                tandoor.delete_cook_log(change.log_id)
            elif change.log_id is not None:
                tandoor.update_cook_log(change.log_id, rating_payload(change))
            else:
                tandoor.create_cook_log(rating_payload(change))
    print(f"{len(todo)} Änderungen, {len(ratings) - len(todo)} schon richtig")


def main() -> None:
    """Liest die Kommandozeile und führt den gewählten Befehl aus."""
    parser = argparse.ArgumentParser(prog="plan", description="Wochenplaner für Tandoor")
    commands = parser.add_subparsers(dest="command", required=True)
    bundle = commands.add_parser("bundle", help="Kontextbündel einer Woche als Datei ausgeben")
    bundle.add_argument(
        "--week",
        help="Zielwoche als ISO-Woche, etwa 2026-W39. Ohne Angabe die kommende Woche.",
    )
    check = commands.add_parser("check", help="Vorschlag gegen das Bündel seiner Woche prüfen")
    check.add_argument("datei", type=Path, help="Pfad der Vorschlagsdatei")
    apply_ = commands.add_parser("apply", help="Vorschlag prüfen und nach Tandoor schreiben")
    apply_.add_argument("datei", type=Path, help="Pfad der Vorschlagsdatei")
    apply_.add_argument("--dry-run", action="store_true", help="Nur zeigen, was geschrieben würde")
    rate = commands.add_parser("rate", help=f"Grundbewertung aus {RATINGS_FILE} nach Tandoor")
    rate.add_argument("--dry-run", action="store_true", help="Nur zeigen, was geschrieben würde")
    args = parser.parse_args()
    if args.command == "check":
        _run_check(args.datei)
    elif args.command == "apply":
        _run_apply(args.datei, args.dry_run)
    elif args.command == "rate":
        _run_rate(args.dry_run)
    else:
        print(write_bundle(args.week))
