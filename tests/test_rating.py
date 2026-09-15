"""Die Grundbewertung und ihr Abgleich mit Tandoors Kochprotokoll.

Hier lohnen Tests, weil beide Richtungen still schiefgehen: eine falsch gelesene Zeile bewertet
das falsche Rezept, und ein übersehener Eintrag legt einen zweiten an. Tandoor mittelt die Noten
eines Rezepts, ein Duplikat wäre also nicht sichtbar, sondern würde die Note nur verziehen.
"""

import pytest

from tandoor_automation.models import CookLog
from tandoor_automation.rating import MARKER, changes, own_base_ratings, parse_ratings, payload

LEO, JAZZ = 1, 2


def _log(log_id: int, recipe_id: int, rating: int | None, user: int = LEO, comment: str = MARKER):
    return CookLog.model_validate(
        {
            "id": log_id,
            "recipe": recipe_id,
            "rating": rating,
            "comment": comment,
            "created_by": {"id": user},
        }
    )


def test_tabs_trennen_die_spalten():
    assert parse_ratings("5\t82\tWraps mit Tofu\n") == {82: 5}


def test_unlesbare_zeile_faellt_auf():
    """Sonst verschwindet eine Bewertung stillschweigend, weil die Zeile verrutscht ist."""
    with pytest.raises(ValueError, match="Zahlen"):
        parse_ratings("Wraps mit Tofu\t5")


def test_zeile_mit_leerzeichen_statt_tab():
    assert parse_ratings("3   11  Lasagne vegetarisch") == {11: 3}


def test_kommentare_und_leerzeilen_werden_uebersprungen():
    assert parse_ratings("# Kopf\n\n  # eingerückt\n4\t7\tCurry\n") == {7: 4}


def test_unbewertetes_rezept_steht_mit_null_drin():
    assert parse_ratings("0\t7\tCurry") == {7: 0}


@pytest.mark.parametrize("zeile", ["6\t7\tCurry", "-1\t7\tCurry"])
def test_note_ausserhalb_der_skala(zeile):
    with pytest.raises(ValueError, match="Sterne"):
        parse_ratings(zeile)


def test_zeile_ohne_id():
    with pytest.raises(ValueError, match="Rezept-ID"):
        parse_ratings("4")


def test_rezept_zweimal_in_der_datei():
    with pytest.raises(ValueError, match="schon weiter oben"):
        parse_ratings("4\t7\tCurry\n3\t7\tCurry nochmal")


def test_fremde_und_beilaeufige_eintraege_zaehlen_nicht():
    """Die Instanz ist geteilt, und der Knopf in der App schreibt Einträge ohne Marker."""
    logs = [
        _log(1, 7, 5),
        _log(2, 8, 4, user=JAZZ),
        _log(3, 9, 3, comment=""),
    ]
    assert set(own_base_ratings(logs, LEO)) == {7}


def test_neue_note_wird_angelegt():
    todo = changes({7: 4}, {})
    assert (todo[0].recipe_id, todo[0].stars, todo[0].log_id) == (7, 4, None)


def test_gleiche_note_bleibt_unberuehrt():
    assert changes({7: 4}, {7: _log(1, 7, 4)}) == []


def test_geaenderte_note_faesst_den_vorhandenen_eintrag_an():
    """Ein zweiter Eintrag würde sich mit dem ersten mitteln, statt ihn abzulösen."""
    todo = changes({7: 2}, {7: _log(1, 7, 4)})
    assert (todo[0].stars, todo[0].log_id) == (2, 1)


def test_zurueckgesetzte_note_wird_geloescht():
    todo = changes({7: 0}, {7: _log(1, 7, 4)})
    assert (todo[0].stars, todo[0].log_id) == (0, 1)


def test_unbewertet_ohne_eintrag_ist_nichts_zu_tun():
    assert changes({7: 0}, {}) == []


def test_koerper_traegt_marker_und_altes_datum():
    body = payload(changes({7: 4}, {})[0])
    assert body["recipe"] == 7
    assert body["rating"] == 4
    assert body["comment"] == MARKER
    assert str(body["created_at"]).startswith("2020-01-01")
