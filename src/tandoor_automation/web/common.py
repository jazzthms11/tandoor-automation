"""Was alle Seiten teilen: Vorlagen, Navigation, der Zugang zu Tandoor und die Wochen."""

from collections.abc import Iterator
from datetime import date, timedelta
from importlib.resources import files
from typing import Annotated

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates

from tandoor_automation.bundle import next_week, parse_week, week_days
from tandoor_automation.config import Settings
from tandoor_automation.tandoor import TandoorClient

HERE = files("tandoor_automation") / "web"
PAGES = [("Wochenplan", "/plan"), ("Einkauf", "/einkauf"), ("Bewertung", "/bewertung")]
"""Die Navigation, eine Seite je Eintrag, die erste ist die Startseite."""
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _everywhere(_: Request) -> dict[str, object]:
    """Was jede Vorlage kennt, ohne dass jede Seite es einzeln übergibt."""
    return {"pages": PAGES}


templates = Jinja2Templates(directory=str(HERE / "templates"), context_processors=[_everywhere])


def day(value: date) -> str:
    """Ein Tag so, wie er am Kühlschrank gelesen wird: `Sa 10.10.`."""
    return f"{WEEKDAYS[value.weekday()]} {value:%d.%m.}"


templates.env.filters["tag"] = day


def tandoor() -> Iterator[TandoorClient]:
    """Ein Client je Anfrage. Er kostet keine Verbindung, solange nichts abgerufen wird."""
    with TandoorClient(Settings()) as client:
        yield client


Tandoor = Annotated[TandoorClient, Depends(tandoor)]


def partial(request: Request) -> bool:
    """Ob htmx nur einen Teil der Seite will. Beim Zurückblättern will es die ganze."""
    return "HX-Request" in request.headers and "HX-History-Restore-Request" not in request.headers


def week_or_next(week: str) -> str:
    """Die genannte Woche, ohne Angabe die kommende.

    Raises:
        ValueError: Wenn die Angabe keine ISO-Woche ist.
    """
    if not week:
        return next_week(date.today())
    try:
        parse_week(week)
    except ValueError as error:
        raise ValueError(f"Die Woche {week} gibt es nicht, gemeint ist etwa 2026-W42") from error
    return week


def shifted(week: str, weeks: int) -> str:
    """Die Woche, die so viele Wochen davor oder danach liegt."""
    year, number = parse_week(week)
    monday = date.fromisocalendar(year, number, 1) + timedelta(weeks=weeks)
    year, number, _ = monday.isocalendar()
    return f"{year}-W{number:02d}"


def week_context(week: str) -> dict[str, object]:
    """Was die Wochenauswahl oben auf einer Seite braucht."""
    days = week_days(week)
    return {
        "week": week,
        "first": days[0],
        "last": days[-1],
        "before": shifted(week, -1),
        "after": shifted(week, 1),
    }
