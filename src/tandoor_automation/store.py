"""Die eigene Datenbank: Entscheidungen von Hand und der Stand der Bons.

Tandoor bleibt die Wahrheit für alles, was dort ein Feld hat, also Plan, Bestand und Liste.
Hier liegt nur, was Tandoor nicht kennt: Grundbewertung, Klassen, Ausnahmen, Intervalle, die
Zuordnung der Bonnamen und welche Bons gebucht sind.

Eine Datenbank lohnt sich nicht wegen der Menge, sondern wegen zweier Schreiber. Zwei Anfragen,
die dieselbe Datei lesen und zurückschreiben, verlieren still eine Änderung, und beim Stand der
Bons heißt das: ein Bon wird doppelt gebucht. SQLite gibt Transaktionen ohne eigenen Dienst.

Alles Veränderliche liegt in einem Ordner außerhalb des Repos, `DATA_DIR`: die Datenbank, die
Rohbons und der Zugang zu Lidl. Das Schema wächst über Alembic und wird beim ersten Zugriff
nachgezogen.
"""

import sqlite3
from contextlib import closing
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from sqlite3 import Connection as SqliteConnection
from typing import Any

from alembic import command
from alembic.config import Config
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, event
from sqlmodel import Field, Session, SQLModel, create_engine, select

from tandoor_automation.classes import Placement
from tandoor_automation.mapping import Entry

DB_NAME = "tandoor.sqlite"
BUSY_MS = 5000
"""So lange wartet ein Schreiber, wenn der andere gerade schreibt, statt sofort abzubrechen."""


