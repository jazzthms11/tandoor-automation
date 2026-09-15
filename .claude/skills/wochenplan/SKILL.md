---
name: wochenplan
description: Plant eine Woche Mittag- und Abendessen für Tandoor. Nutze diesen Skill, wenn Leo nach dem Wochenplan, dem Essensplan oder dem Meal Prep für eine Woche fragt, oder wenn er "plan die nächste Woche" sagt.
---

# Wochenplan

Du wählst die Gerichte einer Woche aus dem Tandoor-Kochbuch. Den Rahmen holt und prüft der Code,
die Wahl triffst du.

## Ablauf

1. `uv run plan bundle` schreibt `bundle/<woche>.json`. Ohne `--week` ist es die kommende Woche,
   sonst `--week 2026-W39`. Ist die Datei schon da und aus der Zielwoche, reicht sie
2. Lies das Bündel. Es enthält die sieben Tage, die Mahlzeiten mit ihren Uhrzeiten, die schon
   belegten Plätze (`occupied`), acht Wochen Planhistorie (`history`) und das ganze Kochbuch
3. Wähle die Gerichte und schreib `vorschlag/<woche>.json` nach dem Schema unten
4. `uv run plan check vorschlag/<woche>.json`. Bessere nach, bis der Befehl sauber durchläuft
5. Zeig Leo die Woche als Tabelle im Gespräch und sag in zwei, drei Zeilen, warum diese Gerichte.
   Schreib **nicht** nach Tandoor, `plan apply` gibt es noch nicht

## Der Haushalt

Zwei Personen. Eine Portion ist eine Mahlzeit für eine Person, `servings` an einem Eintrag ist
also die Zahl der gekochten Portionen, nicht die der Esser.

Geplant werden immer alle sieben Mittag- und alle sieben Abendessen. Gekocht wird an vier Tagen:
sonntags die Mittagessen der Woche und das Abendessen, dienstags und donnerstags je ein
Abendessen für zwei Abende, samstags eines für Samstagabend und den Sonntagmittag.

Der Plan entsteht donnerstags, freitags wird eingekauft, sonntags vorgekocht.

## Die Form der Woche

| Platz | Eintrag | Portionen |
| --- | --- | --- |
| Mittag Mo bis Fr | zwei Einträge, beide Mo bis Fr | je 5 |
| Mittag Sa | Sa bis Sa, eine Kleinigkeit | 2 |
| Mittag So | So bis So, dasselbe Rezept wie Samstagabend | 2 |
| Abend Mo | steht schon im Plan, kommt aus der Vorwoche | 4 |
| Abend Di und Mi | Di bis Mi | 4 |
| Abend Do und Fr | Do bis Fr | 4 |
| Abend Sa | Sa bis Sa | 2 |
| Abend So | So bis Mo der **Folgewoche** | 4 |

Zwei Dinge daran sind leicht zu übersehen:

- **Der Montagabend gehört der Vorwoche.** Er steht als `occupied` im Bündel, weil das
  Sonntagsgericht der Vorwoche bis dorthin reicht. Lass ihn in Ruhe. Steht dort nichts, plan ihn
  selbst als eigenen Eintrag Mo bis Mo mit 2 Portionen
- **Der Sonntagabend reicht über die Woche hinaus**, sein `to_date` ist der Montag danach

Die beiden Mittagsgerichte laufen als je ein Eintrag über Mo bis Fr. Fünf Portionen auf fünf Tage
heißt: an jedem Tag isst eine Person das eine und die andere das andere Gericht, und über die
Woche wird abgewechselt. Deshalb zwei verschiedene Gerichte und nicht zehn Portionen von einem.

Samstagabend und Sonntagmittag sind dasselbe Gericht in zwei Einträgen, einmal mit 2 Portionen für
den Abend und einmal mit 2 für den Mittag. Gekocht wird beides am Samstag.

## Wie du wählst

**Vegetarisch.** Der Haushalt isst seit kurzem fleischlos. Im Kochbuch stehen trotzdem
Fleischgerichte, weil Verwandte dieselbe Instanz nutzen. Nimm Rezepte mit dem Schlagwort
`Vegetarisch`. Ein Rezept mit `Fleisch`, `Rind` oder `Hähnchen` geht nur, wenn es sich offensichtlich
ersetzen lässt; dann schreib die Ersetzung in das Feld `note`, etwa "mit Sojagranulat statt Hack".
Oft gibt es das Gericht ohnehin zweimal, einmal mit und einmal ohne. `Fisch` ist in Ordnung.

**Eiweiß.** Beide achten auf viel Protein. Nährwerte liefert Tandoor nicht, also urteile nach den
Zutaten, die im Namen und in der `description` stehen: Tofu, Linsen, Kichererbsen, Bohnen,
Sojagranulat, Quark, Skyr, Käse, Ei, Fisch. Mindestens die beiden Mittagsgerichte sollen kräftig
liegen, eine reine Nudelpfanne mit Tomatensoße zweimal die Woche ist zu wenig.

