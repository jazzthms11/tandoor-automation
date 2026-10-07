---
name: wochenplan
description: Plant eine Woche Mittag- und Abendessen für Tandoor. Nutze diesen Skill, wenn Leo nach dem Wochenplan, dem Essensplan oder dem Meal Prep für eine Woche fragt, oder wenn er "plan die nächste Woche" sagt.
---

# Wochenplan

Du wählst die Gerichte einer Woche aus dem Tandoor-Kochbuch. Den Rahmen holt und prüft der Code,
die Wahl triffst du.

**Lies zuerst `src/tandoor_automation/regeln/wochenplan.md`.** Dort stehen Haushalt, Form der
Woche, wie du wählst und das Schema des Vorschlags. Dieselbe Datei liest der Lauf über die API,
hier steht nur, was im Gespräch dazukommt.

## Ablauf

1. `uv run plan bundle` schreibt `bundle/<woche>.json`. Ohne `--week` ist es die kommende Woche,
   sonst `--week 2026-W39`. Ist die Datei schon da und aus der Zielwoche, reicht sie
2. Lies das Bündel
3. Frag Leo in einer Nachricht, ob für die Woche etwas zu beachten ist, siehe *Die Frage zur
   Woche*. **Beende damit deinen Zug** und wähle erst nach der Antwort
4. Wähle die Gerichte nach den Regeln und schreib `vorschlag/<woche>.json` nach ihrem Schema
5. `uv run plan check vorschlag/<woche>.json`. Bessere nach, bis der Befehl sauber durchläuft
6. Zeig Leo die Woche als Tabelle im Gespräch und sag in zwei, drei Zeilen, warum diese Gerichte.
   Hat Leo etwas zur Woche gesagt, nenn in einer Zeile, was du daraus gemacht hast
7. Erst wenn Leo zustimmt: `uv run plan apply vorschlag/<woche>.json` schreibt die Woche nach
   Tandoor. Von dir aus schreibst du **nicht**, der Vorschlag ist bis dahin nur eine Datei

## Die Frage zur Woche

Ein Hinweis kommt auf zwei Wegen: als Zusatz beim Aufruf, etwa `/wochenplan dieses Wochenende
wenig Zeit` oder `/wochenplan W41, Samstag Besuch`, oder als Antwort auf die Frage aus Schritt 3.
Was er bewirkt, steht in den Regeln unter *Hinweise zur Woche*.

Die Frage stellst du auch dann, wenn der Aufruf schon einen Hinweis trug, denn vergessen wird
gerade das, woran beim Aufruf niemand gedacht hat. Sie ist eine offene Frage im Gespräch, keine
Auswahl, und nennt Woche, Zeitraum und die schon belegten Plätze aus `occupied`:

> W41 (Sa 03.10. bis Fr 09.10.). In Tandoor steht schon: Mi Abend „Essen bei Eltern“.
> Muss ich etwas beachten? Etwa Mahlzeiten, die ausfallen (Wochenende weg, Besuch, auswärts),
> Gäste, Reste, die weg müssen, oder Wünsche.

Ist nichts belegt, fällt der Satz dazu weg. Ein „nein“ heißt Normalfall. Nennt der Hinweis eine
Woche (`W41`, `übernächste Woche`), ruf `plan bundle --week` entsprechend auf.

## Wenn Leo etwas ändern will

Was beim Ändern gilt, steht in den Regeln unter *Wenn ein Vorschlag geändert wird*. Im Gespräch
kommt dazu:

- **Lass `plan check` nach jeder Änderung laufen**, auch nach einer kleinen. Eine verschobene
  Portionszahl kippt die Deckung eines Tages, ohne dass man es sieht
- **Zeig danach nur die geänderten Zeilen**, nicht die ganze Tabelle, außer Leo will sie sehen

Sagt Leo, so passe es, dann schreibt `uv run plan apply vorschlag/<woche>.json` die Woche nach
Tandoor. Der Befehl prüft noch einmal gegen den Stand, wie er jetzt in Tandoor ist, und legt nur
an, was dort noch fehlt. Ein zweiter Lauf schreibt deshalb nichts doppelt, und ein einzelner
nachgebesserter Eintrag lässt sich mit demselben Befehl nachschieben. `--dry-run` zeigt vorher, was
er tun würde und löscht die Datei nicht; die Frage nach der Aufteilung der Mittagessen stellt er
auch dann. Ohne `--dry-run` löscht `plan apply` die Vorschlagsdatei nach dem Schreiben, Tandoor ist
danach die einzige Wahrheit.

Was schon in Tandoor steht, ändert `plan apply` nicht. Soll ein bereits geschriebener Eintrag weg
oder anders aussehen, gehört das in Tandoors Oberfläche oder auf die Seite *Wochenplan* der
Oberfläche (`plan clear`); sag Leo das, statt es zu umgehen.

## Wenn Leo eine Bewertung ändern will

Die Noten stehen in der Tabelle `bewertung` der Datenbank auf leosserver, nicht im Repo und nicht
in Tandoor. Von hier aus kommst Du nicht an sie heran. Verweise Leo auf die Seite *Bewertung* der
Oberfläche unter `http://leosserver:8095/bewertung`: ein Klick auf einen Stern speichert und schreibt
sofort nach Tandoor. Ohne Oberfläche geht es über die CLI auf dem Server, im Klon unter
`/srv/config/tandoor-automation`:

```bash
docker compose run --rm app plan data export bewertung   # schreibt bewertung.tsv
# Zeile ändern: erste Spalte die Sterne, zweite die Rezept-ID
docker compose run --rm app plan data import bewertung
docker compose run --rm app plan rate
```

- **`plan rate` fasst den vorhandenen Eintrag** im Kochprotokoll an, statt einen zweiten anzulegen
- **Nicht in Tandoors Oberfläche bewerten.** Tandoor mittelt die Noten eines Rezepts, statt die
  neueste zu nehmen → ein Klick dort verzieht die Note und die Datei stimmt nicht mehr
- **Eine Note auf 0 setzen löscht sie** in Tandoor, das Rezept gilt dann wieder als unbewertet
- **Ein neues Rezept fehlt in der Tabelle.** Die Seite zeigt alle Rezepte aus Tandoor, ein Stern
  legt die Zeile an. In der Datei reicht eine angehängte Zeile mit Sternen und ID
