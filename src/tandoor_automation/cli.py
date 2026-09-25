"""Einstiegspunkt `plan`."""

import argparse
from datetime import date
from pathlib import Path

from tandoor_automation.apply import (
    clearable,
    describe,
    describe_meal,
    match_existing,
    meal_type_of,
    payload,
    without,
)
from tandoor_automation.bundle import (
    SPILLOVER,
    PlanBundle,
    build_bundle,
    next_week,
    parse_week,
    week_days,
)
from tandoor_automation.classes import (
    CLASSES_FILE,
    EXCEPTIONS_FILE,
    fresh_foods,
    parse_categories,
    parse_exceptions,
    stock_foods,
)
from tandoor_automation.config import Settings
from tandoor_automation.models import PlannedMeal
from tandoor_automation.proposal import Proposal, validate_proposal
from tandoor_automation.rating import (
    changes,
    own_base_ratings,
    parse_ratings,
)
from tandoor_automation.rating import (
    payload as rating_payload,
)
from tandoor_automation.shopping import (
    INTERVALS_FILE,
    Choice,
    Need,
    Question,
    Review,
    buy_list,
    confirmed_until,
    needs,
    parse_intervals,
    review,
)
from tandoor_automation.shopping import (
    describe as describe_question,
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
    wie er jetzt ist, nicht gegen den, wie er beim Wählen war. Ist die Woche danach vollständig in
    Tandoor, ist die Datei überflüssig: Tandoor ist die einzige Wahrheit, sie wird gelöscht.

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
    if not dry_run:
        path.unlink()


def _run_clear(week: str | None, ids: list[int], dry_run: bool) -> None:
    """Nimmt die eigenen Planeinträge einer Woche wieder aus Tandoor heraus.

    Gelöscht wird nur, was unter dem eigenen Token angelegt wurde: die Instanz ist geteilt, und
    der Platz eines Mitessers ist keine eigene Entscheidung. Fremde Einträge werden genannt und
    bleiben stehen.

    Args:
        week: Zielwoche als ISO-Woche. Ohne Angabe die kommende Woche.
        ids: Nur diese Einträge löschen. Leer heißt: die ganze Woche.
        dry_run: Nur zeigen, was gelöscht würde.
    """
    week = week or next_week(date.today())
    days = week_days(week)
    with TandoorClient(Settings()) as tandoor:
        meals = tandoor.meal_plan(days[0], days[-1] + SPILLOVER)
        mine, others = clearable(meals, days, tandoor.current_user_id(), set(ids))
        _report([f"{entry} liegt nicht in {week}" for entry in _missing(ids, mine, others)])
        for meal in others:
            print(f"fremd, bleibt: {describe_meal(meal)}")
        for meal in mine:
            if dry_run:
                print(f"würde löschen: {describe_meal(meal)}")
            else:
                tandoor.delete_meal(meal.id)
                print(f"gelöscht: {describe_meal(meal)}")
    verb = "zu löschen" if dry_run else "gelöscht"
    print(f"{week}: {len(mine)} Einträge {verb}, {len(others)} fremd")


def _missing(ids: list[int], mine: list[PlannedMeal], others: list[PlannedMeal]) -> list[int]:
    """Sagt, welche der genannten IDs in der Woche gar nicht vorkommen."""
    found = {meal.id for meal in mine + others}
    return sorted(set(ids) - found)


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


def _run_shop(week: str | None, dry_run: bool) -> None:
    """Fragt den Bestand ab und schreibt daraus die Einkaufsliste der Woche.

    Der Schritt liegt zwischen Plan und Einkauf: die Gerichte müssen stehen, damit die Fragen
    entstehen, und die Bons der Vorwoche müssen gebucht sein, damit die Staffel auf dem richtigen
    Bestand rechnet.

    Args:
        week: Zielwoche als ISO-Woche. Ohne Angabe die kommende Woche.
        dry_run: Nur zeigen, was geschrieben würde. Gefragt wird trotzdem.
    """
    target = week or next_week(date.today())
    today = date.today()
    with TandoorClient(Settings()) as tandoor:
        categories = parse_categories(CLASSES_FILE.read_text(encoding="utf-8"))
        exceptions = parse_exceptions(EXCEPTIONS_FILE.read_text(encoding="utf-8"))
        foods = tandoor.foods()
        demand = _planned_needs(tandoor, target)
        found = review(
            set(demand),
            tandoor.inventory(),
            stock_foods(foods, categories, exceptions),
            fresh_foods(foods, categories, exceptions),
            {unit_id: name for name, unit_id in tandoor.units().items()},
            today,
        )
        answers = _ask(found.questions, demand)
        _write_shopping(tandoor, found, answers, today, dry_run)


def _planned_needs(tandoor: TandoorClient, week: str) -> dict[int, Need]:
    """Sammelt, was die Gerichte einer Woche brauchen, je Lebensmittel.

    Die Zutaten stehen nur im Detailabruf, das ist ein Aufruf je Rezept. Bei einer Woche sind das
    eine Handvoll, die Rezeptliste im Ganzen zu holen wäre teurer. Jedes Rezept wird einmal
    geholt, auch wenn es zweimal im Plan steht.
    """
    days = week_days(week)
    meals = tandoor.meal_plan(days[0], days[-1] + SPILLOVER)
    details = {
        recipe_id: tandoor.recipe_detail(recipe_id)
        for recipe_id in sorted({meal.recipe_id for meal in meals if meal.recipe_id})
    }
    return needs(meals, details)


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


def _write_shopping(
    tandoor: TandoorClient,
    found: Review,
    answers: dict[int, Choice],
    today: date,
    dry_run: bool,
) -> None:
    """Schreibt die Antworten in den Bestand und das Fehlende auf die Einkaufsliste.

    Unbeantwortete Fragen fassen den Bestand nicht an: keine Antwort ist keine Bestätigung. Auf
    die Liste kommen sie trotzdem.
    """
    intervals = parse_intervals(INTERVALS_FILE.read_text(encoding="utf-8"))
    for question in found.questions:
        choice = answers.get(question.entry_id)
        if choice is None:
            continue
        trusted_until = confirmed_until(today, question.food_id, intervals)
        if dry_run:
            print(
                f"würde buchen: {question.food_name} auf {choice.amount}, "
                f"gefragt wieder ab {trusted_until}"
            )
        else:
            tandoor.update_inventory_entry(question.entry_id, choice.amount, trusted_until)
    listed = tandoor.shopping_list()
    wanted = buy_list(found, answers)
    todo = [item for item in wanted if item.food_id not in listed]
    for item in todo:
        if dry_run:
            print(f"würde auf die Liste: {item.food_name}")
        else:
            tandoor.create_shopping_entry(item.food_id)
            print(f"auf die Liste: {item.food_name}")
    print(
        f"{len(answers)} von {len(found.questions)} Fragen beantwortet, "
        f"{len(todo)} auf die Liste, {len(wanted) - len(todo)} standen schon drauf"
    )


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
