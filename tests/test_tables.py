"""Tests für den Weg der Tabellen von Hand zwischen Datei und Datenbank.

Geht beim Hin und Zurück eine Entscheidung verloren, fällt das erst auf, wenn ein Bon falsch
gebucht oder eine Ausnahme vergessen ist. Und der Stand der Bons darf beim Einlesen nie
schrumpfen, sonst bucht der nächste Lauf doppelt.
"""

import pytest

from tandoor_automation import store, tables

INTERVALLE = "# Kopf\n\n# --- Kühlschrank ---\n7\t239\tEi (M)\tMedian 11\n\t302\tGouda\n"
AUSNAHMEN = "# Kopf\nfrisch\t\t-\t\t386\tKoriander\tfrisch, hält wenige Tage\n"


@pytest.fixture(autouse=True)
def datenordner(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))


def _export(name):
    table = tables.TABLES[name]
    assert table.render is not None
    return table.render(tables.rows(table))


def _hin_und_zurueck(name, text):
    tables.load(tables.TABLES[name], text, dry_run=False)
    return tables.load(tables.TABLES[name], _export(name), dry_run=False)


@pytest.mark.parametrize(("name", "text"), [("intervalle", INTERVALLE), ("ausnahmen", AUSNAHMEN)])
def test_export_liest_sich_unveraendert_zurueck(name, text):
    assert _hin_und_zurueck(name, text) == tables.Diff(0, 0, 0)


def test_leere_tage_bleiben_als_zeile_aber_ohne_intervall():
    tables.load(tables.TABLES["intervalle"], INTERVALLE, dry_run=False)
    assert store.intervals() == {239: 7}
    assert "\t302\tGouda" in _export("intervalle")


def test_fehlende_zeile_wird_geloescht():
    table = tables.TABLES["intervalle"]
    tables.load(table, INTERVALLE, dry_run=False)
    assert tables.load(table, "7\t239\tEi (M)\n", dry_run=False).removed == 1


def test_gebuchte_bons_werden_nie_entfernt():
    table = tables.TABLES["importiert"]
    tables.load(table, "a\nb\n", dry_run=False)
    assert tables.load(table, "c\n", dry_run=False) == tables.Diff(1, 0, 0)
    assert store.booked() == {"a", "b", "c"}


def test_probelauf_schreibt_nichts():
    tables.load(tables.TABLES["intervalle"], INTERVALLE, dry_run=True)
    assert store.intervals() == {}


def test_doppelter_schluessel_faellt_auf():
    with pytest.raises(ValueError, match="mehrfach"):
        tables.load(tables.TABLES["intervalle"], "7\t239\tEi\n14\t239\tEi\n", dry_run=False)


def test_note_aus_der_oberflaeche_liest_sich_unveraendert_zurueck():
    bewertung = "# Kopf\n\n# --- Pasta ---\n5\t12\tBolognese\n"
    tables.load(tables.TABLES["bewertung"], bewertung, dry_run=False)
    store.set_rating(12, 4)
    store.set_rating(30, 3, "Carbonara")
    assert _export("bewertung").endswith("# --- Pasta ---\n4\t12\tBolognese\n3\t30\tCarbonara\n")
    assert tables.load(tables.TABLES["bewertung"], _export("bewertung"), True) == tables.Diff(
        0, 0, 0
    )
