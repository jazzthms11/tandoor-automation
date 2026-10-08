"""Der Wähler über die API: ein Modell stellt den Wochenplan aus dem Bündel zusammen.

Im Gespräch wählt Claude über den Skill, hier wählt ein Modell ohne Gespräch. Beide lesen dieselben
Regeln aus `regeln/wochenplan.md`, und beide gehen durch dieselbe Prüfung. Was herauskommt, ist ein
Entwurf und kein Ergebnis: geschrieben wird erst nach der Durchsicht.

Die Antwort kommt als strukturierte Ausgabe gegen ein Schema, nicht als Freitext. Findet die
Prüfung Mängel, geht die Liste einmal an das Modell zurück. Bleiben danach Mängel, kommt der
Entwurf trotzdem zurück, mit ihnen: von Hand behoben ist ein Mangel schneller als mit einem
dritten Lauf.

Das Modell steht hinter `Model`, einer Funktion von Systemprompt und Gesprächsverlauf zu Text.
Ein anderer Anbieter ist eine andere Funktion, kein Umbau.
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date
from importlib.resources import files
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from tandoor_automation.apply import share_problems, together_of, unfold
from tandoor_automation.bundle import PlanBundle
from tandoor_automation.proposal import Proposal, ProposalEntry, validate_proposal

MODEL = "opus"
"""Das Modell, das Claude Code nimmt. Ein Lauf je Woche fällt im Abo nicht ins Gewicht."""
DEADLINE_SECONDS = 600
"""So lange darf ein Lauf insgesamt dauern, dann ist er eher in einer Schleife als fleißig."""
METADATA = {"title", "default"}
"""Schlüssel im Schema, die nur beschreiben. Sie fallen vor dem Senden weg."""
ANSWER_RULES = """

## Die Antwort über die API

Hier antwortest du nicht im Gespräch, sondern einmal als JSON nach dem vorgegebenen Schema. Die
Woche setzt der Code, sie fehlt deshalb im Schema. In `reasoning` stehen zwei, drei Sätze für den
Haushalt: was die Woche trägt, welche Regel einem Hinweis weichen musste und welche unbewerteten
Rezepte dabei sind. Gelesen wird das am Handy, also knapp und ohne die Einträge aufzuzählen.

Wird ein Entwurf geändert, kommt er als deine letzte Antwort zurück, darunter der Wunsch. Gib dann
den ganzen Vorschlag wieder ab, nicht nur den geänderten Teil.
"""
FIX = """Die Prüfung im Code hat Mängel gefunden:

{problems}

