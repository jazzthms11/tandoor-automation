"""Der Weg vom geprüften Vorschlag in Tandoors Plan.

Zwei Dinge passieren hier, die `plan check` nicht braucht. Erstens wird aus dem reinen Tag eines
Eintrags ein Zeitstempel, denn Tandoor führt einen Planeintrag mit der Uhrzeit seiner Mahlzeit.
Zweitens wird der Vorschlag gegen den aktuellen Stand in Tandoor gehalten, damit ein zweiter Lauf
nichts doppelt schreibt: was schon genau so dort steht, gilt als erledigt und nicht als Kollision.

Davor liegt das Entfalten: aus den acht Einträgen des Vorschlags werden die Einträge, die Tandoor
wirklich führt, jeder mit den Marken seiner Esser in der ersten Zeile der `note`. Ein geteilter
Platz zerfällt dabei in einen Eintrag je Tag und Esser, denn sonst steht nirgends, wer an welchem
Tag welches der beiden vorgekochten Mittagessen isst.

Der Rückweg steht daneben: `clearable` sagt, welche Einträge einer Woche wieder verschwinden dürfen.
"""

from datetime import date, datetime, time, timedelta

from tandoor_automation.bundle import PlanBundle
from tandoor_automation.models import MealType, PlannedMeal
from tandoor_automation.proposal import (
    MARKS,
    TOLERANCE,
    Proposal,
    ProposalEntry,
    portions_per_day,
)

MIDNIGHT = time(0, 0)

Match = tuple[ProposalEntry, PlannedMeal | None]
Slot = tuple[int, date, date]
"""Ein Platz der Woche: seine Mahlzeit und sein Zeitraum."""


def slot_of(entry: ProposalEntry) -> Slot:
    """Nennt den Platz, den ein Eintrag belegt."""
    return (entry.meal_type_id, entry.from_date, entry.to_date)


def split_groups(proposal: Proposal) -> dict[Slot, list[ProposalEntry]]:
    """Findet die Plätze, an denen jeder Esser ein anderes Gericht bekommt.

    Erkennbar sind sie an der Rechnung: auf demselben Platz so viele Gerichte, wie es Esser gibt,
    und jedes davon mit genau einer Portion am Tag. Die beiden vorgekochten Mittagessen von Montag
    bis Freitag sind das, je fünf Portionen auf fünf Tage. Eine Beilage neben einem Hauptgericht
    ist es nicht: sie trägt für jeden Esser eine eigene Portion und verdoppelt damit die Portionen
    des Platzes.

    Args:
        proposal: Der Vorschlag des Wählers.

    Returns:
        Je geteiltem Platz seine Gerichte, in der Reihenfolge des Vorschlags.
    """
    groups: dict[Slot, list[ProposalEntry]] = {}
    for entry in proposal.entries:
        if entry.recipe_id is not None:
            groups.setdefault(slot_of(entry), []).append(entry)
    return {
        slot: group
        for slot, group in groups.items()
        if len(group) == len(MARKS)
        and all(abs(portions_per_day(entry) - 1) < TOLERANCE for entry in group)
    }


def unfold(proposal: Proposal, leads: dict[Slot, int]) -> Proposal:
    """Baut aus dem Vorschlag die Einträge, die wirklich nach Tandoor gehen.

    Jeder Eintrag mit Rezept bekommt die Esser als Marken, ein geteilter Platz zerfällt zusätzlich
    in einen Eintrag je Tag und Esser. Ein Termin ohne Rezept bleibt unberührt und ohne Marke: an
    ihm wird gegessen, aber nicht aus der eigenen Küche.

    Args:
        proposal: Der Vorschlag des Wählers.
        leads: Je geteiltem Platz das Gericht, mit dem der erste Esser am ersten Tag anfängt.
            Ein Platz ohne Eintrag fängt mit seinem ersten Gericht an.

    Returns:
        Derselbe Vorschlag, entfaltet und mit Marken.
    """
    groups = split_groups(proposal)
    done: set[Slot] = set()
    entries: list[ProposalEntry] = []
    for entry in proposal.entries:
        slot = slot_of(entry)
        if entry.recipe_id is None:
            entries.append(entry)
        elif slot not in groups:
            entries.append(entry.model_copy(update={"marks": list(MARKS)}))
        elif slot not in done:
            done.add(slot)
            entries += _shares(groups[slot], leads.get(slot, 0))
    return proposal.model_copy(update={"entries": entries})


def _shares(group: list[ProposalEntry], lead: int) -> list[ProposalEntry]:
    """Zerlegt einen geteilten Platz in einen Eintrag je Tag und Esser, zu je einer Portion.

    Gewechselt wird täglich: wer am ersten Tag das erste Gericht isst, bekommt am zweiten das
    zweite. Bei einer ungeraden Zahl von Tagen kommt deshalb das Gericht, mit dem der erste Esser
    anfängt, einmal öfter auf seinen Teller als das andere.
    """
    first = group[0]
    shares = []
    for index in range((first.to_date - first.from_date).days + 1):
        day = first.from_date + timedelta(days=index)
        for place, mark in enumerate(MARKS):
            dish = group[(lead + index + place) % len(group)]
            shares.append(
                dish.model_copy(
                    update={"from_date": day, "to_date": day, "servings": 1, "marks": [mark]}
                )
            )
    return shares


