"""Das Lesen und Schreiben von `zuordnung.tsv`.

Hier lohnen Tests, weil die Datei ihr eigenes Format ist und der Weg hin und zurück stimmen muss.
Schreibt der Renderer eine Zeile, die der Parser anders liest, sind alle Entscheidungen verloren,
und der nächste Lauf legt sie als neue, unentschiedene Namen wieder an.

Die Spaltenbreite trägt das: eine Spalte breiter als ein Tabulator bekommt für ein kurzes Feld
zwei davon, und das leere Feld dazwischen verschiebt alles Folgende um eine Stelle.
"""

from collections import Counter

from tandoor_automation.mapping import (
    Counts,
    Entry,
    merge,
    parse_mapping,
    problems,
    render,
    resolve,
    spanning,
)

FOODS = {426: "Sojagranulat", 623: "Sojaschnetzel", 339: "Brot"}


def _counts(**per_store: dict[str, int]) -> Counts:
    counts: Counts = Counter()
    for store, names in per_store.items():
        for name, count in names.items():
            counts[(store, name)] = count
    return counts


def _roundtrip(entries: list[Entry]) -> list[Entry]:
    return parse_mapping(render(entries, FOODS))


def test_geschriebenes_wird_gleich_wieder_gelesen():
    """Zugeordnet, verworfen, unentschieden und mit Laden, alle vier Formen einer Zeile."""
    entries = [
        Entry(receipt_name="Soja Schnetzel", food_id=426, count=3),
        Entry(receipt_name="Soja Schnetzel", store="kaufland", food_id=623, count=1),
        Entry(receipt_name="Zwiebelzopf", discarded=True, count=1),
        Entry(receipt_name="Neuer Artikel", count=1),
    ]
    back = _roundtrip(entries)
    assert [(e.receipt_name, e.store, e.food_id, e.discarded) for e in back] == [
        ("Soja Schnetzel", "", 426, False),
        ("Soja Schnetzel", "kaufland", 623, False),
        ("Zwiebelzopf", "", None, True),
        ("Neuer Artikel", "", None, False),
    ]


def test_langer_name_verschiebt_die_spalten_nicht():
    """Ein Name über die Spaltenbreite hinaus bekommt nur einen Tabulator und bleibt lesbar."""
    lang = "Ein sehr langer Artikelname vom Bon"
    back = _roundtrip([Entry(receipt_name=lang, food_id=339, count=1)])
    assert back[0].receipt_name == lang
    assert back[0].food_id == 339


def test_die_ladenzeile_sticht_die_allgemeine():
    entries = [
        Entry(receipt_name="Soja Schnetzel", food_id=426),
        Entry(receipt_name="Soja Schnetzel", store="kaufland", food_id=623),
    ]
    keys = {("lidl", "Soja Schnetzel"), ("kaufland", "Soja Schnetzel")}
    assert resolve(entries, keys) == {
        ("lidl", "Soja Schnetzel"): 426,
        ("kaufland", "Soja Schnetzel"): 623,
    }


def test_ohne_ladenzeile_gilt_die_allgemeine_ueberall():
    entries = [Entry(receipt_name="Wurzelbrot", food_id=339)]
    keys = {("lidl", "Wurzelbrot"), ("kaufland", "Wurzelbrot")}
    assert set(resolve(entries, keys).values()) == {339}


def test_unentschiedenes_steht_nicht_im_ergebnis():
    entries = [Entry(receipt_name="Neuer Artikel")]
    assert resolve(entries, {("lidl", "Neuer Artikel")}) == {}


def test_die_allgemeine_zeile_zaehlt_ohne_ihre_ladenzeilen():
    """Was die Ladenzeile für sich beansprucht, zählt die allgemeine nicht mehr mit."""
    known = [
        Entry(receipt_name="Soja Schnetzel", food_id=426),
        Entry(receipt_name="Soja Schnetzel", store="kaufland", food_id=623),
    ]
    counts = _counts(lidl={"Soja Schnetzel": 3}, kaufland={"Soja Schnetzel": 1})
    merged = merge(known, counts)
    assert [(e.store, e.count) for e in merged] == [("", 3), ("kaufland", 1)]


def test_neuer_name_kommt_ohne_laden_hinein():
    counts = _counts(kaufland={"Wurzelbrot": 2})
    merged = merge([], counts)
    assert [(e.receipt_name, e.store, e.count) for e in merged] == [("Wurzelbrot", "", 2)]


def test_eine_entscheidung_fuer_zwei_laeden_wird_genannt():
    entries = [Entry(receipt_name="Wurzelbrot", food_id=339)]
    counts = _counts(lidl={"Wurzelbrot": 1}, kaufland={"Wurzelbrot": 2})
    assert "Wurzelbrot" in spanning(entries, counts)[0]


def test_die_ladenzeile_beendet_die_meldung():
    entries = [
        Entry(receipt_name="Soja Schnetzel", food_id=426),
        Entry(receipt_name="Soja Schnetzel", store="kaufland", food_id=623),
    ]
    counts = _counts(lidl={"Soja Schnetzel": 3}, kaufland={"Soja Schnetzel": 1})
    assert spanning(entries, counts) == []


def test_ladenzeile_ohne_vorkommen_ist_ballast():
    entries = [Entry(receipt_name="Soja Schnetzel", store="kaufland", food_id=623, count=0)]
    assert problems(entries, FOODS) == ["Soja Schnetzel (kaufland): kommt bei kaufland nicht vor"]


def test_dieselbe_zeile_zweimal_faellt_auf():
    entries = [
        Entry(receipt_name="Wurzelbrot", food_id=339, count=1),
        Entry(receipt_name="Wurzelbrot", food_id=426, count=1),
    ]
    assert problems(entries, FOODS)[0] == "Wurzelbrot: steht mehrfach in der Datei"
