"""Tests für das Zuordnen der Antworten aus der Oberfläche.

Zwischen Laden und Absenden kann jemand anders gebucht haben. Landet eine Antwort dann auf dem
falschen Knopf, steht still eine falsche Menge im Bestand, und die nächste Frage kommt zu spät.
"""

from decimal import Decimal

from tandoor_automation.shopping import Choice, Question
from tandoor_automation.web.einkauf import match


def _frage(entry_id, name, *amounts):
    choices = [Choice(str(amount), Decimal(amount), amount <= 1) for amount in amounts]
    return Question(entry_id, entry_id, name, "", "Stück", Decimal(amounts[0]), choices)


def test_antwort_findet_ihren_knopf_ueber_die_menge():
    answers, stale = match([_frage(1, "Tomaten", 4, 2, 1, 0)], ["1:2"])
    assert answers == {1: Choice("2", Decimal(2), False)}
    assert stale == []


def test_veraltete_antwort_wird_verworfen_statt_umgedeutet():
    fragen = [_frage(1, "Tomaten", 3, 1, 0), _frage(2, "Mais", 2, 1, 0)]
    answers, stale = match(fragen, ["1:4", "2:1", "7:1"])
    assert list(answers) == [2]
    assert stale == ["Tomaten", "Eintrag 7"]
