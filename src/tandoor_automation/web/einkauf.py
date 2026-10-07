"""Die Seite Einkauf: Bestand abfragen und die Einkaufsliste schreiben, wie `plan shop`.

Im Terminal fragt `plan shop` eine Zeile nach der anderen. Hier stehen alle Fragen auf einer
Seite, nach Ort gebündelt, und gehen mit einem Knopf zusammen ab. Zwischen dem Laden der Seite
und dem Absenden kann Zeit vergehen, der zweite Schritt holt den Stand deshalb neu aus Tandoor
und ordnet die Antworten den Fragen zu, wie sie jetzt sind.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from itertools import groupby
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response

from tandoor_automation.shopping import Choice, Question, describe_need
from tandoor_automation.web.common import Tandoor, templates, week_context, week_or_next
from tandoor_automation.workflow import book_answers, shopping_check, write_list

router = APIRouter()


@router.get("/einkauf", response_class=HTMLResponse)
def shopping_page(request: Request, woche: str = "") -> Response:
    """Das Gerüst der Seite. Die Fragen lädt htmx nach, Tandoor braucht dafür einige Sekunden."""
    return templates.TemplateResponse(request, "einkauf.html", week_context(week_or_next(woche)))


@router.get("/einkauf/fragen", response_class=HTMLResponse)
def questions(request: Request, tandoor: Tandoor, woche: str = "") -> Response:
    """Die Fragen der Woche, nach Ort gebündelt, und was ungefragt auf die Liste geht."""
    week = week_or_next(woche)
    check = shopping_check(tandoor, week, date.today())
    places = [
        (place, list(group))
        for place, group in groupby(check.review.questions, key=lambda question: question.location)
    ]
    needs = {food_id: describe_need(need) for food_id, need in check.demand.items()}
    return templates.TemplateResponse(
        request,
        "einkauf_fragen.html",
        {"week": week, "places": places, "unasked": check.review.unasked, "needs": needs},
    )


def match(questions: list[Question], picked: list[str]) -> tuple[dict[int, Choice], list[str]]:
    """Ordnet die Antworten aus dem Formular den Fragen zu, wie sie jetzt in Tandoor stehen.

    Eine Antwort ist `Eintrags-ID:Menge`. Die Menge statt der Stelle des Knopfs, weil sich die
    Knöpfe ändern, wenn jemand zwischendurch gebucht hat. Passt eine Antwort nicht mehr, bleibt
    die Frage unbeantwortet, und unbeantwortet heißt kaufen.

    Args:
        questions: Die Fragen, frisch aus `shopping_check`.
        picked: Die Antworten aus dem Formular, leere sind nicht beantwortet.

    Returns:
        Die gewählte Antwort je Eintrags-ID und die Namen der Fragen, deren Antwort nicht mehr
        passte.
    """
    wanted: dict[int, Decimal] = {}
    for value in picked:
        entry_id, _, amount = value.partition(":")
        try:
            wanted[int(entry_id)] = Decimal(amount)
        except (ValueError, InvalidOperation):
            continue
    answers: dict[int, Choice] = {}
    stale = []
    for question in questions:
        if question.entry_id not in wanted:
            continue
        amount = wanted.pop(question.entry_id)
        choice = next((choice for choice in question.choices if choice.amount == amount), None)
        if choice is None:
            stale.append(question.food_name)
        else:
            answers[question.entry_id] = choice
    return answers, stale + [f"Eintrag {entry_id}" for entry_id in wanted]


async def _answers(request: Request) -> list[str]:
    """Liest die Antworten aus dem Formular. Je Frage ein Feld `antwort-<Eintrags-ID>`."""
    form = await request.form()
    return [str(value) for key, value in form.multi_items() if key.startswith("antwort-") and value]


@router.post("/einkauf", response_class=HTMLResponse)
def shop(
    request: Request,
    tandoor: Tandoor,
    woche: Annotated[str, Form()],
    antwort: Annotated[list[str], Depends(_answers)],
    vorschau: Annotated[bool, Form()] = False,
) -> Response:
    """Bucht die Antworten in den Bestand und schreibt das Fehlende auf die Liste.

    Args:
        request: Die Anfrage.
        tandoor: Der Zugang zu Tandoor.
        woche: Die Woche, deren Gerichte den Bedarf stellen.
        antwort: Je beantworteter Frage `Eintrags-ID:Menge`.
        vorschau: Nur zeigen, was geschähe.
    """
    week = week_or_next(woche)
    today = date.today()
    check = shopping_check(tandoor, week, today)
    answers, stale = match(check.review.questions, antwort)
    bookings = book_answers(tandoor, check.review, answers, today, vorschau)
    listed = write_list(tandoor, check, answers, vorschau)
    added = [
        (
            item,
            ", ".join(check.demand[item.food_id].recipes) if item.food_id in check.demand else "",
        )
        for item in listed.added
    ]
    return templates.TemplateResponse(
        request,
        "einkauf_ergebnis.html",
        {
            "preview": vorschau,
            "bookings": bookings,
            "added": added,
            "already": listed.already,
            "stale": stale,
            "asked": len(check.review.questions),
            "answered": len(answers),
        },
    )
