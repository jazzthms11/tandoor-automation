"""Die Grundbewertung der Rezepte, gepflegt in `bewertung.tsv`.

Die Skala misst nicht Geschmack, sondern wie oft ein Gericht darf: 5 geht quasi immer, 3 nur
wenn es lange her ist, 1 nie. Damit lässt sie sich gegen die Planhistorie rechnen.

Tandoor hat dafür kein eigenes Feld. Es mittelt die Noten aller Einträge im Kochprotokoll eines
Rezepts, und zwar nur die des anfragenden Nutzers. Die Grundbewertung ist deshalb genau ein
Eintrag je Rezept, am `comment` erkennbar und weit zurückdatiert, damit sie nicht als heute
gekocht gilt. Ändert sich eine Note, wird dieser eine Eintrag geändert; ein zweiter würde sich mit
dem ersten vermischen.
"""

from datetime import datetime

from pydantic import BaseModel

from tandoor_automation.models import CookLog

MARKER = "Grundbewertung"
BACKDATED = datetime(2020, 1, 1, 12, 0).astimezone()
MAX_STARS = 5
COLUMNS = 2


class RatingChange(BaseModel):
    """Was an einem Rezept zu tun ist, damit Tandoor die Note aus der Datei trägt."""

    recipe_id: int
    stars: int
    log_id: int | None = None


def parse_ratings(text: str) -> dict[int, int]:
    """Liest `bewertung.tsv`.

    Die Datei wird von Hand gepflegt, und ob zwischen zwei Spalten ein Tab oder ein Leerzeichen
    steht, sieht man ihr nicht an. Getrennt wird deshalb an beidem. Gelesen werden nur die ersten
    beiden Spalten, der Rest der Zeile ist Gedächtnisstütze.

    Args:
        text: Inhalt der Datei.

    Returns:
        Note je Rezept-ID, unbewertete (0) eingeschlossen.

    Raises:
        ValueError: Bei einer unlesbaren Zeile, einer Note außerhalb von 0 bis 5 oder einem
            Rezept, das zweimal vorkommt.
    """
    ratings: dict[int, int] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        if len(fields) < COLUMNS:
            raise ValueError(f"Zeile {number}: erwartet werden Sterne und Rezept-ID")
        try:
            stars, recipe_id = int(fields[0]), int(fields[1])
        except ValueError as error:
            raise ValueError(f"Zeile {number}: Sterne und ID müssen Zahlen sein") from error
        if not 0 <= stars <= MAX_STARS:
            raise ValueError(f"Zeile {number}: {stars} Sterne, erlaubt sind 0 bis {MAX_STARS}")
        if recipe_id in ratings:
            raise ValueError(f"Zeile {number}: Rezept {recipe_id} steht schon weiter oben")
        ratings[recipe_id] = stars
    return ratings


def own_base_ratings(logs: list[CookLog], user_id: int) -> dict[int, CookLog]:
    """Sucht unter allen Protokolleinträgen die eigenen Grundbewertungen.

    Args:
        logs: Alle Einträge aus `/api/cook-log/`, auch die der Mitesser.
        user_id: Die eigene Benutzer-ID.

    Returns:
        Die Grundbewertung je Rezept-ID.
    """
    return {
        log.recipe_id: log for log in logs if log.created_by_id == user_id and log.comment == MARKER
    }


def changes(ratings: dict[int, int], existing: dict[int, CookLog]) -> list[RatingChange]:
    """Stellt fest, was sich zwischen Datei und Tandoor unterscheidet.

    Die Datei ist die Quelle: eine Note, die dort auf 0 zurückgesetzt wurde, wird in Tandoor
    gelöscht und nicht stehen gelassen.

    Args:
        ratings: Note je Rezept-ID aus der Datei.
        existing: Die eigenen Grundbewertungen, je Rezept-ID.

    Returns:
        Je Rezept ein Vorhaben. `stars` 0 heißt löschen, `log_id` gesetzt heißt ändern, beides
        offen heißt anlegen. Rezepte, deren Note schon stimmt, fehlen.
    """
    todo = []
    for recipe_id, stars in ratings.items():
        log = existing.get(recipe_id)
        if log is None:
            if stars:
                todo.append(RatingChange(recipe_id=recipe_id, stars=stars))
        elif log.rating != stars:
            todo.append(RatingChange(recipe_id=recipe_id, stars=stars, log_id=log.id))
    return todo


def payload(change: RatingChange) -> dict[str, object]:
    """Baut den Körper für einen Eintrag im Kochprotokoll.

    Args:
        change: Das Vorhaben an einem Rezept.

    Returns:
        Der Körper der Anfrage.
    """
    return {
        "recipe": change.recipe_id,
        "rating": change.stars,
        "comment": MARKER,
        "created_at": BACKDATED.isoformat(),
    }
