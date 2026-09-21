"""Rezepte und Planeinträge, eingedampft auf das, was für die Planung zählt.

Tandoor liefert an jedem Rezept die vollständigen Nährwerte jeder Zutat mit, rund 45 KB pro
Rezept. Die Modelle hier greifen nur die Felder heraus, die für die Wahl eines Gerichts zählen;
alles andere verwirft Pydantic beim Parsen.

Zwei Felder heißen hier anders als in der API. Sie tragen deshalb `AliasChoices` und nehmen beide
Schreibweisen an, denn dieselben Modelle lesen einmal Tandoors Antwort und einmal das Bündel, das
aus ihnen geschrieben wurde.
"""

from datetime import datetime, time

from pydantic import AliasChoices, AliasPath, BaseModel, Field, field_validator


class Recipe(BaseModel):
    """Ein Rezept aus `/api/recipe/`, reduziert auf Aufwand, Schlagworte und Kurzbeschreibung.

    `rating` ist die Grundbewertung aus `bewertung.tsv`, 5 heißt "geht quasi immer" und 1 "nie".
    Sie steht nicht in der Antwort von `/api/recipe/`, die trägt das Feld immer leer. Tandoor
    annotiert es nur beim Filtern, `TandoorClient.recipes` holt es deshalb getrennt nach.

    `last_cooked` fehlt mit Absicht: hier wird kein Kochtagebuch geführt, und wann ein Gericht
    zuletzt auf dem Tisch stand, sagt die Planhistorie im Bündel genauer.
    """

    id: int
    name: str
    description: str = ""
    keywords: list[str] = Field(default_factory=list)
    working_time: int
    waiting_time: int
    servings: int
    rating: int = 0

    @field_validator("description", mode="before")
    @classmethod
    def _no_none(cls, value: str | None) -> str:
        """Macht aus der fehlenden Beschreibung eine leere, die Hälfte der Rezepte hat keine."""
        return value or ""

    @field_validator("rating", mode="before")
    @classmethod
    def _unrated_is_zero(cls, value: float | None) -> int:
        """Macht aus der fehlenden Bewertung eine Null, so zählt Tandoor sie selbst auch."""
        return round(value or 0)

    @field_validator("keywords", mode="before")
    @classmethod
    def _labels_only(cls, value: list[dict[str, str] | str]) -> list[str]:
        """Ersetzt die Schlagwort-Objekte durch ihre Anzeigenamen."""
        return [keyword["label"] if isinstance(keyword, dict) else keyword for keyword in value]


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
    recipe_id: int | None = Field(
        default=None, validation_alias=AliasChoices("recipe", "recipe_id")
    )
    recipe_name: str = ""
    servings: float

    @field_validator("recipe_id", mode="before")
    @classmethod
    def _recipe_id(cls, value: dict[str, int] | int | None) -> int | None:
        """Zieht die ID aus dem eingebetteten Rezept, falls eines am Eintrag hängt."""
        return value["id"] if isinstance(value, dict) else value


class MealType(BaseModel):
    """Eine Mahlzeit des Tages aus `/api/meal-type/`.

    `served_at` heißt in der API `time` und ist die Uhrzeit, die Tandoor an jeden Planeintrag
    dieser Mahlzeit schreibt. Der abweichende Name ist nötig, weil ein Feld `time` seine eigene
    Typannotation verdeckt.
    """

    id: int
    name: str
    served_at: time | None = Field(default=None, validation_alias=AliasChoices("time", "served_at"))


class CookLog(BaseModel):
    """Ein Eintrag aus `/api/cook-log/`, reduziert auf Rezept, Note und Herkunft.

    Tandoor mittelt die Noten aller Einträge eines Rezepts, statt die neueste zu nehmen. Die
    Grundbewertung braucht deshalb genau einen Eintrag je Rezept, erkennbar an `comment`.

    `created_by_id` zählt, weil die Instanz geteilt ist: die Liste gibt die Einträge aller
    Mitesser zurück, Tandoors eigene Mittelung sieht dagegen nur die des anfragenden Nutzers.
    """

    id: int
    recipe_id: int = Field(validation_alias=AliasChoices("recipe", "recipe_id"))
    rating: int | None = None
    comment: str = ""
    created_by_id: int = Field(validation_alias=AliasChoices("created_by", "created_by_id"))

    @field_validator("comment", mode="before")
    @classmethod
    def _no_none(cls, value: str | None) -> str:
        """Macht aus dem fehlenden Kommentar einen leeren."""
        return value or ""

    @field_validator("created_by_id", mode="before")
    @classmethod
    def _user_id(cls, value: dict[str, int] | int) -> int:
        """Zieht die ID aus dem eingebetteten Benutzer."""
        return value["id"] if isinstance(value, dict) else value


class Food(BaseModel):
    """Ein Lebensmittel aus `/api/food/`, reduziert auf das, was eine Zuordnung entscheidbar macht.

    Die Kategorie steht in der Antwort verschachtelt und fehlt bei elf Lebensmitteln ganz. Sie
    trennt die Gleichnamigen: `Mozzarella` steht unter Molkereiprodukte, der fettreduzierte unter
    Käse.
    """

    id: int
    name: str
    category: str = Field(default="", validation_alias=AliasPath("supermarket_category", "name"))
