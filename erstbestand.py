"""Einmaliges Schreiben des Ausgangsbestands aus `erstbestand.tsv` nach Tandoor.

Aus der Bonhistorie ist der Bestand nicht zu rechnen: sie kennt jeden Zugang, aber keinen
Abgang. Also einmal alles durchgeben und hier hineinschreiben. Danach ist die Datei erledigt,
Korrekturen gehen in Tandoors Oberfläche.

Kein Befehl der CLI, weil einmal einmal ist. Der Lauf bricht ab, wenn ein Lebensmittel schon
einen Eintrag hat: ein zweiter Lauf würde die Mengen verdoppeln.
"""

import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from tandoor_automation.config import Settings
from tandoor_automation.models import InventoryLocation
from tandoor_automation.shopping import INTERVALS_FILE, confirmed_until, parse_intervals
from tandoor_automation.stock import Addition, describe, payload, twin
from tandoor_automation.tandoor import TandoorClient

STOCK_FILE = Path("erstbestand.tsv")


def parse_stock(text: str) -> list[Addition]:
    """Liest `erstbestand.tsv`.

    Eine leere Menge heißt: das Lebensmittel führt keinen Bestand, die Zeile wird übersprungen.
    Eine 0 dagegen ist eine Aussage, sie steht für geführt und gerade leer.

    Args:
        text: Inhalt der Datei.

    Returns:
        Die aufzunehmenden Bestände in der Reihenfolge der Datei.

    Raises:
        SystemExit: Wenn eine Zeile zu wenige Spalten hat oder die Menge keine Zahl ist.
    """
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("#") or not line.strip():
            continue
        cells = [cell.strip() for cell in line.split("\t")]
        if len(cells) < 6:
            raise SystemExit(f"Zeile {number}: erwartet sind sechs Spalten")
        if not cells[4]:
            continue
        try:
            amount = Decimal(cells[4].replace(",", "."))
        except InvalidOperation:
            raise SystemExit(f"Zeile {number}: {cells[4]!r} ist keine Menge") from None
        found.append(Addition(int(cells[0]), cells[5], cells[3], amount, cells[1]))
    return found


def trusted_until(addition: Addition, intervals: dict[int, int], today: date) -> date:
    """Sagt, bis wann die Aufnahme eines Bestands trägt.

    Die Aufnahme ist eine Bestätigung wie jede andere und trägt deshalb ihr Intervall. Nur die
    leere Ware nicht: sie meldet sich sofort als fällig, sonst stünde sie diese Woche auf keiner
    Einkaufsliste und käme erst nach ihrem Intervall wieder zur Sprache.

    Args:
        addition: Der aufgenommene Bestand.
        intervals: Tage je Lebensmittel, aus `intervalle.tsv`.
        today: Der Tag der Aufnahme.

    Returns:
        Der Tag, ab dem wieder gefragt wird.
    """
    if addition.amount <= 0:
        return today
    return confirmed_until(today, addition.food_id, intervals)


def check(
    additions: list[Addition],
    foods: dict[int, str],
    units: dict[str, int],
    locations: dict[str, InventoryLocation],
) -> None:
    """Prüft, dass jede Zeile geschrieben werden kann, bevor die erste geschrieben wird.

    Args:
        additions: Die aufzunehmenden Bestände.
        foods: Name je Lebensmittel-ID aus Tandoor.
        units: ID je Einheitenname.
        locations: Ort je Name, wie Tandoor ihn kennt.

    Raises:
        SystemExit: Bei unbekannten Lebensmitteln, Einheiten oder Orten.
    """
    problems = [
        f"Lebensmittel {a.food_id} ({a.food_name})" for a in additions if a.food_id not in foods
    ]
    problems += [f'Einheit "{a.unit}"' for a in additions if a.unit not in units]
    problems += [f'Ort "{a.location}"' for a in additions if a.location not in locations]
    for name in sorted(set(problems)):
        print(f"Tandoor kennt {name} nicht")
    if problems:
        raise SystemExit(1)


def run(dry_run: bool) -> None:
    """Schreibt den Ausgangsbestand nach Tandoor.

    Was schon im Bestand steht, bleibt unberührt: ein zweiter Lauf würde die Menge sonst
    verdoppeln. Damit ist der Lauf wiederaufnehmbar, und ein abgerissener Lauf wird einfach
    wiederholt.

    Args:
        dry_run: Nur zeigen, was geschrieben würde.
    """
    additions = parse_stock(STOCK_FILE.read_text(encoding="utf-8"))
    intervals = parse_intervals(INTERVALS_FILE.read_text(encoding="utf-8"))
    today = date.today()
    written = 0
    with TandoorClient(Settings()) as tandoor:
        foods = {food.id: food.name for food in tandoor.foods()}
        units = tandoor.units()
        locations = {place.name: place for place in tandoor.inventory_locations()}
        check(additions, foods, units, locations)
        inventory = tandoor.inventory()
        for addition in additions:
            if twin(addition, inventory, units) is not None:
                print(f"steht schon: {addition.food_name}")
                continue
            expires = trusted_until(addition, intervals, today)
            line = f"{describe(addition)}, bestätigt bis {expires.isoformat()}"
            if dry_run:
                print(f"würde schreiben: {line}")
                continue
            tandoor.create_inventory_entry(
                payload(addition, locations[addition.location], units[addition.unit], expires)
            )
            print(line)
            written += 1
    print(f"{written} von {len(additions)} Zeilen geschrieben")


def main() -> None:
    """Einstiegspunkt."""
    parser = argparse.ArgumentParser(description=f"{STOCK_FILE} einmalig nach Tandoor schreiben")
    parser.add_argument("--dry-run", action="store_true", help="Nur zeigen, was geschrieben würde")
    run(parser.parse_args().dry_run)


if __name__ == "__main__":
    main()
