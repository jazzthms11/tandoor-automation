"""Die Seite Bewertung: alle Rezepte mit Sternen, ein Klick schreibt sofort nach Tandoor."""

import time
from collections import Counter
from dataclasses import dataclass
from threading import Lock
from typing import Annotated

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from sqlmodel import col, select

from tandoor_automation import store
from tandoor_automation.rating import MAX_STARS
from tandoor_automation.tandoor import TandoorClient
from tandoor_automation.web.common import Tandoor, partial, templates
from tandoor_automation.workflow import rate_recipe, sync_ratings

NAMES_SECONDS = 600
"""So lange gilt die Liste der Rezeptnamen, bevor sie neu aus Tandoor geholt wird."""
MEANING = {
    5: "geht quasi immer",
    4: "sehr gut, aber nicht jede Woche",
    3: "kann man mal essen, nur wenn es lange her ist",
    2: "eigentlich nicht gut",
    1: "nie",
    0: "nicht bewertet",
}

router = APIRouter()


class _Names:
    """Die Rezeptnamen aus Tandoor, einige Minuten zwischengespeichert.

    Die Rezeptliste kommt in Seiten zu hundert und trägt an jedem Rezept mehr, als hier gebraucht
    wird. Sie bei jedem Tippen ins Suchfeld neu zu holen, machte die Seite zäh, und neue Rezepte
    entstehen selten. Wer eins gerade angelegt hat, lädt die Liste über den Link neu.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._at: float | None = None
        self._names: dict[int, str] = {}

    def get(self, tandoor: TandoorClient, fresh: bool = False) -> dict[int, str]:
        with self._lock:
            if fresh or self._at is None or time.monotonic() - self._at > NAMES_SECONDS:
                self._names = tandoor.recipe_names()
                self._at = time.monotonic()
            return self._names


_names = _Names()


@dataclass(frozen=True)
class Row:
    """Ein Rezept auf der Seite Bewertung."""

    id: int
    name: str
    stars: int


def _render(request: Request, name: str, context: dict[str, object]) -> Response:
    return templates.TemplateResponse(
        request, name, context | {"meaning": MEANING, "max_stars": MAX_STARS}
    )


@router.get("/bewertung", response_class=HTMLResponse)
def rating_page(
    request: Request, tandoor: Tandoor, q: str = "", sterne: str = "", neu: bool = False
) -> Response:
    """Alle Rezepte mit ihrer Note, durchsuchbar und nach Sternen gefiltert.

    Args:
        request: Die Anfrage.
        tandoor: Der Zugang zu Tandoor, für die Namen.
        q: Suchtext, ein Teil des Namens.
        sterne: Nur Rezepte mit dieser Note. Leer heißt alle.
        neu: Die Rezeptnamen jetzt neu aus Tandoor holen.
    """
    names = _names.get(tandoor, fresh=neu)
    stored = store.ratings()
    rows = sorted(
        (Row(recipe_id, name, stored.get(recipe_id, 0)) for recipe_id, name in names.items()),
        key=lambda row: row.name.casefold(),
    )
    needle = q.strip().casefold()
    shown = [
        row
        for row in rows
        if needle in row.name.casefold() and (not sterne or str(row.stars) == sterne)
    ]
    context = {
        "rows": shown,
        "total": len(rows),
        "counts": Counter(row.stars for row in rows),
        "q": q,
        "sterne": sterne,
    }
    if partial(request):
        return _render(request, "bewertung_liste.html", context)
    return _render(request, "bewertung.html", context | {"gone": _gone(set(names))})


def _gone(known: set[int]) -> list[store.Rating]:
    """Bewertungen zu Rezepten, die es in Tandoor nicht mehr gibt."""
    with store.session() as db:
        rows = db.exec(select(store.Rating).where(col(store.Rating.recipe_id).not_in(known)))
        return list(rows)


@router.post("/bewertung/abgleich", response_class=HTMLResponse)
def sync(request: Request, tandoor: Tandoor) -> Response:
    """Gleicht alle Noten mit Tandoor ab, wie `plan rate`."""
    synced = sync_ratings(tandoor, store.ratings(), dry_run=False)
    lines = [
        (
            "gelöscht" if not change.stars else ("geändert" if change.log_id else "angelegt"),
            change.stars,
            synced.names[change.recipe_id],
        )
        for change in synced.todo
    ]
    return _render(request, "bewertung_abgleich.html", {"unknown": synced.unknown, "lines": lines})


@router.post("/bewertung/{recipe_id:int}", response_class=HTMLResponse)
def rate(
    request: Request,
    tandoor: Tandoor,
    recipe_id: int,
    stars: Annotated[int, Form(ge=0, le=MAX_STARS)],
) -> Response:
    """Speichert eine Note und trägt sie sofort nach Tandoor.

    Erst die Datenbank, dann Tandoor: ist Tandoor gerade nicht erreichbar, geht die Note nicht
    verloren, und der Abgleich holt sie später nach.
    """
    name = _names.get(tandoor).get(recipe_id)
    if name is None:
        return PlainTextResponse(f"Rezept {recipe_id} gibt es in Tandoor nicht", status_code=404)
    store.set_rating(recipe_id, stars, name)
    try:
        written = rate_recipe(tandoor, recipe_id, stars)
    except httpx.HTTPError:
        status, warning = "gespeichert, Tandoor nicht erreicht, später abgleichen", True
    else:
        status, warning = ("in Tandoor" if written else "stand schon so in Tandoor"), False
    return _render(
        request,
        "bewertung_zeile.html",
        {"row": Row(recipe_id, name, stars), "status": status, "warning": warning},
    )


@router.post("/bewertung/{recipe_id:int}/entfernen", response_class=HTMLResponse)
def remove(recipe_id: int) -> str:
    """Nimmt die Bewertung eines Rezepts heraus, das es in Tandoor nicht mehr gibt."""
    store.drop_rating(recipe_id)
    return ""
