"""Zugriff auf die Tandoor-API: Rezepte, Lebensmittel, Plan und Bestand."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from types import TracebackType

import httpx

from tandoor_automation.config import Settings
from tandoor_automation.models import (
    CookLog,
    Food,
    Ingredient,
    InventoryEntry,
    InventoryLocation,
    MealType,
    PlannedMeal,
    Recipe,
    RecipeDetail,
)

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

    def recipe_names(self) -> dict[int, str]:
        """Holt nur Namen je Rezept-ID, ohne die Bewertung nachzuholen.

        Returns:
            Name je Rezept-ID.
        """
        return {item["id"]: item["name"] for item in self._pages("/api/recipe/", {})}

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

    def cook_logs(self, recipe_id: int | None = None) -> list[CookLog]:
        """Holt das Kochprotokoll.

        Args:
            recipe_id: Nur die Einträge dieses Rezepts. Ohne Angabe alle.

        Returns:
            Die Einträge, auch die der Mitesser.
        """
        params = {} if recipe_id is None else {"recipe": str(recipe_id)}
        return [CookLog.model_validate(item) for item in self._pages("/api/cook-log/", params)]

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

    def delete_meal(self, meal_id: int) -> None:
        """Löscht einen Planeintrag.

        Args:
            meal_id: ID des Eintrags.
        """
        response = self._client.delete(f"/api/meal-plan/{meal_id}/")
        response.raise_for_status()

    def foods(self) -> list[Food]:
        """Holt alle Lebensmittel der Instanz.

        Returns:
            Alle Lebensmittel, nach Namen sortiert.
        """
        return [Food.model_validate(item) for item in self._pages("/api/food/", {})]

    def units(self) -> dict[str, int]:
        """Holt die Einheiten der Instanz.

        Returns:
            ID je Name der Einheit.
        """
        return {item["name"]: item["id"] for item in self._pages("/api/unit/", {})}

    def inventory_locations(self) -> list[InventoryLocation]:
        """Holt die Orte, an denen Bestand liegen kann.

        Returns:
            Alle Orte der Instanz.
        """
        return [
            InventoryLocation.model_validate(item)
            for item in self._pages("/api/inventory-location/", {})
        ]

    def inventory(self) -> list[InventoryEntry]:
        """Holt den gesamten Bestand, die leeren Einträge eingeschlossen.

        Geholt wird immer alles: `/api/inventory-entry/` nimmt zwar einen Filter `food` an,
        wertet ihn aber nicht aus und gibt darauf die ganze Liste zurück.

        Ohne `empty` lässt Tandoor jeden Eintrag mit Menge 0 weg. Genau die werden gebraucht:
        ein leeres Lebensmittel ist der Kaufgrund, und ein unsichtbarer Eintrag hieße außerdem,
        dass der nächste Zugang einen zweiten daneben anlegt statt auf ihn zu buchen. Der Wert
        des Parameters ist gleichgültig, Tandoor schaut nur, ob er dasteht.

        Returns:
            Alle Bestandseinträge.
        """
        return [
            InventoryEntry.model_validate(item)
            for item in self._pages("/api/inventory-entry/", {"empty": "1"})
        ]

    def create_inventory_entry(self, body: dict[str, object]) -> InventoryEntry:
        """Legt einen Bestandseintrag an.

        Args:
            body: Der Körper der Anfrage, gebaut von `stock.payload`.

        Returns:
            Der Eintrag, wie Tandoor ihn angelegt hat.
        """
        response = self._client.post("/api/inventory-entry/", json=body)
        response.raise_for_status()
        return InventoryEntry.model_validate(response.json())

    def update_inventory_entry(
        self, entry_id: int, amount: Decimal, expires: date
    ) -> InventoryEntry:
        """Schreibt Menge und Vertrauensdauer eines Bestandseintrags fort.

        Beides gehört zusammen: eine neue Menge ist immer auch eine frische Bestätigung, ob sie
        nun aus dem Bon kommt oder aus der Rückfrage.

        Args:
            entry_id: Der Eintrag.
            amount: Die neue Menge.
            expires: Bis wann der Eintrag ohne neue Bestätigung als real gilt.

        Returns:
            Der Eintrag, wie Tandoor ihn danach führt.
        """
        response = self._client.patch(
            f"/api/inventory-entry/{entry_id}/",
            json={"amount": str(amount), "expires": expires.isoformat()},
        )
        response.raise_for_status()
        return InventoryEntry.model_validate(response.json())

    def recipe_detail(self, recipe_id: int) -> RecipeDetail:
        """Holt ein Rezept samt Zutaten.

        Die Zutaten stehen nur im Detailabruf, die Rezeptliste trägt sie nicht. Zutaten ohne
        Lebensmittel bleiben draußen: das sind Zwischenüberschriften und Anmerkungen.

        Args:
            recipe_id: Das Rezept.

        Returns:
            Name, Grundportionen und Zutaten.
        """
        response = self._client.get(f"/api/recipe/{recipe_id}/")
        response.raise_for_status()
        raw = response.json()
        return RecipeDetail(
            id=raw["id"],
            name=raw["name"],
            servings=raw["servings"],
            ingredients=[
                Ingredient.model_validate(ingredient)
                for step in raw["steps"]
                for ingredient in step["ingredients"]
                if ingredient.get("food")
            ],
        )

    def shopping_list(self) -> set[int]:
        """Holt die Lebensmittel, die offen auf der Einkaufsliste stehen.

        Abgehaktes gibt die Liste mit zurück und zählt hier nicht: es ist gekauft und soll
        beim nächsten Lauf wieder daraufkönnen.

        Returns:
            Die IDs der Lebensmittel mit offenem Eintrag.
        """
        return {
            item["food"]["id"]
            for item in self._pages("/api/shopping-list-entry/", {})
            if not item.get("checked") and item.get("food")
        }

    def shopping_recipes(self) -> dict[int, int]:
        """Holt die Rezeptblöcke der Einkaufsliste, die an einem Planeintrag hängen.

        Returns:
            Die ID des Blocks je Planeintrag.
        """
        return {
            block["mealplan"]: block["id"]
            for block in self._pages("/api/shopping-list-recipe/", {})
            if block.get("mealplan")
        }

    def create_shopping_recipe(self, meal: PlannedMeal) -> int:
        """Legt den Rezeptblock an, unter dem Tandoor den Namen des Gerichts zeigt.

        Args:
            meal: Der Planeintrag, aus dem gekauft wird.

        Returns:
            Die ID des Blocks.
        """
        response = self._client.post(
            "/api/shopping-list-recipe/",
            json={"recipe": meal.recipe_id, "mealplan": meal.id, "servings": meal.servings},
        )
        response.raise_for_status()
        return response.json()["id"]

    def create_shopping_entry(self, food_id: int, block_id: int | None = None) -> None:
        """Setzt ein Lebensmittel auf die Einkaufsliste.

        Die Liste sagt "kaufen" und führt keine Menge: `amount` genügt, `unit` darf fehlen.
        Tandoor zählt die Einträge eines Lebensmittels zusammen, eine 2 heißt also zwei Gerichte.

        Das Lebensmittel geht als ID hinaus und nie als Objekt: ein mitgeschickter Name benennt
        es in Tandoor um.

        Args:
            food_id: Das Lebensmittel.
            block_id: Der Rezeptblock, aus dem es gebraucht wird. Leer bei Vorratsware.
        """
        response = self._client.post(
            "/api/shopping-list-entry/",
            json={"food": food_id, "amount": 1, "list_recipe": block_id},
        )
        response.raise_for_status()

    def foods_raw(self) -> list[dict]:
        """Holt die Lebensmittel unbeschnitten.

        `Food` greift nur Name und Kategorie heraus. Eigenschaften, ihre Basis, die FDC-Nummer
        und die Verknüpfung zu einem Rezept stehen deshalb nur hier.

        Returns:
            Alle Lebensmittel, wie Tandoor sie ausgibt.
        """
        return list(self._pages("/api/food/", {}))

    def property_types(self) -> list[dict]:
        """Holt die Eigenschaftstypen der Instanz.

        Returns:
            Alle Typen mit Name, Einheit und FDC-Nummer.
        """
        return list(self._pages("/api/property-type/", {}))

    def create_property_type(self, body: dict[str, object]) -> dict:
        """Legt einen Eigenschaftstyp an.

        Args:
            body: Name, Einheit und FDC-Nummer.

        Returns:
            Der angelegte Typ, wie Tandoor ihn führt.
        """
        response = self._client.post("/api/property-type/", json=body)
        response.raise_for_status()
        return response.json()

    def set_food_properties(self, food_id: int, properties: list[dict[str, object]]) -> None:
        """Schreibt die Eigenschaften eines Lebensmittels.

        Die Liste muss vollständig sein: was darin fehlt, löscht Tandoor am Lebensmittel. Ein
        Eintrag mit `id` wird fortgeschrieben, einer ohne neu angelegt.

        Args:
            food_id: Das Lebensmittel.
            properties: Alle Eigenschaften des Lebensmittels.
        """
        response = self._client.patch(f"/api/food/{food_id}/", json={"properties": properties})
        response.raise_for_status()

    def recipe_properties(self, recipe_id: int) -> dict:
        """Holt die gerechneten Nährwerte eines Rezepts.

        Gerechnet wird in Tandoor: `food_properties` summiert die Zutaten je Eigenschaftstyp und
        meldet über `missing_value`, wenn eine Zutat aus der Summe gefallen ist.

        Args:
            recipe_id: Das Rezept.

        Returns:
            Ein Eintrag je Eigenschaftstyp, mit Summe, Einzelwerten und Fehlermeldung.
        """
        response = self._client.get(f"/api/recipe/{recipe_id}/")
        response.raise_for_status()
        return response.json().get("food_properties", {})

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
