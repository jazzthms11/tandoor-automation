"""Die Seite Wochenplan: was in einer Woche steht, und die eigenen Einträge zurücknehmen.

Das Zurücknehmen ist `plan clear` mit Auswahl. Der Entwurf eines neuen Plans kommt mit M4 auf
dieselbe Seite.
"""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from tandoor_automation.web.common import Tandoor, templates, week_context, week_or_next
from tandoor_automation.workflow import clear_week

router = APIRouter()


@router.get("/plan", response_class=HTMLResponse)
def plan_page(request: Request, woche: str = "") -> Response:
    """Das Gerüst der Seite, die Einträge lädt htmx nach."""
    return templates.TemplateResponse(request, "plan.html", week_context(week_or_next(woche)))


@router.get("/plan/eintraege", response_class=HTMLResponse)
def entries(request: Request, tandoor: Tandoor, woche: str = "") -> Response:
    """Die Einträge der Woche, die eigenen zum Auswählen, die fremden nur zum Lesen."""
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
