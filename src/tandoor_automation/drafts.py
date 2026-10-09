"""Der Entwurf eines Wochenplans: entstehen lassen, anpassen, freigeben. Ohne Ein- und Ausgabe.

Der Entwurf liegt in der Datenbank, nicht mehr als Datei unter `vorschlag/`. Ihn ändern zwei
Wege: das Modell über einen Wunsch in Worten, und die Hand über Tausch, Termin, Portionen und
Notiz. Nach jeder Änderung läuft dieselbe Prüfung wie vor dem Schreiben, gegen das Bündel, aus dem
gewählt wurde. Erst die Freigabe holt den Stand frisch aus Tandoor.

Jede Änderung nennt die Version, von der sie ausging. Hat jemand anderes inzwischen geändert,
schlägt sie fehl, statt dessen Änderung still zu überschreiben.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from tandoor_automation import store
from tandoor_automation.apply import Slot, together_of
from tandoor_automation.bundle import PlanBundle, build_bundle
from tandoor_automation.chooser import Chosen, Model, check, choose
from tandoor_automation.models import Recipe
from tandoor_automation.proposal import HOUSEHOLD, Proposal, ProposalEntry
from tandoor_automation.tandoor import TandoorClient
from tandoor_automation.workflow import Applied, LeadQuestion, apply_proposal, lead_questions

MIN_WEEKS = {5: 1, 4: 2, 3: 4, 0: 1}
"""Wie viele Wochen ein Gericht mindestens zurückliegen muss, je Note. Was fehlt, darf nicht.

