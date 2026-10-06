"""Alembic-Umgebung. Läuft beim ersten Zugriff aus `store.upgrade` oder von Hand über `alembic`.

Von `store` kommt die offene Verbindung mit, von Hand baut sich die Umgebung ihre eigene auf die
Datenbank im Datenordner.
"""

from alembic import context
from sqlalchemy import Connection
from sqlmodel import SQLModel

from tandoor_automation import store


def _run(connection: Connection) -> None:
    """Führt die Migrationen auf einer Verbindung aus.

    `render_as_batch`, weil SQLite kaum `ALTER TABLE` kann: Alembic baut die Tabelle dann neu
    und kopiert die Zeilen hinüber.
    """
    context.configure(
        connection=connection, target_metadata=SQLModel.metadata, render_as_batch=True
    )
    with context.begin_transaction():
        context.run_migrations()


given = context.config.attributes.get("connection")
if given is None:
    with store.engine(migrate=False).begin() as connection:
        _run(connection)
else:
    _run(given)
