"""Ein Kassenbon, unabhängig von seiner Quelle, und der Weg vom Lidl-Beleg dorthin.

Lidl gibt die Positionen eines Bons nicht als Felder zurück, sondern allein als gedruckten
Beleg in HTML. Die Zeilen darin tragen ihre Werte aber als Attribute, der Beleg muss also nicht
als Text gelesen werden.

Die Artikelnummer bleibt bewusst außen vor. Sie sieht nach einem stabilen Schlüssel aus, ist
aber keiner: dasselbe Lebensmittel trägt über die Jahre mehrere Nummern, und dieselbe Nummer
mehrere Namen. Zugeordnet wird deshalb über den Namen.
"""

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