class Paths(BaseSettings):
    """Liest `DATA_DIR` aus der Umgebung oder aus `.env`. Ohne Angabe `data/` im Arbeitsordner."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    data_dir: Path = Path("data")


def data_dir() -> Path:
    """Der Ordner für alles Veränderliche."""
    return Paths().data_dir


def bons_dir() -> Path:
    """Der Ordner der Rohbons, je Laden ein Unterordner."""
    return data_dir() / "bons"


class Hand(SQLModel):
    """Was jede Tabelle hat, die von Hand gepflegt wird.

    `section` und `position` halten die Gliederung der Datei, aus der die Zeile kam, damit ein
    Export wieder so aussieht wie vorher. `note` ist der Rest der Zeile, die Gedächtnisstütze.
    """

    note: str = ""
    section: str = ""
    position: int = 0
    changed_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())


class Rating(Hand, table=True):
    """Die Grundbewertung eines Rezepts, 0 heißt unbewertet."""

    recipe_id: int = Field(primary_key=True)
    stars: int


class CategoryClass(Hand, table=True):
    """Klasse und Ort einer Supermarkt-Kategorie."""

    category: str = Field(primary_key=True)
    stock_class: str
    location: str = ""


class FoodException(Hand, table=True):
    """Ein Lebensmittel, dessen Klasse oder Ort nicht zur Kategorie passt. Leer heißt geerbt."""

    food_id: int = Field(primary_key=True)
    stock_class: str = ""
    location: str = ""


class FoodInterval(Hand, table=True):
    """Wie lange eine Antwort trägt. Ohne Tage steht die Zeile nur als Lesehilfe da."""

    food_id: int = Field(primary_key=True)
    days: int | None = None


class ReceiptMapping(SQLModel, table=True):
    """Eine Zeile der Zuordnung, siehe `mapping`. Ohne ID und ohne `discarded` unentschieden."""

    store: str = Field(default="", primary_key=True)
    receipt_name: str = Field(primary_key=True)
    food_id: int | None = None
    discarded: bool = False
    changed_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())


class BookedReceipt(SQLModel, table=True):
    """Ein Bon, der abgehandelt ist, gebucht oder übersprungen."""

    receipt_id: str = Field(primary_key=True)
    booked_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())


_engines: dict[Path, Engine] = {}


def engine(migrate: bool = True) -> Engine:
    """Öffnet die Datenbank im Datenordner und zieht beim ersten Mal das Schema nach.

    Args:
        migrate: Das Schema auf den neuesten Stand bringen. Nur Alembic selbst schaltet das ab.

    Returns:
        Die Engine, je Datei nur einmal gebaut.
    """
    path = data_dir() / DB_NAME
    if path in _engines:
        return _engines[path]
    path.parent.mkdir(parents=True, exist_ok=True)
    built = create_engine(f"sqlite:///{path}")
    event.listen(built, "connect", _pragmas)
    if migrate:
        upgrade(built)
        _engines[path] = built
    return built


def upgrade(target: Engine) -> None:
    """Bringt das Schema auf den neuesten Stand. Ein zweiter Aufruf tut nichts."""
    config = Config()
    config.set_main_option("script_location", str(files("tandoor_automation") / "migrations"))
    with target.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def _pragmas(connection: SqliteConnection, _: Any) -> None:  # noqa: ANN401
    """Stellt jede neue Verbindung ein.

    WAL lässt Lesen neben einem Schreiber zu, statt die Datei zu sperren. Die Wartezeit sorgt
    dafür, dass zwei Schreiber nacheinander drankommen, statt dass einer mit "locked" abbricht.
    """
    cursor = connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute(f"PRAGMA busy_timeout={BUSY_MS}")
    cursor.close()


def backup(target: Path | None = None) -> Path:
    """Schreibt eine Kopie der Datenbank, auch während jemand schreibt.

    restic sichert Dateien, und eine mitten im Schreiben gelesene Datenbank ist beim
    Zurückspielen kaputt. Die Kopie geht deshalb über SQLites eigene Sicherung und wird erst
    unter ihren Namen gelegt, wenn sie vollständig ist.

    Args:
        target: Pfad der Kopie. Ohne Angabe `backup/` im Datenordner.

    Returns:
        Der Pfad der Kopie.
    """
    target = target or data_dir() / "backup" / DB_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f"{target.name}.teil")
    engine()
    with (
        closing(sqlite3.connect(data_dir() / DB_NAME)) as source,
        closing(sqlite3.connect(partial)) as copy,
    ):
        source.backup(copy)
    partial.replace(target)
    return target


def session() -> Session:
    """Eine Sitzung auf der Datenbank, als Kontextmanager zu benutzen."""
    return Session(engine())


def ratings() -> dict[int, int]:
    """Note je Rezept-ID, unbewertete (0) eingeschlossen."""
    with session() as db:
        return {row.recipe_id: row.stars for row in db.exec(select(Rating))}


def categories() -> dict[str, Placement]:
    """Klasse und Ort je Supermarkt-Kategorie."""
    with session() as db:
        return {
            row.category: Placement(row.stock_class, row.location)
            for row in db.exec(select(CategoryClass))
        }


def exceptions() -> dict[int, Placement]:
    """Klasse und Ort je Lebensmittel-ID, die von ihrer Kategorie abweicht."""
    with session() as db:
        return {
            row.food_id: Placement(row.stock_class, row.location)
            for row in db.exec(select(FoodException))
        }


def intervals() -> dict[int, int]:
    """Tage bis zur nächsten Rückfrage je Lebensmittel-ID, nur wo Tage stehen."""
    with session() as db:
        rows = db.exec(select(FoodInterval))
        return {row.food_id: row.days for row in rows if row.days is not None}


def mapping() -> list[Entry]:
    """Alle Zeilen der Zuordnung, auch die unentschiedenen, nach Bonname sortiert."""
    with session() as db:
        rows = db.exec(select(ReceiptMapping)).all()
    entries = [Entry(row.receipt_name, row.store, row.food_id, row.discarded) for row in rows]
    return sorted(entries, key=lambda entry: (entry.receipt_name.casefold(), entry.store))


def add_mapping(entries: list[Entry]) -> int:
    """Nimmt neue Bonnamen auf. Was schon dasteht, bleibt unberührt.

    Args:
        entries: Die Zeilen nach `merge`, alte und neue.

    Returns:
        Wie viele Namen neu dazukamen.
    """
    with session() as db:
        known = {(row.store, row.receipt_name) for row in db.exec(select(ReceiptMapping))}
        fresh = [entry for entry in entries if entry.key not in known]
        db.add_all(
            ReceiptMapping(
                store=entry.store,
                receipt_name=entry.receipt_name,
                food_id=entry.food_id,
                discarded=entry.discarded,
            )
            for entry in fresh
        )
        db.commit()
    return len(fresh)


def booked() -> set[str]:
    """Die IDs der Bons, die schon abgehandelt sind."""
    with session() as db:
        return set(db.exec(select(BookedReceipt.receipt_id)))


def remember(receipt_ids: set[str]) -> int:
    """Hält fest, dass diese Bons abgehandelt sind. Doppelte schaden nicht.

    Args:
        receipt_ids: Die IDs der Bons.

    Returns:
        Wie viele davon neu waren.
    """
    with session() as db:
        known = set(db.exec(select(BookedReceipt.receipt_id)))
        fresh = sorted(receipt_ids - known)
        db.add_all(BookedReceipt(receipt_id=receipt_id) for receipt_id in fresh)
        db.commit()
    return len(fresh)
