"""Lesender Zugriff auf die Tandoor-API."""

from collections.abc import Iterator
from datetime import date
from types import TracebackType

import httpx

from kueche.config import Settings
from kueche.models import PlannedMeal, Recipe

PAGE_SIZE = 100
TIMEOUT_SECONDS = 30


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
        """Holt das gesamte Kochbuch.

        Returns:
            Alle Rezepte, nach Namen sortiert.
        """
        return [Recipe.model_validate(item) for item in self._pages("/api/recipe/", {})]

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
