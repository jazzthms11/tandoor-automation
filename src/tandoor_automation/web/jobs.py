"""Arbeit, die länger dauert als eine Anfrage: der Lauf des Modells.

Ein Entwurf braucht bis zu einer Minute, und so lange hält kein Reverse Proxy eine Anfrage offen.
Der Lauf geht deshalb in einen eigenen Thread, und die Seite fragt alle paar Sekunden nach, ob er
fertig ist. Das Ergebnis selbst liegt danach in der Datenbank, hier steht nur, ob gerade etwas
läuft und ob der letzte Lauf scheiterte.

Der Dienst läuft als ein Prozess, ein Wörterbuch reicht. Nach einem Neustart ist ein laufender
Lauf vergessen, der Entwurf davor bleibt.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock, Thread

log = logging.getLogger(__name__)


@dataclass
class Job:
    """Ein Lauf für eine Woche."""

    running: bool = True
    error: str = ""


_jobs: dict[str, Job] = {}
_lock = Lock()


def start(key: str, work: Callable[[], object]) -> None:
    """Startet einen Lauf, wenn für diesen Schlüssel nicht schon einer läuft.

    Raises:
        ValueError: Wenn schon einer läuft. Zwei Läufe auf demselben Entwurf überschrieben sich.
    """
    with _lock:
        current = _jobs.get(key)
        if current is not None and current.running:
            raise ValueError("Für diese Woche läuft das Modell schon")
        job = _jobs[key] = Job()

    def run() -> None:
        try:
            work()
        except Exception as error:  # noqa: BLE001
            log.exception("Lauf für %s gescheitert", key)
            job.error = str(error) or type(error).__name__
        finally:
            job.running = False

    Thread(target=run, daemon=True).start()


def state(key: str) -> Job | None:
    """Der laufende oder zuletzt gescheiterte Lauf. Ein erfolgreicher ist danach vergessen."""
    with _lock:
        job = _jobs.get(key)
        if job is not None and not job.running and not job.error:
            del _jobs[key]
            return None
        return job


def forget(key: str) -> None:
    """Vergisst den Fehler eines Laufs, etwa wenn danach von Hand weitergemacht wird."""
    with _lock:
        job = _jobs.get(key)
        if job is not None and not job.running:
            del _jobs[key]
