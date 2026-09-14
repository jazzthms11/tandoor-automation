"""Rezepte und Planeinträge, eingedampft auf das, was für die Planung zählt.

Tandoor liefert an jedem Rezept die vollständigen Nährwerte jeder Zutat mit, rund 45 KB pro
Rezept. Die Modelle hier greifen nur die Felder heraus, die für die Wahl eines Gerichts zählen;
alles andere verwirft Pydantic beim Parsen.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class Recipe(BaseModel):
    """Ein Rezept aus `/api/recipe/`, reduziert auf Aufwand, Schlagworte und Kochhistorie."""

    id: int
    name: str
    keywords: list[str] = Field(default_factory=list)
    working_time: int
    waiting_time: int
    servings: int
    rating: float | None = None
    last_cooked: datetime | None = None

    @field_validator("keywords", mode="before")
    @classmethod
    def _labels_only(cls, value: list[dict[str, str]]) -> list[str]:
        """Ersetzt die Schlagwort-Objekte durch ihre Anzeigenamen."""
        return [keyword["label"] for keyword in value]


class PlannedMeal(BaseModel):
    """Ein Eintrag aus `/api/meal-plan/`, reduziert auf Zeitraum, Mahlzeit und Gericht.

    Ein Eintrag muss kein Rezept haben: `recipe_id` und `recipe_name` bleiben dann leer und nur
    `title` sagt, was den Platz belegt, etwa "Urlaub". Solche Einträge gehen oft über mehrere Tage,
    `from_date` und `to_date` sind deshalb nicht zwingend derselbe Tag.

    Beide Daten tragen die Uhrzeit der Mahlzeit, Mittagessen etwa 12:00 in lokaler Zeitzone.
    """

    id: int
    title: str = ""
    from_date: datetime
    to_date: datetime
    meal_type_name: str
    recipe_id: int | None = Field(default=None, validation_alias="recipe")
    recipe_name: str = ""
    servings: float

    @field_validator("recipe_id", mode="before")
    @classmethod
    def _recipe_id(cls, value: dict[str, int] | int | None) -> int | None:
        """Zieht die ID aus dem eingebetteten Rezept, falls eines am Eintrag hängt."""
        return value["id"] if isinstance(value, dict) else value
