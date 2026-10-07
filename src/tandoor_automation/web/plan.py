"""Die Seite Wochenplan: der Entwurf der Woche, seine Freigabe, und was schon in Tandoor steht.

Oben steht der Entwurf. Er entsteht über das Modell, donnerstags von selbst über `plan draft` oder
hier über einen Knopf, und wird danach angepasst: in Worten über das Modell, oder von Hand über
Tausch, Termin, Portionen und Notiz. Jede Änderung zeigt die Mängel sofort am Platz. Die Freigabe
fragt nach der Aufteilung der Mittagessen und schreibt dann wie `plan apply`.

Unten steht, was in Tandoor eingetragen ist, mit Auswahl zum Zurücknehmen wie `plan clear`.

Jede Aktion am Entwurf antwortet mit dem ganzen Abschnitt neu gerendert. Das ist einfacher als
einzelne Plätze zu tauschen, und die Mängel hängen ohnehin an der ganzen Woche.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response
from starlette.concurrency import run_in_threadpool

from tandoor_automation import drafts
from tandoor_automation.chooser import Gemini, Model
from tandoor_automation.web import common, jobs
from tandoor_automation.web.common import Tandoor, templates, week_context, week_or_next
from tandoor_automation.workflow import Applied, clear_week

router = APIRouter()
model_factory: type[Model] | None = None
"""Für den Probelauf ohne Schlüssel austauschbar, sonst Gemini."""

Week = Annotated[str, Form(alias="woche")]
Version = Annotated[int, Form(alias="version")]
Index = Annotated[int, Form(alias="index")]


def _model() -> Model:
    return (model_factory or Gemini)()


@router.get("/plan", response_class=HTMLResponse)
def plan_page(request: Request, woche: str = "") -> Response:
    """Die Seite: Entwurf oben, Einträge in Tandoor unten, die lädt htmx nach."""
    week = week_or_next(woche)
    return templates.TemplateResponse(
        request, "plan.html", week_context(week) | _draft_context(week)
    )


@router.get("/plan/entwurf", response_class=HTMLResponse)
def draft_section(request: Request, woche: str = "") -> Response:
    """Der Abschnitt Entwurf, auch zum Nachfragen, solange das Modell läuft."""
    return _section(request, week_or_next(woche))


@router.post("/plan/entwurf", response_class=HTMLResponse)
def create(request: Request, week: Week, hinweise: Annotated[str, Form()] = "") -> Response:
    """Lässt das Modell einen neuen Entwurf wählen, im Hintergrund."""
    week = week_or_next(week)
    model = _model()

    def work() -> None:
        with common.open_tandoor() as tandoor:
            drafts.create(tandoor, model, week, hinweise)

    jobs.start(week, work)
    return _section(request, week)


@router.post("/plan/entwurf/wunsch", response_class=HTMLResponse)
def wish(
    request: Request, week: Week, version: Version, wunsch: Annotated[str, Form()]
) -> Response:
    """Gibt dem Modell einen Wunsch in Worten, es ändert nur, was gemeint ist."""
    model = _model()
    jobs.start(week, lambda: drafts.revise(model, week, version, wunsch))
    return _section(request, week)


@router.post("/plan/entwurf/neu-waehlen", response_class=HTMLResponse)
def rechoose(
    request: Request,
    week: Week,
    version: Version,
    index: Index,
    wunsch: Annotated[str, Form()] = "",
) -> Response:
    """Lässt das Modell für einen einzelnen Platz ein anderes Gericht wählen."""
    model = _model()
    jobs.start(week, lambda: drafts.rechoose(model, week, version, index, wunsch))
    return _section(request, week)


@router.get("/plan/entwurf/kandidaten", response_class=HTMLResponse)
def candidates(request: Request, woche: str, version: int, index: int, q: str = "") -> Response:
    """Die Gerichte, die einen Platz übernehmen könnten, als Knöpfe."""
    draft = drafts.load(week_or_next(woche))
    if draft is None or draft.version != version:
        raise drafts.store.StaleDraftError(woche)
    found = drafts.candidates(draft, index, q)
    return templates.TemplateResponse(
        request,
        "plan_kandidaten.html",
        {"found": found, "index": index, "searched": bool(q.strip())},
    )


@router.post("/plan/entwurf/tauschen", response_class=HTMLResponse)
def swap(
    request: Request,
    week: Week,
    version: Version,
    index: Index,
    recipe_id: Annotated[int, Form()],
) -> Response:
    """Setzt ein anderes Gericht auf einen Platz, das Paar vom Wochenende wandert mit."""
    drafts.replace_recipe(week, version, index, recipe_id)
    return _section(request, week)


@router.post("/plan/entwurf/termin", response_class=HTMLResponse)
def appointment(
    request: Request, week: Week, version: Version, index: Index, titel: Annotated[str, Form()]
) -> Response:
    """Macht aus einem Platz einen Termin ohne Rezept."""
    drafts.make_appointment(week, version, index, titel)
    return _section(request, week)


@router.post("/plan/entwurf/details", response_class=HTMLResponse)
def details(
    request: Request,
    week: Week,
    version: Version,
    index: Index,
    portionen: Annotated[float, Form()],
    notiz: Annotated[str, Form()] = "",
) -> Response:
    """Ändert Portionen und Notiz eines Platzes."""
    drafts.set_details(week, version, index, portionen, notiz)
    return _section(request, week)


@router.post("/plan/entwurf/verwerfen", response_class=HTMLResponse)
def discard(request: Request, week: Week) -> Response:
    """Verwirft den Entwurf, danach lässt sich neu entwerfen."""
    drafts.discard(week)
    jobs.forget(week)
    return _section(request, week)


@router.get("/plan/entwurf/freigabe", response_class=HTMLResponse)
def release_form(request: Request, woche: str, version: int) -> Response:
    """Die Fragen vor dem Schreiben: wer auf einem geteilten Platz womit anfängt."""
    draft = drafts.load(week_or_next(woche))
    if draft is None or draft.version != version:
        raise drafts.store.StaleDraftError(woche)
    return templates.TemplateResponse(
        request,
        "plan_freigabe.html",
        {"draft": draft, "questions": drafts.questions(draft)},
    )


@router.post("/plan/entwurf/freigabe", response_class=HTMLResponse)
async def release(request: Request) -> Response:
    """Schreibt den Entwurf nach Tandoor, oder zeigt mit `vorschau`, was geschähe.

    Die Antworten auf die Fragen stehen in Feldern `lead-<Mahlzeit>-<von>-<bis>`, deren Namen
    erst der Entwurf festlegt. Das Formular wird deshalb hier selbst gelesen.
    """
    form = await request.form()
    week = week_or_next(str(form.get("woche", "")))
    version = int(str(form.get("version", "0")))
    preview = form.get("vorschau") == "true"
    leads = {}
    for key, value in form.multi_items():
        if key.startswith("lead-"):
            meal_type, first, last = key.removeprefix("lead-").split("_")
            slot = (int(meal_type), date.fromisoformat(first), date.fromisoformat(last))
            leads[slot] = int(str(value))

    def work() -> Applied:
        with common.open_tandoor() as tandoor:
            return drafts.release(tandoor, week, version, leads, preview)

    applied = await run_in_threadpool(work)
    written = not preview and not applied.problems
    return templates.TemplateResponse(
        request,
        "plan_freigabe_ergebnis.html",
        {"applied": applied, "preview": preview},
        headers={"HX-Trigger": "plan-geschrieben"} if written else None,
    )


@router.get("/plan/eintraege", response_class=HTMLResponse)
def entries(request: Request, tandoor: Tandoor, woche: str = "") -> Response:
    """Die Einträge der Woche in Tandoor, die eigenen zum Auswählen, die fremden nur zum Lesen."""
    week = week_or_next(woche)
    cleared = clear_week(tandoor, week, [], dry_run=True)
    return templates.TemplateResponse(
        request,
        "plan_eintraege.html",
        {"week": week, "mine": cleared.mine, "others": cleared.others},
    )


@router.post("/plan/zuruecknehmen", response_class=HTMLResponse)
def take_back(
    request: Request,
    tandoor: Tandoor,
    woche: Annotated[str, Form()],
    eintrag: Annotated[list[int], Form()] = [],  # noqa: B006
) -> Response:
    """Löscht die ausgewählten eigenen Einträge aus Tandoor.

    Ohne Auswahl wird nichts gelöscht. `clear_week` nähme sonst die ganze Woche, und ein
    versehentlich leeres Formular darf das nicht.
    """
    week = week_or_next(woche)
    if not eintrag:
        return templates.TemplateResponse(
            request, "plan_ergebnis.html", {"message": "Nichts ausgewählt, nichts gelöscht."}
        )
    cleared = clear_week(tandoor, week, eintrag, dry_run=False)
    if cleared.missing:
        message = f"Nicht mehr in {week}: {cleared.missing}. Nichts gelöscht, Seite neu laden."
    else:
        count = len(cleared.mine)
        message = f"{count} {'Eintrag' if count == 1 else 'Einträge'} gelöscht."
    return templates.TemplateResponse(
        request, "plan_ergebnis.html", {"message": message, "week": week}
    )


def _section(request: Request, week: str) -> Response:
    return templates.TemplateResponse(request, "plan_entwurf.html", _draft_context(week))


def _draft_context(week: str) -> dict[str, object]:
    """Was der Abschnitt Entwurf braucht: den Lauf, den Entwurf und die Plätze in Reihenfolge."""
    draft = drafts.load(week)
    context: dict[str, object] = {"week": week, "job": jobs.state(week), "draft": draft}
    if draft is None:
        return context
    order = {meal_type.id: position for position, meal_type in enumerate(draft.bundle.meal_types)}
    places = sorted(
        enumerate(draft.proposal.entries),
        key=lambda item: (item[1].from_date, order.get(item[1].meal_type_id, 99)),
    )
    return context | {
        "places": places,
        "meal_names": {meal_type.id: meal_type.name for meal_type in draft.bundle.meal_types},
        "ratings": {recipe.id: recipe.rating for recipe in draft.bundle.recipes},
    }
