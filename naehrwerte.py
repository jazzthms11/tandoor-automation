"""Einmaliges Nachtragen von Zucker und Ballaststoffen an Tandoors Lebensmitteln.

Tandoor führt die zwei Werte nicht: seine vier Eigenschaftstypen kommen aus dem Open Data
Projekt, und das kennt nur Kalorien, Fett, Protein und Kohlenhydrate. Die Tagesnotiz führt
dagegen Zucker und Ballaststoffe, also müssen beide hier hinein, bevor SyncHealth die Nährwerte
der geplanten Mahlzeiten lesen kann.

Drei Quellen, in dieser Reihenfolge:

1. FDC für die Lebensmittel mit `fdc_id`. Zucker steht dort unter Nummer 2000, in
   Foundation-Datensätzen aber nur unter 1063, gelesen werden deshalb beide.
2. `naehrwerte.tsv` für die Lebensmittel ohne Nummer.
3. Die eigene Rezeptsumme für die Lebensmittel, die selbst ein Rezept sind. Die muss zuletzt
   kommen, sie rechnet über die Werte der ersten beiden Quellen.

Nicht über Tandoors eigenen Knopf `POST /api/food/<id>/fdc/`: der überschreibt die vier
vorhandenen Werte mit, setzt die Basis hart auf 100 g und kann der Nummer 1063 nicht ausweichen.

Kein Befehl der CLI, weil einmal einmal ist. Wiederholbar ist der Lauf trotzdem: geschrieben
wird je Lebensmittel die vollständige Eigenschaftsliste, ein zweiter Lauf schreibt dasselbe.
"""

import argparse
import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import NamedTuple

import httpx
from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from tandoor_automation.config import Settings
from tandoor_automation.tandoor import TandoorClient

VALUES_FILE = Path("naehrwerte.tsv")
CACHE_FILE = Path("cache/fdc.json")
FDC_FOOD_URL = "https://api.nal.usda.gov/fdc/v1/food/{fdc_id}"
FDC_TIMEOUT_SECONDS = 30
SUGAR = "Zucker"
FIBRE = "Ballaststoffe"
SUGAR_IDS = (2000, 1063)
FIBRE_ID = 1079
NEW_TYPES = (
    {"name": SUGAR, "unit": "g", "fdc_id": SUGAR_IDS[0]},
    {"name": FIBRE, "unit": "g", "fdc_id": FIBRE_ID},
)
CENT = Decimal("0.01")
WEIGHT_UNITS = ("g", "ml")


