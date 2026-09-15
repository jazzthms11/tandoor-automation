"""Das Kontextbündel, aus dem ein Modell die Gerichte einer Woche wählt."""

import re
from datetime import date, timedelta

from pydantic import BaseModel

from tandoor_automation.models import MealType, PlannedMeal, Recipe
from tandoor_automation.tandoor import TandoorClient

HISTORY_WEEKS = 8
WEEK_PATTERN = re.compile(r"^(\d{4})-W(\d{2})$")


class PlanBundle(BaseModel):
    """Alles, was für die Wahl der Gerichte einer Woche gebraucht wird.

    `occupied` und `history` sind dieselbe Sorte Eintrag, nur in verschiedenen Zeiträumen:
    `occupied` belegt Plätze in der Zielwoche, `history` sagt, was zuletzt auf dem Tisch stand.
    """

    week: str
    days: list[date]
    meal_types: list[MealType]
    occupied: list[PlannedMeal]
    history: list[PlannedMeal]
    recipes: list[Recipe]


def parse_week(week: str) -> tuple[int, int]:
    """Zerlegt eine ISO-Woche in Jahr und Wochennummer.

    Args:
        week: Woche in der Form `2026-W38`.

    Returns:
        Jahr und Wochennummer.

    Raises:
        ValueError: Wenn die Form nicht stimmt oder die Woche im Jahr nicht existiert.
    """
    match = WEEK_PATTERN.match(week)
    if not match:
        raise ValueError(f"'{week}' ist keine ISO-Woche, erwartet wird etwa '2026-W38'")
    year, number = int(match[1]), int(match[2])
    date.fromisocalendar(year, number, 1)
    return year, number


def week_days(week: str) -> list[date]:
    """Gibt die sieben Tage einer ISO-Woche, Montag zuerst.

    Args:
        week: Woche in der Form `2026-W38`.

    Returns:
        Montag bis Sonntag.
    """
    year, number = parse_week(week)
    return [date.fromisocalendar(year, number, day) for day in range(1, 8)]


def next_week(today: date) -> str:
    """Gibt die auf `today` folgende ISO-Woche.

    Args:
        today: Bezugstag.

    Returns:
        Woche in der Form `2026-W38`.
    """
    year, number, _ = (today + timedelta(days=7)).isocalendar()
    return f"{year}-W{number:02d}"


def overlaps(meal: PlannedMeal, start: date, end: date) -> bool:
    """Prüft, ob ein Planeintrag in einen Zeitraum hineinragt.

    Ein Eintrag kann über mehrere Tage laufen, etwa wenn dasselbe Gericht zweimal auf den Tisch
    kommt. Ein Vergleich auf ein einzelnes Datum würde solche Einträge übersehen.

    Args:
        meal: Der Planeintrag.
        start: Erster Tag des Zeitraums, einschließlich.
        end: Letzter Tag des Zeitraums, einschließlich.

    Returns:
        Ob sich Eintrag und Zeitraum überschneiden.
    """
    return meal.from_date.date() <= end and meal.to_date.date() >= start


def build_bundle(tandoor: TandoorClient, week: str) -> PlanBundle:
    """Holt alles Nötige aus Tandoor und stellt es für die Zielwoche zusammen.

    Args:
        tandoor: Offener Client.
        week: Zielwoche in der Form `2026-W38`.

    Returns:
        Das fertige Bündel.
    """
    days = week_days(week)
    start, end = days[0], days[-1]
    meals = tandoor.meal_plan(start - timedelta(weeks=HISTORY_WEEKS), end)
    return PlanBundle(
        week=week,
        days=days,
        meal_types=tandoor.meal_types(),
        occupied=[meal for meal in meals if overlaps(meal, start, end)],
        history=[meal for meal in meals if not overlaps(meal, start, end)],
        recipes=tandoor.recipes(),
    )