def share_problems(plan: Proposal) -> list[str]:
    """Findet Einträge, deren Portionen für die Esser nicht reichen, die an ihnen stehen.

    Der Anteil eines Essers ist `servings / Tage / Marken`, und wer die Nährwerte eines Tages
    daraus rechnet, glaubt diese Zahl. Zwei Mittagsgerichte über ungleiche Zeiträume bilden keinen
    geteilten Platz, bekommen deshalb beide Marken und halbierten still jeden Anteil. Die Deckung
    der Woche stimmt dabei, nur die Zuordnung nicht.

    Args:
        plan: Der entfaltete Vorschlag.

    Returns:
        Alle gefundenen Mängel als Klartextzeilen.
    """
    return [
        f"'{entry.recipe_name}' ab {entry.from_date}: {portions_per_day(entry):.1f} Portionen "
        f"am Tag für {len(entry.marks)} Esser"
        for entry in plan.entries
        if entry.marks and portions_per_day(entry) < len(entry.marks) - TOLERANCE
    ]


def note_of(entry: ProposalEntry) -> str:
    """Setzt die Marken der Esser in die erste Zeile der Notiz eines Eintrags."""
    return "\n".join(part for part in [" ".join(entry.marks), entry.note] if part)


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
    """Nennt einen Eintrag so, wie er in der Ausgabe von `plan apply` wiederzuerkennen ist.

    Die Marken stehen dahinter: nach dem Entfalten unterscheiden sich zwei Zeilen desselben Tages
    nur noch durch sie.
    """
    name = meal_type.name if meal_type else f"Mahlzeit {entry.meal_type_id}"
    marks = f" {' '.join(entry.marks)}" if entry.marks else ""
    return (
        f"{_span(entry.from_date, entry.to_date)} {name}: {entry.recipe_name or entry.title}{marks}"
    )


def _span(start: date, end: date) -> str:
    """Nennt den Zeitraum eines Eintrags, den einzelnen Tag ohne Wiederholung."""
    return str(start) if start == end else f"{start} bis {end}"


def describe_meal(meal: PlannedMeal) -> str:
    """Nennt einen Planeintrag samt seiner ID, so wie `plan clear` ihn ausgibt."""
    return f"{_span(meal.from_date.date(), meal.to_date.date())} {meal.meal_type_name}: " + (
        f"{meal.recipe_name or meal.title} [{meal.id}]"
    )


def clearable(
    meals: list[PlannedMeal], days: list[date], user_id: int, ids: set[int]
) -> tuple[list[PlannedMeal], list[PlannedMeal]]:
    """Teilt die Planeinträge einer Woche in die eigenen und die fremden.

    Maßgeblich ist der erste Tag eines Eintrags, nicht seine Überschneidung mit der Woche. Ein
    Abendessen für zwei Abende ragt über den Freitag hinaus und gehört trotzdem in diese Woche;
    eines, das am Freitag davor beginnt, gehört in die vorige und bleibt stehen.

    Args:
        meals: Die aus Tandoor geholten Einträge.
        days: Die Tage der Woche, Samstag zuerst.
        user_id: Die eigene Benutzer-ID.
        ids: Auf diese Einträge beschränken. Leer heißt: die ganze Woche.

    Returns:
        Die eigenen Einträge und die fremden, beide in der Reihenfolge ihres ersten Tages.
    """
    chosen = [meal for meal in meals if days[0] <= meal.from_date.date() <= days[-1]]
    if ids:
        chosen = [meal for meal in chosen if meal.id in ids]
    chosen.sort(key=lambda meal: (meal.from_date, meal.meal_type_name))
    return (
        [meal for meal in chosen if meal.created_by == user_id],
        [meal for meal in chosen if meal.created_by != user_id],
    )


def _is_twin(entry: ProposalEntry, meal: PlannedMeal, meal_type: MealType) -> bool:
    """Prüft, ob ein Planeintrag genau der ist, den dieser Vorschlagseintrag anlegen würde."""
    return (
        meal.meal_type_name == meal_type.name
        and meal.from_date.date() == entry.from_date
        and meal.to_date.date() == entry.to_date
        and meal.recipe_id == entry.recipe_id
        and meal.title == entry.title
        and meal.note == note_of(entry)
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
        "note": note_of(entry),
        "servings": entry.servings,
        "from_date": _stamp(entry.from_date, served),
        "to_date": _stamp(entry.to_date, served),
        "meal_type": {"id": meal_type.id, "name": meal_type.name},
        "recipe": recipe,
    }


def _stamp(day: date, served: time) -> str:
    """Macht aus Tag und Uhrzeit einen Zeitstempel in der Zeitzone dieses Rechners."""
    return datetime.combine(day, served).astimezone().isoformat()
