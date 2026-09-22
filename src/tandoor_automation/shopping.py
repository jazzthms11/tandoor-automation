"""Die Rückfrage vor dem Einkauf: was ist noch da, was kommt auf die Liste.

Gefragt wird nicht der ganze Schrank, sondern was einen Auslöser hat. Rezeptware löst der
Wochenplan aus, Vorratsware die Zeit. Damit wächst die Frage mit dem Bedarf und nicht mit dem
Bestand.

Die Antwort überschreibt den Bestand, sie rechnet ihn nicht ab. Zwischen zwei Fragen nimmt die
Menge deshalb nicht ab: der Bestand ist eine Momentaufnahme mit Datum und keine laufende Bilanz.
Was davon zu halten ist, sagt `expires`.

Die Staffel der Antworten kommt aus der gebuchten Menge und nicht aus einer Tabelle. Zwei
Packungen Tiefkühlobst sind ein voller Schrank, acht Dosen Tomaten sind es auch, und eine feste
Grenze träfe immer nur eines von beidem.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from tandoor_automation.classes import StockFood
from tandoor_automation.models import InventoryEntry

CONFIRM_DAYS = 14
"""So lange gilt ein bestätigter Eintrag als real, danach fragt die Vorratsware wieder.

Geschätzt und nicht gemessen: aus den Kaufabständen ließ sich die Dauer nicht ableiten. Ein
einzelner Wert für alles ist der Anfang, je Klasse getrennte Intervalle stehen noch aus.
"""
BY_PLAN = "rezept"
BY_TIME = "vorrat"


@dataclass(frozen=True)
class Choice:
    """Ein Knopf der Rückfrage: was er als Bestand setzt und ob er kaufen heißt."""

    label: str
    amount: Decimal
    buys: bool


@dataclass(frozen=True)
class Question:
    """Eine Zeile der Rückfrage: ein Bestandseintrag und die Antworten, die zur Wahl stehen."""

    entry_id: int
    food_id: int
    food_name: str
    location: str
    unit: str
    amount: Decimal
    choices: list[Choice]


@dataclass(frozen=True)
class Item:
    """Ein Lebensmittel, wie es auf der Liste steht."""

    food_id: int
    food_name: str
    location: str


@dataclass(frozen=True)
class Review:
    """Was vor dem Einkauf zu tun ist: die Fragen und das, was ungefragt auf die Liste geht."""

    questions: list[Question]
    unasked: list[Item]


def review(
    planned: set[int],
    entries: list[InventoryEntry],
    stock: dict[int, StockFood],
    fresh: dict[int, StockFood],
    units: dict[int, str],
    today: date,
) -> Review:
    """Stellt zusammen, was vor dem Einkauf zu klären ist.

    Ungefragt auf die Liste geht dreierlei: die Frischware der Woche, die nie Bestand führt; die
    Bestandsware, die der Plan braucht und für die nie ein Eintrag entstand; und die fällige
    Bestandsware, von der nichts mehr da ist. Nach einer Menge zu fragen, die schon auf null
    steht, wäre eine Frage ohne Antwortmöglichkeit.

    Der letzte Fall ist der Grund, warum leere Vorratsware auch ohne Rezept auf die Liste kommt:
    Butter steht in keinem Gericht und fehlt trotzdem.

    Args:
        planned: IDs der Lebensmittel, die die Gerichte der Woche brauchen.
        entries: Alle Bestandseinträge aus Tandoor.
        stock: Name, Ort und Klasse je Lebensmittel, das Bestand führt.
        fresh: Name, Ort und Klasse je Lebensmittel, das je Plan gekauft wird.
        units: Name je Einheiten-ID.
        today: Der Tag, gegen den `expires` geprüft wird.

    Returns:
        Die Fragen und die Lebensmittel, die ungefragt auf die Liste gehen, beide nach Ort und
        Name sortiert.
    """
    questions = []
    unasked = []
    for entry in entries:
        food = stock.get(entry.food_id)
        if food is None or not _due(food, entry, entry.food_id in planned, today):
            continue
        choices = _choices(food.stock_class, entry.amount)
        if choices:
            questions.append(
                Question(
                    entry.id,
                    entry.food_id,
                    food.name,
                    food.location,
                    units.get(entry.unit_id, ""),
                    entry.amount,
                    choices,
                )
            )
        else:
            unasked.append(Item(entry.food_id, food.name, food.location))
    booked = {entry.food_id for entry in entries}
    asked = {question.food_id for question in questions}
    unasked = [item for item in unasked if item.food_id not in asked]
    for food_id in planned - asked - {item.food_id for item in unasked}:
        food = fresh.get(food_id)
        if food is None and food_id not in booked:
            food = stock.get(food_id)
        if food is not None:
            unasked.append(Item(food_id, food.name, food.location))
    return Review(_sorted(questions), _sorted(unasked))


def buy_list(review_: Review, answers: dict[int, Choice]) -> list[Item]:
    """Sucht zusammen, was auf die Einkaufsliste kommt.

    Args:
        review_: Die gestellten Fragen und das ungefragt Fehlende.
        answers: Die gewählte Antwort je Eintrags-ID. Fehlt eine, gilt sie als unbestätigt und
            das Lebensmittel wird gekauft: ein fehlendes Abendessen kostet mehr als eine Dose.

    Returns:
        Die zu kaufenden Lebensmittel, nach Ort und Name sortiert.
    """
    bought = list(review_.unasked)
    for question in review_.questions:
        choice = answers.get(question.entry_id)
        if choice is None or choice.buys:
            bought.append(Item(question.food_id, question.food_name, question.location))
    return _sorted(bought)


def confirmed_until(today: date) -> date:
    """Sagt, bis wann eine Antwort von heute trägt."""
    return today + timedelta(days=CONFIRM_DAYS)


def describe(question: Question) -> str:
    """Schreibt die Frage in eine Zeile, samt der Knöpfe."""
    stock = f"{_plain(question.amount)} {question.unit}".strip()
    buttons = "  ".join(
        f"[{index}] {choice.label}" for index, choice in enumerate(question.choices)
    )
    return f"{question.food_name} ({stock} gebucht)\n  {buttons}"


def _due(food: StockFood, entry: InventoryEntry, in_plan: bool, today: date) -> bool:
    """Sagt, ob dieser Eintrag diese Woche einen Auslöser hat."""
    if food.stock_class == BY_PLAN:
        return in_plan
    return entry.expires is None or entry.expires <= today


def _choices(stock_class: str, amount: Decimal) -> list[Choice]:
    """Baut die Knöpfe einer Frage aus der gebuchten Menge.

    Vorratsware liegt meist einzeln und oft angebrochen, dort genügt da oder leer. Rezeptware
    liegt in ganzen Packungen, dort steht die Menge zur Wahl: der Bestand, etwa die Hälfte, die
    letzte, keine. Doppelte Stufen fallen weg, damit bei kleinen Beständen nicht zweimal
    dasselbe dasteht.

    Args:
        stock_class: `rezept` oder `vorrat`.
        amount: Die gebuchte Menge.

    Returns:
        Die Knöpfe, vom vollen Schrank zum leeren. Leer, wenn es nichts zu fragen gibt.
    """
    if _too_little(stock_class, amount):
        return []
    if stock_class == BY_TIME:
        return [Choice("da", amount, False), Choice("leer", Decimal(0), True)]
    steps: list[Decimal] = []
    for step in (amount, amount // 2, Decimal(1), Decimal(0)):
        if step <= amount and step not in steps:
            steps.append(step)
    return [Choice(_label(step, amount), step, step <= 1) for step in steps]


def _too_little(stock_class: str, amount: Decimal) -> bool:
    """Sagt, ob so wenig gebucht ist, dass die Frage sich erübrigt und gekauft wird.

    Bei Rezeptware ist die letzte Packung schon der Kaufgrund, wenn die Woche sie braucht: beide
    Antworten hießen dann kaufen, und eine Frage mit nur einer Antwort ist keine.
    """
    if stock_class == BY_PLAN:
        return amount <= 1
    return amount <= 0


def _label(step: Decimal, amount: Decimal) -> str:
    """Benennt eine Stufe so, wie sie vor dem Schrank gelesen wird."""
    if step <= 0:
        return "leer"
    if step == 1:
        return "nur noch 1"
    if step == amount:
        return f"noch {_plain(step)}"
    return f"etwa {_plain(step)}"


def _sorted[T: (Question, Item)](items: list[T]) -> list[T]:
    """Sortiert nach Ort und Name, damit der Kühlschrank einmal aufgeht und nicht fünfmal."""
    return sorted(items, key=lambda item: (item.location, item.food_name.casefold()))


def _plain(amount: Decimal) -> str:
    """Schreibt eine Menge ohne nachlaufende Nullen und ohne Exponent."""
    return f"{amount.normalize():f}"
