"""Der Weg vom geprüften Vorschlag in Tandoors Plan.

Zwei Dinge passieren hier, die `plan check` nicht braucht. Erstens wird aus dem reinen Tag eines
Eintrags ein Zeitstempel, denn Tandoor führt einen Planeintrag mit der Uhrzeit seiner Mahlzeit.
Zweitens wird der Vorschlag gegen den aktuellen Stand in Tandoor gehalten, damit ein zweiter Lauf
nichts doppelt schreibt: was schon genau so dort steht, gilt als erledigt und nicht als Kollision.
"""

from datetime import date, datetime, time

from tandoor_automation.bundle import PlanBundle
from tandoor_automation.models import MealType, PlannedMeal
from tandoor_automation.proposal import TOLERANCE, Proposal, ProposalEntry

MIDNIGHT = time(0, 0)

Match = tuple[ProposalEntry, PlannedMeal | None]


def meal_type_of(bundle: PlanBundle, entry: ProposalEntry) -> MealType | None:
    """Sucht die Mahlzeit eines Eintrags im Bündel.

    Args:
        bundle: Das Bündel der Woche.
        entry: Der Eintrag des Vorschlags.

    Returns:
        Die Mahlzeit, oder nichts, wenn es die ID nicht gibt.
    """
    return next(
        (candidate for candidate in bundle.meal_types if candidate.id == entry.meal_type_id), None
    )


def describe(entry: ProposalEntry, meal_type: MealType | None) -> str:
    """Nennt einen Eintrag so, wie er in der Ausgabe von `plan apply` wiederzuerkennen ist."""
    span = str(entry.from_date)
    if entry.to_date != entry.from_date:
        span = f"{entry.from_date} bis {entry.to_date}"
    name = meal_type.name if meal_type else f"Mahlzeit {entry.meal_type_id}"
    return f"{span} {name}: {entry.recipe_name or entry.title}"


def _is_twin(entry: ProposalEntry, meal: PlannedMeal, meal_type: MealType) -> bool:
    """Prüft, ob ein Planeintrag genau der ist, den dieser Vorschlagseintrag anlegen würde."""
    return (
        meal.meal_type_name == meal_type.name
        and meal.from_date.date() == entry.from_date
        and meal.to_date.date() == entry.to_date
        and meal.recipe_id == entry.recipe_id
        and meal.title == entry.title
        and abs(meal.servings - entry.servings) < TOLERANCE
    )


def match_existing(proposal: Proposal, bundle: PlanBundle) -> list[Match]:
    """Ordnet jedem Eintrag des Vorschlags den Planeintrag zu, der ihn schon erfüllt.

    Aus einem zweiten Lauf über denselben Vorschlag wird so ein Lauf ohne Schreibzugriff. Jeder
    Planeintrag kann nur einmal zugeordnet werden, sonst würden zwei gleiche Einträge im Vorschlag
    beide auf denselben Zwilling zeigen und der zweite nie geschrieben.

    Args:
        proposal: Der Vorschlag des Wählers.
        bundle: Ein frisch aus Tandoor gebautes Bündel derselben Woche.

    Returns:
        Zu jedem Eintrag sein Zwilling in Tandoor, oder nichts, wenn er noch fehlt.
    """
    taken: set[int] = set()
    matches: list[Match] = []
    for entry in proposal.entries:
        meal_type = meal_type_of(bundle, entry)
        twin = None
        if meal_type is not None:
            twin = next(
                (
                    meal
                    for meal in bundle.occupied
                    if meal.id not in taken and _is_twin(entry, meal, meal_type)
                ),
                None,
            )
        if twin is not None:
            taken.add(twin.id)
        matches.append((entry, twin))
    return matches


def without(bundle: PlanBundle, meals: list[PlannedMeal]) -> PlanBundle:
    """Nimmt schon geschriebene Einträge aus den belegten Plätzen des Bündels.

    Ohne das würde ein zweiter Lauf den eigenen ersten als Doppelbelegung melden.

    Args:
        bundle: Das Bündel der Woche.
        meals: Die Planeinträge, die aus dem Vorschlag selbst stammen.

    Returns:
        Ein Bündel, dessen `occupied` nur noch fremde Plätze enthält.
    """
    ids = {meal.id for meal in meals}
    keep = [meal for meal in bundle.occupied if meal.id not in ids]
    return bundle.model_copy(update={"occupied": keep})


def payload(entry: ProposalEntry, meal_type: MealType) -> dict[str, object]:
    """Baut den Körper für `POST /api/meal-plan/`.

    Rezept und Mahlzeit gehen als verschachteltes Objekt hinein; Tandoor erwartet dort die ID und
    den Namen, nicht die bloße Zahl.

    Args:
        entry: Der Eintrag des Vorschlags.
        meal_type: Seine Mahlzeit samt Uhrzeit.

    Returns:
        Der Körper der Anfrage.
    """
    served = meal_type.served_at or MIDNIGHT
    recipe = None
    if entry.recipe_id is not None:
        recipe = {"id": entry.recipe_id, "name": entry.recipe_name}
    return {
        "title": entry.title,
        "note": entry.note,
        "servings": entry.servings,
        "from_date": _stamp(entry.from_date, served),
        "to_date": _stamp(entry.to_date, served),
        "meal_type": {"id": meal_type.id, "name": meal_type.name},
        "recipe": recipe,
    }


def _stamp(day: date, served: time) -> str:
    """Macht aus Tag und Uhrzeit einen Zeitstempel in der Zeitzone dieses Rechners."""
    return datetime.combine(day, served).astimezone().isoformat()
