"""Der Webdienst: setzt die Seiten zusammen und fängt Fehler von Tandoor ab.

Gestartet wird er mit `uvicorn tandoor_automation.web.app:app`, im Container über die
Compose-Datei. Jede Seite hat ihr eigenes Modul mit einem Router, gemeinsam genutztes steht in
`common`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from tandoor_automation import store
from tandoor_automation.chooser import ChooserError
from tandoor_automation.web import bewertung, bons, einkauf, plan
from tandoor_automation.web.common import HERE, PAGES, templates


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Zieht das Schema der Datenbank beim Start nach, damit ein Fehler dort sofort auffällt."""
    store.engine()
    yield


app = FastAPI(title="tandoor-automation", lifespan=_lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
for module in (plan, einkauf, bons, bewertung):
    app.include_router(module.router)


def _problem(request: Request, message: str, status: int) -> Response:
    """Eine Meldung als Text für htmx, das sie oben einblendet, sonst als ganze Seite."""
    if "HX-Request" in request.headers:
        return PlainTextResponse(message, status_code=status)
    return templates.TemplateResponse(
        request, "fehler.html", {"message": message}, status_code=status
    )


@app.exception_handler(httpx.HTTPError)
def _tandoor_down(request: Request, error: httpx.HTTPError) -> Response:
    """Zeigt einen Fehler von Tandoor als Meldung statt als Absturz."""
    return _problem(request, f"Tandoor antwortet nicht wie erwartet: {error}", 502)


@app.exception_handler(store.StaleDraftError)
def _stale(request: Request, _: store.StaleDraftError) -> Response:
    """Jemand anderes hat den Entwurf inzwischen geändert, die Seite zeigt einen alten Stand."""
    return _problem(request, "Der Entwurf wurde inzwischen geändert. Seite neu laden.", 409)


@app.exception_handler(ChooserError)
def _chooser(request: Request, error: ChooserError) -> Response:
    """Das Modell ist nicht erreichbar oder nicht eingerichtet."""
    return _problem(request, str(error), 502)


@app.exception_handler(ValueError)
def _bad_input(request: Request, error: ValueError) -> Response:
    """Eine Angabe in der Adresse, die nicht passt, etwa eine Woche, die es nicht gibt."""
    return _problem(request, str(error), 400)


@app.get("/")
def home() -> RedirectResponse:
    """Die Startseite ist die erste Seite der Navigation."""
    return RedirectResponse(PAGES[0][1])


@app.get("/health")
def health() -> dict[str, bool]:
    """Für den Healthcheck des Containers: der Dienst antwortet und die Datenbank öffnet."""
    store.engine()
    return {"ok": True}
