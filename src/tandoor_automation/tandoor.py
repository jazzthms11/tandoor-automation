"""Zugriff auf die Tandoor-API: Rezepte, Lebensmittel und Plan lesen, Planeinträge anlegen."""

from collections.abc import Iterator
from datetime import date
from types import TracebackType

import httpx

from tandoor_automation.config import Settings
from tandoor_automation.models import CookLog, Food, MealType, PlannedMeal, Recipe

PAGE_SIZE = 100
TIMEOUT_SECONDS = 30
STARS = range(1, 6)


class TandoorClient:
    """Holt Rezepte und Planhistorie und gibt sie eingedampft zurück.

    Als Kontextmanager benutzen, damit die HTTP-Verbindung wieder geschlossen wird:

    ```python
    with TandoorClient(Settings()) as tandoor:
        recipes = tandoor.recipes()
    ```
    """

    def __init__(self, settings: Settings) -> None:
        """Baut den HTTP-Client aus Adresse und Token.

        Args:
            settings: Adresse der Tandoor-Instanz und API-Token.
        """
        self._client = httpx.Client(
            base_url=str(settings.tandoor_url).rstrip("/"),
            headers={
                "Authorization": f"Bearer {settings.tandoor_token.get_secret_value()}",
                "Accept": "application/json",
            },
            timeout=TIMEOUT_SECONDS,
        )

    def __enter__(self) -> "TandoorClient":
        """Gibt den Client selbst zurück."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Schließt die HTTP-Verbindung."""
        self._client.close()

    def recipes(self) -> list[Recipe]:
        """Holt das gesamte Kochbuch samt Grundbewertung.

        Returns:
            Alle Rezepte, nach Namen sortiert.
        """
        stars = self.ratings()
        recipes = [Recipe.model_validate(item) for item in self._pages("/api/recipe/", {})]
        for recipe in recipes:
            recipe.rating = stars.get(recipe.id, 0)
        return recipes

    def ratings(self) -> dict[int, int]:
        """Holt die eigene Bewertung je Rezept.

        Das Feld `rating` an `/api/recipe/` ist immer leer: Tandoor annotiert es nur, wenn danach
        gefiltert wird. Abgefragt wird deshalb Stufe für Stufe, und die Antwort ist schon auf den
        Nutzer hinter dem Token gefiltert.

        Returns:
            Note je Rezept-ID. Unbewertete Rezepte fehlen.
        """
        return {
            item["id"]: star
            for star in STARS
            for item in self._pages("/api/recipe/", {"rating": str(star)})
        }

    def current_user_id(self) -> int:
        """Gibt die Benutzer-ID hinter dem Token.

        Returns:
            Die eigene ID. Sie zählt, weil die Instanz geteilt ist und Bewertungen je Nutzer
            gelten.
        """
        response = self._client.get("/api/user-preference/")
        response.raise_for_status()
        return int(response.json()[0]["user"]["id"])

    def cook_logs(self) -> list[CookLog]:
        """Holt das Kochprotokoll.

        Returns:
            Alle Einträge, auch die der Mitesser.
        """
        return [CookLog.model_validate(item) for item in self._pages("/api/cook-log/", {})]

    def create_cook_log(self, body: dict[str, object]) -> CookLog:
        """Legt einen Eintrag im Kochprotokoll an.

        Args:
            body: Der Körper der Anfrage, gebaut von `rating.payload`.

        Returns:
            Der angelegte Eintrag.
        """
        response = self._client.post("/api/cook-log/", json=body)
        response.raise_for_status()
        return CookLog.model_validate(response.json())

    def update_cook_log(self, log_id: int, body: dict[str, object]) -> CookLog:
        """Ändert einen Eintrag im Kochprotokoll.

        Args:
            log_id: ID des Eintrags.
            body: Der Körper der Anfrage.

        Returns:
            Der geänderte Eintrag.
        """
        response = self._client.patch(f"/api/cook-log/{log_id}/", json=body)
        response.raise_for_status()
        return CookLog.model_validate(response.json())

    def delete_cook_log(self, log_id: int) -> None:
        """Löscht einen Eintrag im Kochprotokoll.

        Args:
            log_id: ID des Eintrags.
        """
        response = self._client.delete(f"/api/cook-log/{log_id}/")
        response.raise_for_status()

    def meal_types(self) -> list[MealType]:
        """Holt die Mahlzeiten des Tages, nach Uhrzeit sortiert.

        Returns:
            Alle in Tandoor angelegten Mahlzeitentypen.
        """
        types = [MealType.model_validate(item) for item in self._pages("/api/meal-type/", {})]
        return sorted(
            types, key=lambda meal_type: (meal_type.served_at is None, meal_type.served_at)
        )

    def meal_plan(self, start: date, end: date) -> list[PlannedMeal]:
        """Holt die Planeinträge eines Zeitraums.

        Args:
            start: Erster Tag, einschließlich.
            end: Letzter Tag, einschließlich.

        Returns:
            Alle Einträge des Zeitraums, auch die ohne Rezept.
        """
        params = {"from_date": start.isoformat(), "to_date": end.isoformat()}
        return [PlannedMeal.model_validate(item) for item in self._pages("/api/meal-plan/", params)]

    def create_meal(self, body: dict[str, object]) -> PlannedMeal:
        """Legt einen Planeintrag an.

        Args:
            body: Der Körper der Anfrage, gebaut von `apply.payload`.

        Returns:
            Der Eintrag, wie Tandoor ihn angelegt hat.
        """
        response = self._client.post("/api/meal-plan/", json=body)
        response.raise_for_status()
        return PlannedMeal.model_validate(response.json())

    def foods(self) -> list[Food]:
        """Holt alle Lebensmittel der Instanz.

        Returns:
            Alle Lebensmittel, nach Namen sortiert.
        """
        return [Food.model_validate(item) for item in self._pages("/api/food/", {})]

    def _pages(self, path: str, params: dict[str, str]) -> Iterator[dict]:
        """Läuft eine paginierte Liste durch und gibt die Einträge einzeln aus.

        Seitenzahlen werden selbst hochgezählt statt der `next`-URL zu folgen, weil Tandoor hinter
        einem Tunnel läuft und dort absolute URLs mit falschem Schema zurückgeben kann.
        """
        page = 1
        while True:
            response = self._client.get(
                path, params={**params, "page": page, "page_size": PAGE_SIZE}
            )
            response.raise_for_status()
            payload = response.json()
            yield from payload["results"]
            if not payload.get("next"):
                return
            page += 1
