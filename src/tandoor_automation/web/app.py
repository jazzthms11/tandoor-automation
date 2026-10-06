"""Der Webdienst: Layout, Navigation und die Seite Bewertung.

Gestartet wird er mit `uvicorn tandoor_automation.web.app:app`, im Container über die
Compose-Datei. Jede Anfrage, die Tandoor braucht, öffnet einen eigenen Client. Das kostet keine
Verbindung, solange nichts abgerufen wird.
"""

import time
from collections import Counter
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib.resources import files
from threading import Lock
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import col, select

from tandoor_automation import store
from tandoor_automation.config import Settings
from tandoor_automation.rating import MAX_STARS
from tandoor_automation.tandoor import TandoorClient
from tandoor_automation.workflow import rate_recipe, sync_ratings

HERE = files("tandoor_automation") / "web"
PAGES = [("Bewertung", "/bewertung")]
"""Die Navigation, eine Seite je Eintrag. Weitere kommen mit den nächsten Meilensteinen."""
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


def _everywhere(_: Request) -> dict[str, object]:
    """Was jede Vorlage kennt, ohne dass jede Seite es einzeln übergibt."""
    return {"pages": PAGES, "meaning": MEANING, "max_stars": MAX_STARS}


templates = Jinja2Templates(directory=str(HERE / "templates"), context_processors=[_everywhere])


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Zieht das Schema der Datenbank beim Start nach, damit ein Fehler dort sofort auffällt."""
    store.engine()
    yield


app = FastAPI(title="tandoor-automation", lifespan=_lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")


def _tandoor() -> Iterator[TandoorClient]:
    with TandoorClient(Settings()) as client:
        yield client


Tandoor = Annotated[TandoorClient, Depends(_tandoor)]


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


def _partial(request: Request) -> bool:
    """Ob htmx nur einen Teil der Seite will. Beim Zurückblättern will es die ganze."""
    return "HX-Request" in request.headers and "HX-History-Restore-Request" not in request.headers


@app.exception_handler(httpx.HTTPError)
def _tandoor_down(request: Request, error: httpx.HTTPError) -> Response:
    """Zeigt einen Fehler von Tandoor als Meldung statt als Absturz."""
    message = f"Tandoor antwortet nicht wie erwartet: {error}"
    if "HX-Request" in request.headers:
        return PlainTextResponse(message, status_code=502)
    return templates.TemplateResponse(request, "fehler.html", {"message": message}, status_code=502)


@app.get("/")
def home() -> RedirectResponse:
    """Die Startseite ist vorerst die einzige Seite."""
    return RedirectResponse(PAGES[0][1])


@app.get("/health")
def health() -> dict[str, bool]:
    """Für den Healthcheck des Containers: der Dienst antwortet und die Datenbank öffnet."""
    store.engine()
    return {"ok": True}


@app.get("/bewertung", response_class=HTMLResponse)
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
    if _partial(request):
        return templates.TemplateResponse(request, "bewertung_liste.html", context)
    return templates.TemplateResponse(
        request, "bewertung.html", context | {"gone": _gone(set(names))}
    )


def _gone(known: set[int]) -> list[store.Rating]:
    """Bewertungen zu Rezepten, die es in Tandoor nicht mehr gibt."""
    with store.session() as db:
        rows = db.exec(select(store.Rating).where(col(store.Rating.recipe_id).not_in(known)))
        return list(rows)


@app.post("/bewertung/abgleich", response_class=HTMLResponse)
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
    return templates.TemplateResponse(
        request, "bewertung_abgleich.html", {"unknown": synced.unknown, "lines": lines}
    )


@app.post("/bewertung/{recipe_id:int}", response_class=HTMLResponse)
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
    return templates.TemplateResponse(
        request,
        "bewertung_zeile.html",
        {"row": Row(recipe_id, name, stars), "status": status, "warning": warning},
    )


@app.post("/bewertung/{recipe_id:int}/entfernen", response_class=HTMLResponse)
def remove(recipe_id: int) -> str:
    """Nimmt die Bewertung eines Rezepts heraus, das es in Tandoor nicht mehr gibt."""
    store.drop_rating(recipe_id)
    return ""