**Kohlenhydrate.** Die beiden Mittagsgerichte auf verschiedenen Grundlagen, am besten eines auf
Reis und eines auf Nudeln. Beides lässt sich gut vorkochen. Eine reine Nudelwoche kommt vor, ist
aber die Ausnahme, und dann sag es dazu.

**Vorkochen.** Für die Mittagessen zählt das Schlagwort `Mealprep`, das sind die Gerichte, die
aufgewärmt noch schmecken. Aufläufe, Currys, Suppen und Bowls sind sichere Kandidaten, Salate mit
Blattsalat und alles Frittierte nicht.

**Abwechslung.** Nichts wiederholen, was in `history` in den letzten beiden Wochen stand. Kein
Gericht zweimal in derselben Woche, ausgenommen das Paar Samstagabend und Sonntagmittag. Über den
ganzen Plan hinweg nicht dreimal dieselbe Küche.

**Aufwand.** Am Sonntag wird dreimal gekocht, zwei Mittagsgerichte und ein Abendessen. Nimm dafür
nicht drei Rezepte mit 50 Minuten `working_time`. Unter der Woche ist Zeit knapper als am
Wochenende, der Samstagabend darf aufwendig sein.

**Was kein Hauptgericht ist.** Rezepte mit `Beilage`, `Nachtisch`, `Süß`, `Soßen` oder
`Basisrezepte` sind Bausteine, keine Mahlzeit. Eine Beilage darf als zusätzlicher Eintrag neben ein
Hauptgericht, etwa Ofenkartoffeln zu Tofu-Nuggets, aber nie allein auf einem Platz stehen.

**Ein paar Rezepte tragen gar keine Schlagworte.** Urteile dort nach Name und `description`.

**Der Froster.** Es wird in großen Mengen vorgekocht und portioniert eingefroren, zurzeit nur
Bolognese. Diese Portionen sind für Wochenenden gedacht, an denen zwei volle Gerichte nicht zu
schaffen sind. Was wirklich im Froster liegt, weiß das Bündel nicht. Schlag eine Frosterportion
deshalb nur vor, wenn Leo von sich aus sagt, dass die Woche eng wird, und schreib es in die `note`.

## Das Schema

`vorschlag/<woche>.json`:

```json
{
  "week": "2026-W39",
  "entries": [
    {
      "recipe_id": 11,
      "recipe_name": "Lasagne vegetarisch",
      "meal_type_id": 1,
      "from_date": "2026-09-21",
      "to_date": "2026-09-25",
      "servings": 5,
      "note": ""
    }
  ]
}
```

`meal_type_id` steht im Bündel unter `meal_types`, üblicherweise 1 für Mittagessen und 2 für
Abendessen. Die Daten sind reine Tage ohne Uhrzeit, die Uhrzeit setzt später `plan apply` aus der
Mahlzeit ein. `recipe_name` muss genau der Name aus dem Bündel sein, er ist die Sicherung gegen
eine vertauschte ID. `note` darf leer bleiben.

## Was geprüft wird

`plan check` prüft, ob es das Rezept und die Mahlzeit gibt, ob Name und ID zusammenpassen, ob der
Zeitraum in der Woche liegt, ob ein belegter Platz überschrieben würde und ob an jedem Tag für
beide Mahlzeiten mindestens zwei Portionen eingeplant sind.

Alles andere prüfst du selbst, bevor du Leo den Plan zeigst: vegetarisch, Eiweiß, die Mischung aus
Reis und Nudeln, die Abwechslung gegen die Historie und der Aufwand an den Kochtagen.

## Wenn Leo etwas ändern will

Der Vorschlag ist eine Datei und kein Ergebnis. Einwände sind der Normalfall, nicht das Zeichen,
dass die Wahl misslungen war.

- **Ändere nur, was gemeint ist.** Ein Einwand gegen den Mittwochabend ist kein Auftrag, die Woche
  neu zu würfeln. Alles andere bleibt stehen
- **Samstagabend und Sonntagmittag hängen zusammen.** Wird eines der beiden getauscht, tausch das
  andere mit, sonst wird am Samstag für einen Mittag gekocht, den es nicht mehr gibt
- **Die beiden Mittagsgerichte sind ein Paar.** Fällt eines weg, muss der Ersatz die Trennung von
  Reis und Nudeln und das Eiweiß wieder tragen
- **Lass `plan check` nach jeder Änderung laufen**, auch nach einer kleinen. Eine verschobene
  Portionszahl kippt die Deckung eines Tages, ohne dass man es sieht
- **Zeig danach nur die geänderten Zeilen**, nicht die ganze Tabelle, außer Leo will sie sehen

Sagt Leo, so passe es: Der Plan steht in `vorschlag/<woche>.json` und muss von Hand in Tandoor
eingetragen werden, solange es `plan apply` nicht gibt. Sag das dazu, statt es zu verschweigen.
