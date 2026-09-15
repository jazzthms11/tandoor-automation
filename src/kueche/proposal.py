"""Der Wochenvorschlag eines Wählers und die Prüfung, die vor dem Schreiben nach Tandoor läuft.

Der Vorschlag kommt von einem Modell und wird deshalb nicht geglaubt, sondern geprüft. Geprüft
wird nur, was sich mechanisch prüfen lässt: gibt es das Rezept, passt Name zu ID, liegt der
Zeitraum in der Woche, ist ein Platz doppelt belegt, wird jeder Platz der Woche satt. Ob die Wahl
gut ist, also abwechslungsreich, eiweißreich und vegetarisch, entscheidet das Modell.
"""

from datetime import date, timedelta

from pydantic import BaseModel

from kueche.bundle import PlanBundle
from kueche.models import MealType

HOUSEHOLD = 2
TOLERANCE = 0.01


class ProposalEntry(BaseModel):
    """Ein Gericht in dem Zeitraum, über den es gegessen wird.

    Der Zeitraum ist nicht der Kochtag: ein vorgekochtes Mittagessen läuft von Montag bis Freitag,
    ein Abendessen über zwei Abende. Die Uhrzeit steuert die Mahlzeit bei, `plan apply` setzt sie
    beim Schreiben ein. `recipe_name` steht neben der ID, damit die Datei lesbar bleibt und ein
    vertauschtes Rezept auffällt.
    """

    recipe_id: int
    recipe_name: str
    meal_type_id: int
    from_date: date
    to_date: date
    servings: float
    note: str = ""


class Proposal(BaseModel):
    """Der Wochenplan, den ein Wähler aus dem Bündel zusammengestellt hat."""

    week: str
    entries: list[ProposalEntry]


def _portions_per_day(entry: ProposalEntry) -> float:
    """Verteilt die Portionen eines Eintrags gleichmäßig auf seine Tage."""
    return entry.servings / ((entry.to_date - entry.from_date).days + 1)


def _is_occupied(bundle: PlanBundle, meal_type: MealType, day: date) -> bool:
    """Prüft, ob ein Platz der Zielwoche schon in Tandoor steht."""
    return any(
        meal.meal_type_name == meal_type.name
        and meal.from_date.date() <= day <= meal.to_date.date()
        for meal in bundle.occupied
    )


def _recipe_problems(entry: ProposalEntry, bundle: PlanBundle) -> list[str]:
    """Prüft Rezept und Mahlzeit eines Eintrags gegen das Bündel."""
    problems = []
    recipe = next(
        (candidate for candidate in bundle.recipes if candidate.id == entry.recipe_id), None
    )
    if recipe is None:
        problems.append(f"Rezept {entry.recipe_id} ('{entry.recipe_name}') steht nicht im Bündel")
    elif recipe.name != entry.recipe_name:
        problems.append(
            f"Rezept {entry.recipe_id} heißt '{recipe.name}', nicht '{entry.recipe_name}'"
        )
    if all(meal_type.id != entry.meal_type_id for meal_type in bundle.meal_types):
        problems.append(f"'{entry.recipe_name}': Mahlzeit {entry.meal_type_id} gibt es nicht")
    return problems


def _period_problems(entry: ProposalEntry, bundle: PlanBundle) -> list[str]:
    """Prüft Zeitraum und Portionen eines Eintrags.

    Der letzte Tag darf einen Tag über die Woche hinausragen: das Abendessen vom Sonntag wird für
    Sonntag und den Montag danach gekocht, und dieser Montag gehört schon zur nächsten Woche.
    """
    first, last = bundle.days[0], bundle.days[-1]
    problems = []
    if entry.to_date < entry.from_date:
        problems.append(f"'{entry.recipe_name}': endet am {entry.to_date} vor dem Anfang")
    if not first <= entry.from_date <= last:
        problems.append(f"'{entry.recipe_name}': beginnt am {entry.from_date} außerhalb der Woche")
    if entry.to_date > last + timedelta(days=1):
        problems.append(f"'{entry.recipe_name}': endet am {entry.to_date}, zu weit nach der Woche")
    if entry.servings <= 0:
        problems.append(f"'{entry.recipe_name}': {entry.servings} Portionen")
    return problems


def _collision_problems(proposal: Proposal, bundle: PlanBundle) -> list[str]:
    """Findet Einträge, die einen in Tandoor schon belegten Platz überschreiben würden."""
    names = {meal_type.id: meal_type.name for meal_type in bundle.meal_types}
    problems = []
    for entry in proposal.entries:
        for meal in bundle.occupied:
            if meal.meal_type_name != names.get(entry.meal_type_id):
                continue
            if entry.from_date <= meal.to_date.date() and entry.to_date >= meal.from_date.date():
                belegt = meal.recipe_name or meal.title
                problems.append(
                    f"'{entry.recipe_name}' trifft auf '{belegt}' am {meal.from_date.date()}"
                )
    return problems


def _coverage_problems(proposal: Proposal, bundle: PlanBundle) -> list[str]:
    """Findet Plätze der Woche, für die zu wenige Portionen eingeplant sind.

    Ein Platz, den Tandoor schon belegt, bleibt außen vor: dort steht bereits etwas, sei es ein
    Gericht aus der Vorwoche oder ein Eintrag wie "Urlaub".
    """
    problems = []
    for day in bundle.days:
        for meal_type in bundle.meal_types:
            if _is_occupied(bundle, meal_type, day):
                continue
            served = sum(
                _portions_per_day(entry)
                for entry in proposal.entries
                if entry.meal_type_id == meal_type.id and entry.from_date <= day <= entry.to_date
            )
            if served < HOUSEHOLD - TOLERANCE:
                problems.append(f"{day} {meal_type.name}: {served:.1f} statt {HOUSEHOLD} Portionen")
    return problems


def validate_proposal(proposal: Proposal, bundle: PlanBundle) -> list[str]:
    """Prüft einen Vorschlag gegen das Bündel, aus dem er gewählt wurde.

    Args:
        proposal: Der Vorschlag des Wählers.
        bundle: Das Bündel derselben Woche.

    Returns:
        Alle gefundenen Mängel als Klartextzeilen. Leer heißt: der Vorschlag darf geschrieben
        werden.
    """
    if proposal.week != bundle.week:
        return [f"Vorschlag gilt {proposal.week}, das Bündel {bundle.week}"]
    problems = []
    for entry in proposal.entries:
        problems += _recipe_problems(entry, bundle)
        problems += _period_problems(entry, bundle)
    return problems + _collision_problems(proposal, bundle) + _coverage_problems(proposal, bundle)