Aus der Tabelle in den Regeln: 5 darf zwei Wochen hintereinander, 4 nach einer Woche Pause, 3 nach
etwa vier Wochen. Unbewertet ist erlaubt. 2 nur auf Wunsch und 1 nie, beide stehen deshalb nicht in
der Liste, sind über die Suche aber zu finden."""
NOT_A_MEAL = {"beilage", "nachtisch", "süß", "soßen", "basisrezepte"}
VEGETARIAN = "vegetarisch"
MEALPREP = "mealprep"
CANDIDATES = 12


@dataclass(frozen=True)
class WeekDraft:
    """Ein Entwurf, wie er aus der Datenbank kommt."""

    week: str
    proposal: Proposal
    bundle: PlanBundle
    reasoning: str
    hints: str
    problems: list[str]
    version: int
    released_at: datetime | None

    def problems_of(self, entry: ProposalEntry) -> list[str]:
        """Die Mängel, die einen Eintrag beim Namen nennen."""
        label = entry.recipe_name or entry.title
        return [problem for problem in self.problems if label and label in problem]


@dataclass(frozen=True)
class Candidate:
    """Ein Gericht, das einen Platz übernehmen könnte."""

    recipe: Recipe
    weeks_ago: int | None
    """Vor wie vielen Wochen es zuletzt dran war. Ohne Angabe nie in der Historie."""
    allowed: bool


def load(week: str) -> WeekDraft | None:
    """Der Entwurf einer Woche, wenn es einen gibt."""
    row = store.draft(week)
    if row is None:
        return None
    return WeekDraft(
        week=row.week,
        proposal=Proposal.model_validate_json(row.proposal),
        bundle=PlanBundle.model_validate_json(row.bundle),
        reasoning=row.reasoning,
        hints=row.hints,
        problems=json.loads(row.problems),
        version=row.version,
        released_at=row.released_at,
    )


def create(tandoor: TandoorClient, model: Model, week: str, hints: str) -> WeekDraft:
    """Holt das Bündel, lässt das Modell wählen und legt den Entwurf ab.

    Ein vorhandener Entwurf derselben Woche wird ersetzt: wer neu entwerfen lässt, will den alten
    nicht mehr.

    Raises:
        ChooserError: Wenn das Modell nicht oder falsch antwortet. Der alte Entwurf bleibt dann.
    """
    bundle = build_bundle(tandoor, week)
    chosen = choose(model, bundle, hints)
    return _save(week, chosen, bundle, hints, None)


def revise(model: Model, week: str, version: int, request: str) -> WeekDraft:
    """Lässt das Modell den Entwurf nach einem Wunsch in Worten ändern.

    Raises:
        StaleDraftError: Wenn der Entwurf inzwischen anders aussieht.
        ChooserError: Wenn das Modell nicht oder falsch antwortet.
    """
    current = _current(week, version)
    previous = Chosen(current.proposal, current.reasoning, current.problems)
    chosen = choose(model, current.bundle, current.hints, previous, request)
    return _save(week, chosen, current.bundle, current.hints, version)


def rechoose(model: Model, week: str, version: int, index: int, wish: str) -> WeekDraft:
    """Lässt das Modell für genau einen Platz ein anderes Gericht wählen."""
    current = _current(week, version)
    entry = _entry(current.proposal, index)
    name = entry.recipe_name or entry.title
    request = (
        f"Wähle für '{name}' vom {entry.from_date} bis {entry.to_date} ein anderes Gericht. "
        "Alles andere bleibt, außer was laut den Regeln daran hängt."
    )
    if wish.strip():
        request += f" Wunsch dazu: {wish.strip()}"
    return revise(model, week, version, request)


def replace_recipe(week: str, version: int, index: int, recipe_id: int) -> WeekDraft:
    """Setzt ein anderes Gericht auf einen Platz.

    Steht dasselbe Gericht noch an einem anderen Platz, wandert es dort mit. Das ist das Paar aus
    Samstagabend und Sonntagmittag, für das am Samstag gekocht wird. Doppelt steht ein Gericht
    sonst nirgends.
    """

    def change(proposal: Proposal, bundle: PlanBundle) -> None:
        recipe = next((r for r in bundle.recipes if r.id == recipe_id), None)
        if recipe is None:
            raise ValueError(f"Rezept {recipe_id} steht nicht im Kochbuch")
        old = _entry(proposal, index)
        for position, entry in enumerate(proposal.entries):
            if position == index or (
                old.recipe_id is not None and entry.recipe_id == old.recipe_id
            ):
                proposal.entries[position] = entry.model_copy(
                    update={
                        "recipe_id": recipe.id,
                        "recipe_name": recipe.name,
                        "title": "",
                        "servings": entry.servings or _full(entry),
                    }
                )

    return _edit(week, version, change)


def make_appointment(week: str, version: int, index: int, title: str) -> WeekDraft:
    """Macht aus einem Platz einen Termin ohne Rezept, etwa Besuch oder auswärts essen."""
    if not title.strip():
        raise ValueError("Ein Termin braucht einen Titel")

    def change(proposal: Proposal, _: PlanBundle) -> None:
        entry = _entry(proposal, index)
        proposal.entries[index] = entry.model_copy(
            update={"recipe_id": None, "recipe_name": "", "title": title.strip(), "servings": 0}
        )

    return _edit(week, version, change)


def set_details(week: str, version: int, index: int, servings: float, note: str) -> WeekDraft:
    """Ändert Portionen und Notiz eines Platzes."""

    def change(proposal: Proposal, _: PlanBundle) -> None:
        entry = _entry(proposal, index)
        proposal.entries[index] = entry.model_copy(
            update={"servings": servings, "note": note.strip()}
        )

    return _edit(week, version, change)


def refresh_recipes(tandoor: TandoorClient, week: str, version: int) -> WeekDraft:
    """Holt das Kochbuch neu in den Entwurf, damit seit dem Entwurf angelegte Rezepte erscheinen.

    Nur die Rezepte samt Bewertung werden ersetzt. Plan und Historie bleiben, wie sie waren.

    Raises:
        StaleDraftError: Wenn der Entwurf inzwischen anders aussieht.
    """
    current = _current(week, version)
    bundle = current.bundle.model_copy(update={"recipes": tandoor.recipes()})
    chosen = Chosen(current.proposal, current.reasoning, check(current.proposal, bundle))
    return _save(week, chosen, bundle, current.hints, version)


def discard(week: str) -> None:
    """Verwirft den Entwurf einer Woche."""
    store.drop_draft(week)


def candidates(draft: WeekDraft, index: int, query: str = "") -> list[Candidate]:
    """Die Gerichte, die einen Platz übernehmen könnten, das passendste zuerst.

    Ohne Suchtext gelten die Regeln: erlaubt nach Note und Abstand, keine Beilagen, nichts, was
    schon im Entwurf steht. Vorn steht, was vegetarisch ist, für ein Mittagessen was sich vorkochen
    lässt, und dann, was am längsten her ist. Mit Suchtext zählt nur der Name, und auch
    Gesperrtes erscheint, markiert: ein Wunsch schlägt die Regel.
    """
    entry = _entry(draft.proposal, index)
    planned = {e.recipe_id for e in draft.proposal.entries if e.recipe_id != entry.recipe_id}
    start = draft.bundle.days[0]
    prepped = entry.meal_type_id not in together_of(draft.bundle)
    needle = query.strip().casefold()
    found = []
    for recipe in draft.bundle.recipes:
        keywords = {keyword.casefold() for keyword in recipe.keywords}
        if recipe.id in planned or recipe.id == entry.recipe_id:
            continue
        if needle and needle not in recipe.name.casefold():
            continue
        if not needle and keywords & NOT_A_MEAL:
            continue
        weeks_ago = _weeks_ago(draft.bundle, recipe.id, start)
        gap = MIN_WEEKS.get(recipe.rating)
        allowed = gap is not None and (weeks_ago is None or weeks_ago >= gap)
        if allowed or needle:
            found.append((recipe, keywords, Candidate(recipe, weeks_ago, allowed)))
    found.sort(
        key=lambda item: (
            not item[2].allowed,
            VEGETARIAN not in item[1],
            prepped and MEALPREP not in item[1],
            -(item[2].weeks_ago if item[2].weeks_ago is not None else 1000),
            item[0].name.casefold(),
        )
    )
    return [candidate for _, _, candidate in found[:CANDIDATES]]


def questions(draft: WeekDraft) -> list[LeadQuestion]:
    """Die Fragen vor der Freigabe: wer auf einem geteilten Platz mit welchem Gericht anfängt."""
    return lead_questions(draft.proposal, draft.bundle)


def release(
    tandoor: TandoorClient, week: str, version: int, leads: dict[Slot, int], dry_run: bool
) -> Applied:
    """Schreibt den Entwurf nach Tandoor, gegen den Stand von jetzt, wie `plan apply`.

    Ist alles geschrieben, gilt der Entwurf als freigegeben und bleibt zum Nachlesen liegen.

    Raises:
        StaleDraftError: Wenn der Entwurf inzwischen anders aussieht.
    """
    current = _current(week, version)
    applied = apply_proposal(tandoor, current.proposal, build_bundle(tandoor, week), leads, dry_run)
    if not dry_run and not applied.problems:
        released = store.Draft.model_validate(
            store.draft(week),
            update={"released_at": datetime.now().astimezone()},
        )
        store.put_draft(released, version)
    return applied


def _current(week: str, version: int) -> WeekDraft:
    current = load(week)
    if current is None or current.version != version:
        raise store.StaleDraftError(week)
    return current


def _entry(proposal: Proposal, index: int) -> ProposalEntry:
    if not 0 <= index < len(proposal.entries):
        raise ValueError(f"Den Eintrag {index} gibt es im Entwurf nicht")
    return proposal.entries[index]


def _edit(week: str, version: int, change: Callable[[Proposal, PlanBundle], None]) -> WeekDraft:
    """Ändert den Vorschlag von Hand, prüft neu und legt ihn ab. Die Begründung bleibt."""
    current = _current(week, version)
    proposal = current.proposal.model_copy(deep=True)
    change(proposal, current.bundle)
    chosen = Chosen(proposal, current.reasoning, check(proposal, current.bundle))
    return _save(week, chosen, current.bundle, current.hints, version)


def _save(
    week: str, chosen: Chosen, bundle: PlanBundle, hints: str, expected: int | None
) -> WeekDraft:
    row = store.put_draft(
        store.Draft(
            week=week,
            proposal=chosen.proposal.model_dump_json(),
            bundle=bundle.model_dump_json(),
            reasoning=chosen.reasoning,
            hints=hints,
            problems=json.dumps(chosen.problems, ensure_ascii=False),
        ),
        expected,
    )
    return WeekDraft(
        week, chosen.proposal, bundle, chosen.reasoning, hints, chosen.problems, row.version, None
    )


def _full(entry: ProposalEntry) -> float:
    """Portionen für einen Platz, der vorher ein Termin war: der ganze Haushalt, jeden Tag."""
    return float(((entry.to_date - entry.from_date).days + 1) * HOUSEHOLD)


def _weeks_ago(bundle: PlanBundle, recipe_id: int, start: date) -> int | None:
    """Vor wie vielen Wochen das Gericht zuletzt auf dem Tisch stand. Vorige Woche ist 1."""
    days = [
        meal.from_date.date()
        for meal in bundle.history
        if meal.recipe_id == recipe_id and meal.from_date.date() < start
    ]
    if not days:
        return None
    return ((start - max(days)).days - 1) // 7 + 1