Behebe sie und gib den ganzen Vorschlag noch einmal ab. Was in Ordnung war, bleibt."""


log = logging.getLogger(__name__)


class ChooserError(Exception):
    """Das Modell hat nicht geantwortet, oder nicht in der verlangten Form."""


class ChosenEntry(BaseModel):
    """Ein Eintrag, wie ihn das Modell abgibt. Wie `ProposalEntry`, nur ohne die Marken."""

    recipe_id: int | None = Field(None, description="ID aus dem Kochbuch, leer bei einem Termin")
    recipe_name: str = Field("", description="Name genau wie im Bündel, leer bei einem Termin")
    title: str = Field("", description="Nur bei einem Termin ohne Rezept, etwa Besuch")
    meal_type_id: int
    from_date: date
    to_date: date
    servings: float = Field(0, description="Gekochte Portionen über den ganzen Zeitraum")
    note: str = ""


class Answer(BaseModel):
    """Die ganze Antwort des Modells: der Plan und die Begründung für den Haushalt."""

    reasoning: str = Field(description="Zwei, drei Sätze für den Haushalt")
    entries: list[ChosenEntry]


@dataclass(frozen=True)
class Turn:
    """Ein Beitrag im Verlauf: `user` für den Code, `model` für die Antworten des Modells."""

    role: str
    text: str


class Model(Protocol):
    """Ein Modell, das auf Systemprompt und Verlauf mit Text nach einem JSON-Schema antwortet."""

    def __call__(self, system: str, turns: list[Turn], schema: dict[str, Any]) -> str:
        """Gibt die Antwort als JSON-Text."""
        ...


class ClaudeCode:
    """Claude Code ohne Gespräch (`claude -p`), angemeldet über das Abo statt über die API.

    Das Token kommt aus `claude setup-token` und steht als `CLAUDE_CODE_OAUTH_TOKEN` in der `.env`.
    Claude Code bekommt keine Werkzeuge und kein Gedächtnis: es liest Regeln und Verlauf und
    antwortet einmal gegen das Schema.
    """

    def __init__(self) -> None:
        """Prüft, ob Claude Code da ist, damit ein Fehler vor dem Lauf auffällt und nicht in ihm."""
        if shutil.which("claude") is None:
            raise ChooserError("Claude Code ist nicht installiert, `claude` fehlt im Pfad")

    def __call__(self, system: str, turns: list[Turn], schema: dict[str, Any]) -> str:
        """Schickt den Verlauf an Claude Code und gibt die Antwort als JSON-Text.

        `claude -p` kennt nur eine Eingabe und keine früheren Antworten. Der Verlauf steht deshalb
        als ein Text da, die eigenen Antworten von vorher darin als Zitat. Gearbeitet wird in
        einem leeren Ordner, der auch als Heimatverzeichnis dient: so findet Claude Code weder
        die `CLAUDE.md` des Klons noch Einstellungen, und es hat etwas, wohin es schreiben darf.

        Raises:
            ChooserError: Bei Fristablauf, fehlender Anmeldung oder einer Antwort ohne Ergebnis.
        """
        command = [
            "claude", "-p",
            "--model", MODEL,
            "--system-prompt", system,
            "--json-schema", json.dumps(schema),
            "--output-format", "json",
            "--tools", "",
            "--setting-sources", "",
            "--strict-mcp-config",
            "--no-session-persistence",
        ]  # fmt: skip
        with tempfile.TemporaryDirectory() as home:
            try:
                done = subprocess.run(
                    command,
                    input=_transcript(turns),
                    capture_output=True,
                    text=True,
                    cwd=home,
                    env=os.environ | {"HOME": home},
                    timeout=DEADLINE_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise ChooserError(
                    f"Claude ist nach {DEADLINE_SECONDS // 60} Minuten nicht fertig"
                ) from error
        return _result(done)


def _transcript(turns: list[Turn]) -> str:
    """Der Verlauf als ein Text: die Beiträge des Codes, dazwischen die eigenen Antworten."""
    parts = [
        turn.text if turn.role == "user" else f"Deine Antwort davor:\n\n```json\n{turn.text}\n```"
        for turn in turns
    ]
    return "\n\n".join(parts)


def _result(done: subprocess.CompletedProcess[str]) -> str:
    """Die strukturierte Antwort aus der Ausgabe von `claude -p --output-format json`."""
    try:
        output = json.loads(done.stdout)
    except json.JSONDecodeError:
        detail = (done.stderr or done.stdout).strip()[:300]
        raise ChooserError(f"Claude Code bricht ab ({done.returncode}): {detail}") from None
    answer = output.get("structured_output")
    if output.get("is_error") or answer is None:
        detail = str(output.get("result", ""))[:300]
        raise ChooserError(f"Claude antwortet ohne Ergebnis ({output.get('subtype')}): {detail}")
    log.info("Claude fertig nach %.0f s", output.get("duration_ms", 0) / 1000)
    return json.dumps(answer)


@dataclass(frozen=True)
class Chosen:
    """Ein Entwurf: der Vorschlag, die Begründung des Modells und die Mängel, die blieben."""

    proposal: Proposal
    reasoning: str
    problems: list[str]


def rules() -> str:
    """Die Regeln der Wahl, wie sie auch der Skill im Gespräch liest, samt Antwortform."""
    text = (files("tandoor_automation") / "regeln" / "wochenplan.md").read_text(encoding="utf-8")
    return text + ANSWER_RULES


def check(proposal: Proposal, bundle: PlanBundle) -> list[str]:
    """Prüft einen Entwurf so, wie `plan apply` ihn vor dem Schreiben prüft.

    Dazu gehört die entfaltete Form: zwei Mittagsgerichte über ungleiche Zeiträume decken die
    Woche, teilen aber keinen Platz, und das zeigt erst `share_problems`.
    """
    unfolded = unfold(proposal, together_of(bundle), {})
    return validate_proposal(proposal, bundle) + share_problems(unfolded)


def choose(
    model: Model,
    bundle: PlanBundle,
    hints: str = "",
    previous: Chosen | None = None,
    request: str = "",
) -> Chosen:
    """Lässt das Modell einen Entwurf wählen oder einen bestehenden ändern.

    Regeln und Bündel stehen vorn im Verlauf, Hinweise und Wünsche hinten. Der vordere Teil ist
    bei jedem Lauf derselbe und kann beim Anbieter im Cache bleiben.

    Args:
        model: Das Modell.
        bundle: Das Bündel der Woche.
        hints: Hinweise zur Woche, leer heißt Normalfall.
        previous: Ein bestehender Entwurf, der geändert werden soll.
        request: Was an `previous` anders werden soll.

    Returns:
        Der Entwurf mit Begründung und den Mängeln, die nach einer Nachbesserung blieben.

    Raises:
        ChooserError: Wenn das Modell nicht oder nicht in der verlangten Form antwortet.
    """
    turns = [Turn("user", _context(bundle, hints))]
    if previous is not None:
        turns += [Turn("model", _as_answer(previous)), Turn("user", request)]
    text = _ask(model, turns)
    chosen = _read(text, bundle)
    if not chosen.problems:
        return chosen
    turns += [Turn("model", text), Turn("user", FIX.format(problems=_listed(chosen.problems)))]
    return _read(_ask(model, turns), bundle)


def _context(bundle: PlanBundle, hints: str) -> str:
    """Das Bündel als JSON, darunter die Hinweise zur Woche."""
    hinted = hints.strip() or "keine, es gilt der Normalfall"
    return (
        f"Das Bündel der Woche {bundle.week}:\n\n```json\n{bundle.model_dump_json()}\n```\n\n"
        f"Hinweise zur Woche: {hinted}"
    )


def _as_answer(chosen: Chosen) -> str:
    """Ein Entwurf so, wie das Modell ihn abgegeben hätte."""
    entries = [
        ChosenEntry.model_validate(entry.model_dump(exclude={"marks"}))
        for entry in chosen.proposal.entries
    ]
    return Answer(reasoning=chosen.reasoning, entries=entries).model_dump_json()


def _ask(model: Model, turns: list[Turn]) -> str:
    return model(rules(), turns, schema())


def _read(text: str, bundle: PlanBundle) -> Chosen:
    """Liest die Antwort und prüft sie gleich."""
    try:
        answer = Answer.model_validate_json(text)
    except ValidationError as error:
        raise ChooserError(f"Antwort passt nicht zum Schema: {error}") from error
    proposal = Proposal(
        week=bundle.week,
        entries=[ProposalEntry.model_validate(entry.model_dump()) for entry in answer.entries],
    )
    return Chosen(proposal, answer.reasoning, check(proposal, bundle))


def _listed(problems: list[str]) -> str:
    return "\n".join(f"- {problem}" for problem in problems)


def schema() -> dict[str, Any]:
    """Das JSON-Schema der Antwort, ohne Verweise, Titel und Vorgaben.

    Pydantic legt verschachtelte Modelle unter `$defs` ab und verweist darauf. Eingesetzt ist
    das Schema kürzer zu lesen und unabhängig davon, wie viel JSON Schema der Anbieter versteht.
    Titel und Vorgaben tragen für das Modell nichts, die Vorgaben setzt beim Lesen Pydantic.
    Ein Feld, das selbst `title` heißt, steht unter `properties` und bleibt.
    """
    raw = Answer.model_json_schema()
    defs = raw.pop("$defs", {})

    def inline(node: Any) -> Any:  # noqa: ANN401
        if isinstance(node, list):
            return [inline(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return inline(defs[node["$ref"].rsplit("/", 1)[-1]])
        return {
            key: inline(value)
            for key, value in node.items()
            if not (key in METADATA and not isinstance(value, dict))
        }

    return inline(raw)
