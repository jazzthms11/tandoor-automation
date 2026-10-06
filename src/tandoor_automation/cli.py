"""Einstiegspunkt `plan`.

Hier wird gefragt und ausgegeben, sonst nichts. Die Abläufe selbst stehen in `workflow`, damit
die Oberfläche dieselben Schritte über Knöpfe gehen kann.
"""

import argparse
from datetime import date
from pathlib import Path

from tandoor_automation.apply import Slot, describe_meal
from tandoor_automation.bundle import PlanBundle, build_bundle, next_week, parse_week
from tandoor_automation.config import Settings
from tandoor_automation.proposal import MARKS, Proposal, validate_proposal
from tandoor_automation.rating import parse_ratings
from tandoor_automation.shopping import Choice, Need, Question
from tandoor_automation.shopping import describe as describe_question
from tandoor_automation.tandoor import TandoorClient
from tandoor_automation.workflow import (
    LeadQuestion,
    apply_proposal,
    book_answers,
    clear_week,
    lead_questions,
    shopping_check,
    sync_ratings,
    write_list,
)

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
    wie er jetzt ist, nicht gegen den, wie er beim Wählen war. Ist die Woche danach vollständig in
    Tandoor, ist die Datei überflüssig: Tandoor ist die einzige Wahrheit, sie wird gelöscht.

    Auch `--dry-run` fragt vorher nach der Aufteilung der geteilten Plätze, denn erst sie sagt,
    welche Einträge entstehen.

    Args:
        path: Pfad der Vorschlagsdatei.
        dry_run: Nur zeigen, was geschrieben würde.
    """
    proposal = _read_proposal(path)
    with TandoorClient(Settings()) as tandoor:
        bundle = build_bundle(tandoor, proposal.week)
        leads = _ask_leads(lead_questions(proposal, bundle))
        applied = apply_proposal(tandoor, proposal, bundle, leads, dry_run)
    _report(applied.problems)
    for outcome, line in applied.lines:
        print(f"{outcome}: {line}")
    if not dry_run:
        path.unlink()


def _ask_leads(questions: list[LeadQuestion]) -> dict[Slot, int]:
    """Stellt die Fragen nach der Aufteilung im Terminal.

    Ohne Terminal im Rücken und bei leerer Eingabe fängt der erste Esser mit dem ersten Gericht
    an.

    Args:
        questions: Die Fragen aus `lead_questions`.

    Returns:
        Je gefragtem Platz das gewählte Gericht als Platz in seiner Gruppe.
    """
    leads = {}
    for question in questions:
        _, start, end = question.slot
        print(f"\n{question.meal_name} {start} bis {end}, {question.days} Tage")
        print(f"  Welches Gericht isst {MARKS[0]} {question.times}-mal?")
        for index, dish in enumerate(question.dishes):
            print(f"  {index} {dish}")
        leads[question.slot] = _read_lead(len(question.dishes))
    return leads


def _read_lead(count: int) -> int:
    """Liest eine Antwort, bis sie zu den Gerichten passt. Leer heißt: das erste."""
    while True:
        try:
            answer = input("  > ").strip()
        except EOFError:
            return 0
        if not answer:
            return 0
        if answer.isdigit() and int(answer) < count:
            return int(answer)
        print(f"  0 bis {count - 1}, oder leer für das erste")


def _run_clear(week: str | None, ids: list[int], dry_run: bool) -> None:
    """Nimmt die eigenen Planeinträge einer Woche wieder aus Tandoor heraus.

    Fremde Einträge werden genannt und bleiben stehen. Eine ID, die nicht in der Woche liegt,
    hält den Lauf an, bevor etwas gelöscht ist.

    Args:
        week: Zielwoche als ISO-Woche. Ohne Angabe die kommende Woche.
        ids: Nur diese Einträge löschen. Leer heißt: die ganze Woche.
        dry_run: Nur zeigen, was gelöscht würde.
    """
    week = week or next_week(date.today())
    with TandoorClient(Settings()) as tandoor:
        cleared = clear_week(tandoor, week, ids, dry_run)
    _report([f"{entry} liegt nicht in {week}" for entry in cleared.missing])
    for meal in cleared.others:
        print(f"fremd, bleibt: {describe_meal(meal)}")
    verb = "würde löschen" if dry_run else "gelöscht"
    for meal in cleared.mine:
        print(f"{verb}: {describe_meal(meal)}")
    total = "zu löschen" if dry_run else "gelöscht"
    print(f"{week}: {len(cleared.mine)} Einträge {total}, {len(cleared.others)} fremd")


def _run_rate(dry_run: bool) -> None:
    """Gleicht die Grundbewertung aus `bewertung.tsv` mit Tandoors Kochprotokoll ab.

    Die Datei ist die Quelle: eine Note, die dort auf 0 steht, wird in Tandoor gelöscht.

    Args:
        dry_run: Nur zeigen, was geschrieben würde.
    """
    ratings = parse_ratings(RATINGS_FILE.read_text(encoding="utf-8"))
    with TandoorClient(Settings()) as tandoor:
        synced = sync_ratings(tandoor, ratings, dry_run)
    if synced.unknown:
        print(f"{RATINGS_FILE}: unbekannte Rezepte {synced.unknown}")
        raise SystemExit(1)
    for change in synced.todo:
        verb = "löschen" if not change.stars else ("ändern" if change.log_id else "anlegen")
        print(
            f"{'würde ' if dry_run else ''}{verb}: {change.stars}★ {synced.names[change.recipe_id]}"
        )
    print(f"{len(synced.todo)} Änderungen, {len(ratings) - len(synced.todo)} schon richtig")


def _run_shop(week: str | None, dry_run: bool) -> None:
    """Fragt den Bestand ab und schreibt daraus die Einkaufsliste der Woche.

    Args:
        week: Zielwoche als ISO-Woche. Ohne Angabe die kommende Woche.
        dry_run: Nur zeigen, was geschrieben würde. Gefragt wird trotzdem.
    """
    target = week or next_week(date.today())
    today = date.today()
    with TandoorClient(Settings()) as tandoor:
        check = shopping_check(tandoor, target, today)
        answers = _ask(check.review.questions, check.demand)
        bookings = book_answers(tandoor, check.review, answers, today, dry_run)
        listed = write_list(tandoor, check, answers, dry_run)
    for booking in bookings:
        if dry_run:
            print(
                f"würde buchen: {booking.question.food_name} auf {booking.choice.amount}, "
                f"gefragt wieder ab {booking.trusted_until}"
            )
    for item in listed.added:
        need = check.demand.get(item.food_id)
        reason = f" ({', '.join(need.recipes)})" if need else ""
        print(f"{'würde ' if dry_run else ''}auf die Liste: {item.food_name}{reason}")
    print(
        f"{len(answers)} von {len(check.review.questions)} Fragen beantwortet, "
        f"{len(listed.added)} auf die Liste, {listed.already} standen schon drauf"
    )


def _ask(questions: list[Question], demand: dict[int, Need]) -> dict[int, Choice]:
    """Stellt die Fragen im Terminal, nach Ort gebündelt.

    Eine leere Eingabe überspringt: die Frage bleibt unbeantwortet, und unbeantwortet heißt
    kaufen. Ohne Terminal im Rücken wird gar nicht gefragt, dann geht alles Fragliche auf die
    Liste.

    Args:
        questions: Die Fragen, nach Ort und Name sortiert.
        demand: Bedarf der Woche je Lebensmittel, wird über den Knöpfen gezeigt.

    Returns:
        Die gewählte Antwort je Eintrags-ID, nur für die beantworteten Fragen.
    """
    if not questions:
        return {}
    answers: dict[int, Choice] = {}
    place = ""
    for question in questions:
        if question.location != place:
            place = question.location
            print(f"\n{place or 'ohne Ort'}")
        print(f"  {describe_question(question, demand.get(question.food_id))}")
        choice = _read_choice(question)
        if choice is not None:
            answers[question.entry_id] = choice
    return answers


def _read_choice(question: Question) -> Choice | None:
    """Liest eine Antwort, bis sie zu den Knöpfen passt. Leer heißt übersprungen."""
    while True:
        try:
            answer = input("  > ").strip()
        except EOFError:
            return None
        if not answer:
            return None
        if answer.isdigit() and int(answer) < len(question.choices):
            return question.choices[int(answer)]
        print(f"  {0} bis {len(question.choices) - 1}, oder leer zum Überspringen")


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
    shop = commands.add_parser("shop", help="Bestand abfragen und die Einkaufsliste schreiben")
    shop.add_argument(
        "--week",
        help="Zielwoche als ISO-Woche, etwa 2026-W39. Ohne Angabe die kommende Woche.",
    )
    shop.add_argument("--dry-run", action="store_true", help="Nur zeigen, was geschrieben würde")
    clear = commands.add_parser("clear", help="Eigene Planeinträge einer Woche wieder löschen")
    clear.add_argument(
        "--week",
        help="Zielwoche als ISO-Woche, etwa 2026-W39. Ohne Angabe die kommende Woche.",
    )
    clear.add_argument(
        "--eintrag",
        type=int,
        action="append",
        default=[],
        metavar="ID",
        help="Nur diesen Eintrag löschen, mehrfach angebbar. Ohne Angabe die ganze Woche.",
    )
    clear.add_argument("--dry-run", action="store_true", help="Nur zeigen, was gelöscht würde")
    args = parser.parse_args()
    if args.command == "check":
        _run_check(args.datei)
    elif args.command == "apply":
        _run_apply(args.datei, args.dry_run)
    elif args.command == "rate":
        _run_rate(args.dry_run)
    elif args.command == "shop":
        _run_shop(args.week, args.dry_run)
    elif args.command == "clear":
        _run_clear(args.week, args.eintrag, args.dry_run)
    else:
        print(write_bundle(args.week))