class FdcSettings(BaseSettings):
    """Liest `FDC_API_KEY` aus der Umgebung oder aus `.env`.

    Getrennt von `Settings`: die CLI läuft ohne diesen Schlüssel, und ein Pflichtfeld dort würde
    jeden Aufruf von `plan` anhalten.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    fdc_api_key: SecretStr


class Values(NamedTuple):
    """Zucker und Ballaststoffe eines Lebensmittels, in Gramm je Basis des Lebensmittels."""

    sugar: Decimal
    fibre: Decimal


def gram(cell: str, number: int) -> Decimal:
    """Liest eine Grammangabe aus einer Zelle.

    Args:
        cell: Inhalt der Zelle.
        number: Zeilennummer, für die Fehlermeldung.

    Returns:
        Der Wert als Dezimalzahl.

    Raises:
        SystemExit: Wenn die Zelle leer ist oder keine Zahl trägt.
    """
    if not cell:
        raise SystemExit(f"Zeile {number}: der Wert fehlt, ohne ihn bleibt jedes Rezept unfertig")
    try:
        return Decimal(cell.replace(",", "."))
    except InvalidOperation:
        raise SystemExit(f"Zeile {number}: {cell!r} ist keine Zahl") from None


def parse_values(text: str) -> dict[int, Values]:
    """Liest `naehrwerte.tsv`.

    Args:
        text: Inhalt der Datei.

    Returns:
        Zucker und Ballaststoffe je Lebensmittel-ID.

    Raises:
        SystemExit: Wenn eine Zeile zu wenige Spalten hat oder ein Wert fehlt.
    """
    found = {}
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("#") or not line.strip():
            continue
        cells = [cell.strip() for cell in line.split("\t")]
        if len(cells) < 6:
            raise SystemExit(f"Zeile {number}: erwartet sind sechs Spalten")
        found[int(cells[0])] = Values(gram(cells[1], number), gram(cells[2], number))
    return found


def ensure_types(tandoor: TandoorClient, dry_run: bool) -> dict[str, dict]:
    """Legt die zwei Eigenschaftstypen an, falls sie fehlen.

    Args:
        tandoor: Die offene Verbindung.
        dry_run: Nur zeigen, was angelegt würde.

    Returns:
        Typ je Name, die vier vorhandenen eingeschlossen.
    """
    types = {entry["name"]: entry for entry in tandoor.property_types()}
    for wanted in NEW_TYPES:
        if wanted["name"] in types:
            continue
        if dry_run:
            print(f"würde Eigenschaftstyp anlegen: {wanted['name']} (FDC {wanted['fdc_id']})")
            types[str(wanted["name"])] = dict(wanted)
            continue
        types[str(wanted["name"])] = tandoor.create_property_type(dict(wanted))
        print(f"Eigenschaftstyp angelegt: {wanted['name']} (FDC {wanted['fdc_id']})")
    return types


def basis_factor(food: dict) -> Decimal | None:
    """Rechnet Werte je 100 g auf die Basis eines Lebensmittels um.

    Millilitern wird die Dichte 1 unterstellt: betroffen sind Kochsahne und Brühen, und ein
    Prozent Abweichung entscheidet hier nichts.

    Args:
        food: Das Lebensmittel, wie Tandoor es ausgibt.

    Returns:
        Der Faktor, oder None wenn die Basis keine Gewichts- oder Volumeneinheit ist.
    """
    unit = (food.get("properties_food_unit") or {}).get("name")
    if unit not in WEIGHT_UNITS:
        return None
    return Decimal(str(food["properties_food_amount"])) / 100


def nutrients(client: httpx.Client, fdc_id: int) -> dict[int, Decimal] | None:
    """Holt die Nährstoffe eines FDC-Datensatzes.

    Der Schlüssel steht im Kopf der Anfrage und nicht in der Adresse: als Parameter stünde er in
    jeder Fehlermeldung und damit in jedem Protokoll.

    Args:
        client: Der HTTP-Client für api.nal.usda.gov, mit dem Schlüssel im Kopf.
        fdc_id: Die Nummer des Datensatzes.

    Returns:
        Menge je 100 g und Nährstoffnummer, oder None wenn FDC die Nummer nicht kennt.

    Raises:
        SystemExit: Wenn das Stundenlimit des Schlüssels erreicht ist.
    """
    response = client.get(FDC_FOOD_URL.format(fdc_id=fdc_id))
    if response.status_code == 429:
        raise SystemExit("FDC nimmt keine Anfragen mehr an, das Limit des Schlüssels ist erreicht")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return {
        entry["nutrient"]["id"]: Decimal(str(entry["amount"]))
        for entry in response.json().get("foodNutrients", [])
        if entry.get("amount") is not None
    }


def cached_nutrients(
    client: httpx.Client, fdc_id: int, cache: dict[str, dict | None]
) -> dict | None:
    """Holt die Nährstoffe einer FDC-Nummer, aus dem Zwischenspeicher wenn sie schon dasteht.

    Der Lauf ist einer je Durchsicht der Datei, und die Werte bei FDC stehen fest. Ohne
    Zwischenspeicher kostete jede Runde 361 Anfragen, und der Schlüssel trägt 1000 je Stunde.

    Args:
        client: Der HTTP-Client für api.nal.usda.gov, mit dem Schlüssel im Kopf.
        fdc_id: Die Nummer des Datensatzes.
        cache: Nährstoffe je Nummer, wird ergänzt.

    Returns:
        Menge je Nährstoffnummer, oder None wenn FDC die Nummer nicht kennt.
    """
    number = str(fdc_id)
    if number not in cache:
        amounts = nutrients(client, fdc_id)
        cache[number] = None if amounts is None else {str(k): str(v) for k, v in amounts.items()}
    stored = cache[number]
    return None if stored is None else {int(k): Decimal(v) for k, v in stored.items()}


def fdc_values(
    client: httpx.Client, foods: list[dict], cache: dict[str, dict | None]
) -> dict[int, Values]:
    """Holt Zucker und Ballaststoffe zu jedem Lebensmittel mit FDC-Nummer.

    Übersprungen wird, wem ein Nährstoff im Datensatz fehlt oder wessen Basis kein Gewicht ist.
    Eine 0 wäre hier eine Aussage, die niemand getroffen hat: FDC führt Zucker in vielen
    Datensätzen gar nicht, und still gebucht stünde der Römersalat ohne seine Ballaststoffe da.
    Solche Lebensmittel gehören in `naehrwerte.tsv`, `check` nennt sie Zeile für Zeile.

    Args:
        client: Der HTTP-Client für api.nal.usda.gov, mit dem Schlüssel im Kopf.
        foods: Alle Lebensmittel aus Tandoor.
        cache: Nährstoffe je FDC-Nummer, wird ergänzt.

    Returns:
        Die Werte je Lebensmittel-ID, in Gramm je Basis.
    """
    found, skipped = {}, 0
    for food in sorted(foods, key=lambda entry: entry["name"]):
        if not food.get("fdc_id"):
            continue
        factor = basis_factor(food)
        amounts = cached_nutrients(client, food["fdc_id"], cache) if factor is not None else {}
        if amounts is None:
            print(f"  FDC kennt die Nummer {food['fdc_id']} nicht ({food['name']})")
            amounts = {}
        sugar = next((amounts[number] for number in SUGAR_IDS if number in amounts), None)
        fibre = amounts.get(FIBRE_ID)
        if factor is None or sugar is None or fibre is None:
            skipped += 1
            continue
        found[food["id"]] = Values(
            (sugar * factor).quantize(CENT, ROUND_HALF_UP),
            (fibre * factor).quantize(CENT, ROUND_HALF_UP),
        )
    print(f"FDC: {len(found)} Lebensmittel gelesen, {skipped} ohne vollständigen Datensatz")
    return found


def recipe_values(tandoor: TandoorClient, foods: list[dict]) -> dict[int, dict[str, Decimal]]:
    """Rechnet die Werte der Lebensmittel, die selbst ein Rezept sind.

    Ihre Basis ist ein Stück und meint das ganze Rezept, belegt am Pizzateig: 1670 kcal am
    Lebensmittel sind genau die Summe seines Rezepts. Geschrieben werden alle Eigenschaften und
    nicht nur die zwei neuen, damit die Summen nicht weiter auseinanderlaufen.

    Args:
        tandoor: Die offene Verbindung.
        foods: Alle Lebensmittel aus Tandoor.

    Returns:
        Menge je Eigenschaftsname und Lebensmittel-ID.

    Raises:
        SystemExit: Wenn ein Rezept selbst noch unvollständig ist.
    """
    found = {}
    for food in sorted(foods, key=lambda entry: entry["name"]):
        if not food.get("recipe"):
            continue
        properties = tandoor.recipe_properties(food["recipe"]["id"])
        unfinished = [entry["name"] for entry in properties.values() if entry["missing_value"]]
        if unfinished:
            raise SystemExit(
                f"{food['name']}: das Rezept {food['recipe']['name']} trägt selbst keine "
                f"{', '.join(unfinished)}"
            )
        found[food["id"]] = {
            entry["name"]: Decimal(str(entry["total_value"])).quantize(CENT, ROUND_HALF_UP)
            for entry in properties.values()
        }
    print(f"Rezept-Lebensmittel: {len(found)} gerechnet")
    return found


def payload(food: dict, amounts: dict[str, Decimal], types: dict[str, dict]) -> list[dict]:
    """Baut die vollständige Eigenschaftsliste eines Lebensmittels.

    Vollständig muss sie sein: was im PATCH fehlt, löscht Tandoor am Lebensmittel, und übrig
    bleibt eine Eigenschaft ohne Lebensmittel, die den Eigenschaftstyp gegen das Löschen sperrt.

    Args:
        food: Das Lebensmittel, wie Tandoor es ausgibt.
        amounts: Die neuen Mengen je Eigenschaftsname.
        types: Eigenschaftstyp je Name.

    Returns:
        Alle Eigenschaften des Lebensmittels, die unveränderten eingeschlossen.
    """
    rows = []
    for prop in food.get("properties") or []:
        name = prop["property_type"]["name"]
        amount = amounts.get(name, prop["property_amount"])
        rows.append(
            {
                "id": prop["id"],
                "property_amount": str(amount),
                "property_type": {"id": prop["property_type"]["id"], "name": name},
            }
        )
    known = {prop["property_type"]["name"] for prop in food.get("properties") or []}
    for name, amount in amounts.items():
        if name not in known:
            rows.append(
                {
                    "property_amount": str(amount),
                    "property_type": {"id": types[name]["id"], "name": name},
                }
            )
    return rows


def basis(food: dict) -> str:
    """Nennt die Menge, auf die sich die Werte eines Lebensmittels beziehen.

    Args:
        food: Das Lebensmittel, wie Tandoor es ausgibt.

    Returns:
        Menge und Einheit, etwa "100 g" oder "1 Stück".
    """
    unit = (food.get("properties_food_unit") or {}).get("name") or "?"
    return f"{food['properties_food_amount']:g} {unit}"


def recipe_foods(tandoor: TandoorClient) -> dict[int, str]:
    """Nennt die Lebensmittel, die in Rezepten vorkommen.

    Nur sie brauchen die zwei Werte: ein Lebensmittel ohne Rezept hält keine Summe auf. Gelesen
    wird das aus `food_values` der Rezepte, dort steht jede Zutat, auch die ohne Menge.

    Args:
        tandoor: Die offene Verbindung.

    Returns:
        Name je Lebensmittel-ID.
    """
    found = {}
    for recipe in tandoor.recipes():
        for entry in tandoor.recipe_properties(recipe.id).values():
            for value in entry["food_values"].values():
                found[value["food"]["id"]] = value["food"]["name"]
    return found


def check(values: dict[int, Values], foods: list[dict], needed: dict[int, str]) -> None:
    """Prüft, dass jedes Lebensmittel eines Rezepts beide Werte bekommt, bevor geschrieben wird.

    Eine Lücke bleibt nicht als 0 stehen, sondern als Zeile für `naehrwerte.tsv`: ausgegeben wird
    sie fertig zum Einfügen, nur die zwei Werte fehlen.

    Args:
        values: Die Werte aus FDC und aus der Datei zusammen.
        foods: Alle Lebensmittel aus Tandoor.
        needed: Name je Lebensmittel-ID, das in einem Rezept vorkommt.

    Raises:
        SystemExit: Bei unbekannten IDs in der Datei oder bei Lücken in Rezept-Lebensmitteln.
    """
    by_id = {food["id"]: food for food in foods}
    unknown = sorted(food_id for food_id in values if food_id not in by_id)
    for food_id in unknown:
        print(f"Lebensmittel {food_id} kennt Tandoor nicht")
    gaps = [
        by_id[food_id]
        for food_id in needed
        if food_id not in values and not by_id[food_id].get("recipe")
    ]
    if gaps:
        print(f"ohne Wert, gehört in {VALUES_FILE}:")
    for food in sorted(gaps, key=lambda entry: entry["name"]):
        kcal = next(
            (
                prop["property_amount"]
                for prop in food.get("properties") or []
                if prop["property_type"]["name"] == "Kalorien"
            ),
            "",
        )
        print(f"{food['id']}\t\t\t{basis(food)}\t{kcal:g}\t{food['name']}")
    if unknown or gaps:
        raise SystemExit(f"{len(unknown) + len(gaps)} Lücken, vor dem Schreiben zu füllen")


def write(
    tandoor: TandoorClient,
    foods: list[dict],
    amounts: dict[int, dict[str, Decimal]],
    types: dict[str, dict],
    dry_run: bool,
) -> int:
    """Schreibt die Werte an die Lebensmittel.

    Args:
        tandoor: Die offene Verbindung.
        foods: Alle Lebensmittel aus Tandoor.
        amounts: Die neuen Mengen je Eigenschaftsname und Lebensmittel-ID.
        types: Eigenschaftstyp je Name.
        dry_run: Nur zeigen, was geschrieben würde.

    Returns:
        Wie viele Lebensmittel geschrieben wurden.
    """
    written = 0
    for food in sorted(foods, key=lambda entry: entry["name"]):
        if food["id"] not in amounts:
            continue
        values = amounts[food["id"]]
        line = f"{food['name']} je {basis(food)}: " + ", ".join(
            f"{name} {value:g}" for name, value in values.items()
        )
        if dry_run:
            print(f"würde schreiben: {line}")
            continue
        tandoor.set_food_properties(food["id"], payload(food, values, types))
        print(line)
        written += 1
    return written


def verify(tandoor: TandoorClient) -> None:
    """Prüft, dass jedes Rezept seine Nährwerte vollständig rechnet.

    Args:
        tandoor: Die offene Verbindung.
    """
    unfinished = {}
    recipes = tandoor.recipes()
    for recipe in recipes:
        gaps = [
            entry["name"]
            for entry in tandoor.recipe_properties(recipe.id).values()
            if entry["missing_value"]
        ]
        if gaps:
            unfinished[recipe.name] = gaps
    for name, gaps in sorted(unfinished.items()):
        print(f"unvollständig: {name} ({', '.join(gaps)})")
    print(f"{len(recipes) - len(unfinished)} von {len(recipes)} Rezepten rechnen vollständig")


def run(dry_run: bool) -> None:
    """Trägt Zucker und Ballaststoffe an allen Lebensmitteln nach.

    Args:
        dry_run: Nur zeigen, was geschrieben würde.
    """
    try:
        key = FdcSettings().fdc_api_key.get_secret_value()
    except ValidationError:
        raise SystemExit(
            "FDC_API_KEY fehlt in .env, ein Schlüssel kommt sofort über "
            "https://fdc.nal.usda.gov/api-key-signup"
        ) from None
    from_file = parse_values(VALUES_FILE.read_text(encoding="utf-8"))
    with TandoorClient(Settings()) as tandoor:
        foods = tandoor.foods_raw()
        needed = recipe_foods(tandoor)
        headers = {"X-Api-Key": key, "Accept": "application/json"}
        cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
        try:
            with httpx.Client(timeout=FDC_TIMEOUT_SECONDS, headers=headers) as client:
                values = fdc_values(client, foods, cache) | from_file
        finally:
            CACHE_FILE.parent.mkdir(exist_ok=True)
            CACHE_FILE.write_text(json.dumps(cache, indent=1))
        check(values, foods, needed)
        types = ensure_types(tandoor, dry_run)
        amounts = {
            food_id: {SUGAR: value.sugar, FIBRE: value.fibre} for food_id, value in values.items()
        }
        written = write(tandoor, foods, amounts, types, dry_run)
        written += write(tandoor, foods, recipe_values(tandoor, foods), types, dry_run)
        if dry_run:
            return
        print(f"{written} Lebensmittel geschrieben")
        verify(tandoor)


def main() -> None:
    """Einstiegspunkt."""
    parser = argparse.ArgumentParser(description="Zucker und Ballaststoffe nach Tandoor schreiben")
    parser.add_argument("--dry-run", action="store_true", help="Nur zeigen, was geschrieben würde")
    run(parser.parse_args().dry_run)


if __name__ == "__main__":
    main()
