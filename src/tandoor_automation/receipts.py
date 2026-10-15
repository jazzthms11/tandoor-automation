"""Ein Kassenbon, unabhängig von seiner Quelle, und die Wege von Lidl und Kaufland dorthin.

Lidl gibt die Positionen eines Bons nicht als Felder zurück, sondern allein als gedruckten
Beleg in HTML. Die Zeilen darin tragen ihre Werte aber als Attribute, der Beleg muss also nicht
als Text gelesen werden.

Kaufland gibt nichts zurück. Sein Beleg ist ein PDF aus der App, und gelesen wird die Textebene
darin, Spalte für Spalte. Weil dabei anders als bei Lidl eine Zeile stillschweigend durchfallen
kann, rechnet `parse_kaufland` die Positionen gegen die gedruckte Summe.

Die Artikelnummer bleibt bewusst außen vor. Sie sieht nach einem stabilen Schlüssel aus, ist
aber keiner: dasselbe Lebensmittel trägt über die Jahre mehrere Nummern, und dieselbe Nummer
mehrere Namen. Zugeordnet wird deshalb über den Namen.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any

from pydantic import BaseModel

PIECE = "stk"
KILOGRAM = "kg"
WEIGHT_MARKER = "kg x"
"""Woran eine Gewichtsposition zu erkennen ist: ihr folgt eine zweite Zeile, die die Rechnung
je Kilo zeigt. Stückware hat diese Zeile nicht."""

ITEMS_START = "Preis EUR"
ITEMS_END = "Summe"
"""Zwischen diesen beiden Zeilen stehen auf dem Kaufland-Beleg die Positionen. Darunter folgen
Zahlungsart und Steuerblock, darüber die Anschrift der Filiale."""

PRICED = re.compile(r"^(?P<rest>.*?)\s\s+(?P<total>-?\d+,\d{2})(?:\s+(?P<tax>[A-Z]))?\s*$")
"""Eine Zeile mit einem Betrag in der rechten Spalte. Ohne Steuerklasse ist sie keine Position,
sondern ein Rabatt: `K Card XTRA Rabatt` hängt am Artikel darüber."""
MULTIPLE = re.compile(r"(?P<quantity>\d+)\s*\*\s*(?P<unit_price>\d+,\d{2})\s*$")
"""Die Stückrechnung, entweder hinter dem Namen oder allein auf der Zeile darunter."""
WEIGHED = re.compile(r"^(?P<kilos>\d+,\d{3})\s*kg$")
"""Das Gewicht einer gewogenen Position, allein auf der Zeile unter dem Namen. Einen Kilopreis
druckt Kaufland nicht."""
CENT = Decimal("0.01")
STAMP = re.compile(r"Datum:(\d{2})\.(\d{2})\.(\d{2}).*?Bon:(\d+)")
REGISTER = re.compile(r"Filiale:\s*(\d+)\s*Kasse:\s*(\d+)")
CITY = re.compile(r"^\d{5}\s+(\S.*)$")
CENTURY = 2000


class ReceiptItem(BaseModel):
    """Eine Position auf dem Bon, so wie sie gekauft wurde."""

    name: str
    quantity: Decimal
    unit: str
    unit_price: Decimal


class Receipt(BaseModel):
    """Ein Einkauf, unabhängig davon, aus welchem Laden er stammt."""

    source: str
    receipt_id: str
    purchased_on: date
    store: str
    items: list[ReceiptItem]


def parse_lidl(raw: dict[str, Any]) -> Receipt:
    """Liest einen Bon, wie ihn `bon fetch` abgelegt hat.

    Args:
        raw: Die Antwort der Lidl-API zu einem einzelnen Bon.

    Returns:
        Der Einkauf mit allen Positionen.
    """
    reader = _PrintedReceipt()
    reader.feed(raw["htmlPrintedReceipt"])
    store = raw.get("store")
    return Receipt(
        source="lidl",
        receipt_id=str(raw["id"]),
        purchased_on=datetime.fromisoformat(raw["date"]).date(),
        store=store.get("name", "") if isinstance(store, dict) else str(store or ""),
        items=_items(reader.lines),
    )


def parse_kaufland(text: str) -> Receipt:
    """Liest einen Kaufland-Beleg aus der Textebene seines PDF.

    Args:
        text: Die Ausgabe von `pdftotext -layout` zu einem Beleg.

    Returns:
        Der Einkauf mit allen Positionen.

    Raises:
        ValueError: Wenn der Beleg seinen Positionsblock, sein Datum oder seine Filiale nicht
            hergibt, oder wenn die gelesenen Positionen nicht die gedruckte Summe ergeben.
    """
    lines = text.splitlines()
    head, block, printed = _split(lines)
    day, number = _stamp(text)
    shop, register = _register(text)
    items, discounts = _kaufland_items(block)
    _balance(items, discounts, printed)
    return Receipt(
        source="kaufland",
        receipt_id=f"{day:%Y%m%d}-{shop}-{register}-{number}",
        purchased_on=day,
        store=_city(head),
        items=items,
    )


def _split(lines: list[str]) -> tuple[list[str], list[str], Decimal]:
    """Teilt den Beleg in Kopf, Positionsblock und gedruckte Summe.

    Args:
        lines: Die Zeilen des Belegs.

    Returns:
        Die Zeilen über dem Block, die Zeilen des Blocks und die Summe darunter.

    Raises:
        ValueError: Wenn der Block oder die Summe fehlt.
    """
    start = next((index for index, line in enumerate(lines) if ITEMS_START in line), None)
    end = next(
        (index for index, line in enumerate(lines) if line.strip().startswith(ITEMS_END)), None
    )
    if start is None or end is None or end <= start:
        raise ValueError("Der Beleg trägt keinen Positionsblock")
    total = PRICED.match(lines[end])
    if total is None:
        raise ValueError("Die Zeile der Summe trägt keinen Betrag")
    return lines[:start], lines[start + 1 : end], _amount(total["total"])


def _kaufland_items(lines: list[str]) -> tuple[list[ReceiptItem], Decimal]:
    """Macht aus den Zeilen des Positionsblocks die Positionen und die Summe der Rabatte.

    Args:
        lines: Die Zeilen zwischen Spaltenkopf und Summe.

    Returns:
        Die gekauften Positionen und die Rabatte, die an ihnen hängen.
    """
    items: list[ReceiptItem] = []
    discounts = Decimal(0)
    pending = ""
    for line in lines:
        found = PRICED.match(line) if line.strip() else None
        if found is None:
            pending = line.strip() or pending
            continue
        if found["tax"] is None:
            discounts += _amount(found["total"])
            continue
        items.append(_kaufland_item(found, pending))
        pending = ""
    return items, discounts


def _kaufland_item(found: re.Match[str], pending: str) -> ReceiptItem:
    """Baut eine Position aus ihrer Betragszeile und dem Namen, der ihr vorausgeht.

    Der Name steht entweder vor der Stückrechnung oder, wenn er dafür zu lang war, allein auf
    der Zeile darüber. Ohne Stückrechnung ist die Menge eins und der Betrag der Einzelpreis.
    Gewogenes trägt seinen Namen immer auf der Zeile darüber, der Kilopreis folgt aus Betrag und
    Gewicht.

    Args:
        found: Die getroffene Betragszeile.
        pending: Die Zeile darüber, falls sie keinen Betrag trug.

    Returns:
        Die Position.

    Raises:
        ValueError: Wenn zu einem Betrag kein Name zu finden ist.
    """
    rest = found["rest"].strip()
    weighed = WEIGHED.match(rest)
    if weighed and pending:
        kilos = _amount(weighed["kilos"])
        return ReceiptItem(
            name=pending,
            quantity=kilos,
            unit=KILOGRAM,
            unit_price=_amount(found["total"]) / kilos,
        )
    several = MULTIPLE.search(rest)
    name = rest[: several.start()].strip() if several else rest
    name = name or pending
    if not name:
        raise ValueError(f"Betrag {found['total']} ohne Artikelnamen")
    return ReceiptItem(
        name=name,
        quantity=_amount(several["quantity"]) if several else Decimal(1),
        unit=PIECE,
        unit_price=_amount(several["unit_price"]) if several else _amount(found["total"]),
    )


def _balance(items: list[ReceiptItem], discounts: Decimal, printed: Decimal) -> None:
    """Rechnet die gelesenen Positionen gegen die gedruckte Summe.

    Fällt eine Zeile durch das Raster, ist der Bon nicht halb gelesen, sondern falsch: die Ware
    käme nie in den Bestand, und aufgefallen wäre es niemandem. Jede Position zählt auf den Cent
    gerundet, wie gedruckt: der Kilopreis einer gewogenen ist ein Bruch.

    Args:
        items: Die gelesenen Positionen.
        discounts: Die Summe der Rabattzeilen, negativ.
        printed: Die Summe, wie sie auf dem Beleg steht.

    Raises:
        ValueError: Wenn beides nicht übereinstimmt.
    """
    counted = sum(((item.quantity * item.unit_price).quantize(CENT) for item in items), Decimal(0))
    counted += discounts
    if counted != printed:
        raise ValueError(f"Positionen ergeben {counted}, auf dem Beleg steht {printed}")


def _stamp(text: str) -> tuple[date, str]:
    """Liest Kaufdatum und Bonnummer aus dem Fuß des Belegs."""
    found = STAMP.search(text)
    if found is None:
        raise ValueError("Der Beleg trägt kein Datum mit Bonnummer")
    day, month, year, number = found.groups()
    return date(CENTURY + int(year), int(month), int(day)), number


def _register(text: str) -> tuple[str, str]:
    """Liest Filiale und Kasse aus dem Fuß des Belegs."""
    found = REGISTER.search(text)
    if found is None:
        raise ValueError("Der Beleg trägt keine Filiale mit Kasse")
    return found[1], found[2]


def _city(head: list[str]) -> str:
    """Liest den Ort aus der Anschrift über dem Positionsblock."""
    for line in head:
        found = CITY.match(line.strip())
        if found:
            return found[1].strip()
    return ""


@dataclass
class _Line:
    """Eine Zeile des gedruckten Belegs samt ihrer Attribute."""

    line_id: str
    description: str
    quantity: str | None
    unit_price: str
    texts: list[str] = field(default_factory=list)


class _PrintedReceipt(HTMLParser):
    """Sammelt die Artikelzeilen des Belegs in der Reihenfolge des Drucks.

    Eine Zeile steht im Beleg als mehrere `span`, die sich das Layout teilen und dieselbe `id`
    sowie dieselben Attribute tragen. Zusammengefasst werden sie über diese `id`.
    """

    def __init__(self) -> None:
        """Beginnt mit einem leeren Beleg."""
        super().__init__()
        self.lines: list[_Line] = []
        self._open: _Line | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Öffnet eine Artikelzeile oder setzt eine schon begonnene fort."""
        values = {key: value for key, value in attrs if value is not None}
        if tag != "span" or "article" not in values.get("class", ""):
            self._open = None
            return
        line_id = values.get("id", "")
        if self.lines and self.lines[-1].line_id == line_id:
            self._open = self.lines[-1]
            return
        self._open = _Line(
            line_id=line_id,
            description=values.get("data-art-description", ""),
            quantity=values.get("data-art-quantity"),
            unit_price=values.get("data-unit-price", "0"),
        )
        self.lines.append(self._open)

    def handle_data(self, data: str) -> None:
        """Hängt den gedruckten Text an die offene Zeile."""
        text = data.strip()
        if self._open is not None and text:
            self._open.texts.append(text)


def _items(lines: list[_Line]) -> list[ReceiptItem]:
    """Macht aus den Belegzeilen die gekauften Positionen.

    Eine Position beginnt dort, wo der gedruckte Text der Artikelbezeichnung entspricht. Alles
    dahinter auf derselben Zeile ist Preis und Steuerklasse, die Zeile danach gehört bei
    Gewichtsware noch zur selben Position.
    """
    items = []
    for index, line in enumerate(lines):
        if not line.texts or line.texts[0] != line.description:
            continue
        following = lines[index + 1] if index + 1 < len(lines) else None
        items.append(
            ReceiptItem(
                name=line.description,
                quantity=_amount(line.quantity or "1"),
                unit=KILOGRAM if _by_weight(line, following) else PIECE,
                unit_price=_amount(line.unit_price),
            )
        )
    return items


def _by_weight(line: _Line, following: _Line | None) -> bool:
    """Sagt, ob eine Position gewogen wurde."""
    if following is None or following.description != line.description:
        return False
    return WEIGHT_MARKER in following.texts


def _amount(text: str) -> Decimal:
    """Liest eine Zahl in deutscher Schreibweise."""
    return Decimal(text.replace(".", "").replace(",", "."))
