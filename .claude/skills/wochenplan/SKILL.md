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
   samt Grundbewertung (`rating`)
3. Frag Leo in einer Nachricht, ob für die Woche etwas zu beachten ist, siehe *Hinweise zur
   Woche*. **Beende damit deinen Zug** und wähle erst nach der Antwort
4. Wähle die Gerichte und schreib `vorschlag/<woche>.json` nach dem Schema unten
5. `uv run plan check vorschlag/<woche>.json`. Bessere nach, bis der Befehl sauber durchläuft
6. Zeig Leo die Woche als Tabelle im Gespräch und sag in zwei, drei Zeilen, warum diese Gerichte.
   Hat Leo etwas zur Woche gesagt, nenn in einer Zeile, was du daraus gemacht hast
7. Erst wenn Leo zustimmt: `uv run plan apply vorschlag/<woche>.json` schreibt die Woche nach
   Tandoor. Von dir aus schreibst du **nicht**, der Vorschlag ist bis dahin nur eine Datei

## Der Haushalt

Zwei Personen. Eine Portion ist eine Mahlzeit für eine Person, `servings` an einem Eintrag ist
also die Zahl der gekochten Portionen, nicht die der Esser.

Geplant werden immer alle sieben Mittag- und alle sieben Abendessen. Gekocht wird an vier Tagen:
samstags ein Gericht für den Samstagabend und den Sonntagmittag, sonntags die Mittagessen der
Woche und das Abendessen, dienstags und donnerstags je ein Abendessen für zwei Abende.

**Die Woche läuft von Samstag bis Freitag.** Der Plan entsteht donnerstags, freitags wird
eingekauft, am Samstag fängt sie an. Der Einkauf steht damit am Anfang der Woche und nicht
mitten darin. Das Etikett bleibt die ISO-Woche des Montags, der in der Woche liegt: `2026-W40`
heißt Samstag, der 26. September, bis Freitag, der 2. Oktober.

## Die Form der Woche

In der Reihenfolge der Woche:

| Platz | Eintrag | Portionen |
| --- | --- | --- |
| Mittag Sa | Sa bis Sa, eine Kleinigkeit | 2 |
| Abend Sa | Sa bis Sa | 2 |
| Mittag So | So bis So, dasselbe Rezept wie Samstagabend | 2 |
| Abend So | So bis Mo | 4 |
| Mittag Mo bis Fr | zwei Einträge, beide Mo bis Fr | je 5 |
| Abend Di und Mi | Di bis Mi | 4 |
| Abend Do und Fr | Do bis Fr | 4 |

Zwei Dinge daran sind leicht zu übersehen:

- **Der Montagabend hat keinen eigenen Eintrag.** Er hängt am Sonntagsgericht, dessen `to_date`
  der Montag ist. Acht Einträge decken so vierzehn Plätze
- **Kein Eintrag reicht über die Ränder der Woche.** Der Samstag fängt frei an, weil der
  Donnerstag der Vorwoche nur bis zu ihrem Freitag reicht. Steht trotzdem etwas in `occupied`,
  ist es ein Termin oder ein Rest eines früheren Laufs, und du lässt es in Ruhe

Die beiden Mittagsgerichte laufen als je ein Eintrag über Mo bis Fr. Fünf Portionen auf fünf Tage
heißt: an jedem Tag isst eine Person das eine und die andere das andere Gericht, und über die
Woche wird abgewechselt. Deshalb zwei verschiedene Gerichte und nicht zehn Portionen von einem.

Samstagabend und Sonntagmittag sind dasselbe Gericht in zwei Einträgen, einmal mit 2 Portionen für
den Abend und einmal mit 2 für den Mittag. Gekocht wird beides am Samstag.

## Wie du wählst

**Die Bewertung sagt, was erlaubt ist, die Historie sagt, was dran ist.** Jedes Rezept trägt im
Bündel ein `rating` von 0 bis 5. Die Skala misst nicht Geschmack, sondern wie eng ein Gericht
wiederkommen darf:

| `rating` | Bedeutung | Frühestens wieder |
| --- | --- | --- |
| 5 | geht quasi immer | darf zwei Wochen hintereinander |
| 4 | sehr gut, aber nicht jede Woche | nach einer Woche Pause |
| 3 | kann man mal essen | nach mehreren Wochen, Richtwert vier |
| 2 | eigentlich nicht gut | nur wenn Leo es ausdrücklich will |
| 1 | nie | gar nicht, auch nicht als Lückenfüller |
| 0 | nicht bewertet | erlaubt, aber nenn es beim Vorschlagen, damit Leo nachbewerten kann |

**Eine 5 heißt nicht, dass das Gericht jede Woche drinstehen soll.** Sie hebt nur die Sperre auf.
Unter allen Gerichten, die nach der Tabelle dürfen, gewinnt das, was am längsten her ist. Eine 4,
die vier Wochen nicht dran war, schlägt eine 5 von letzter Woche. Sonst steht jede Woche Bolognese
auf dem Tisch, und das ist genau der Fehler, den die Bewertung nicht machen soll.

Die Note schlägt die übrigen Regeln nur nach unten: ein Gericht mit 1 kommt auch dann nicht auf
den Tisch, wenn es sonst perfekt in die Woche passt.

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

**Abwechslung.** Der Mindestabstand steht in der Bewertungstabelle, und unter den erlaubten
Gerichten kommt das an die Reihe, das am längsten her ist. Prüf das an `history`, nicht am Gefühl.
Kein Gericht zweimal in derselben Woche, ausgenommen das Paar Samstagabend und Sonntagmittag. Über
den ganzen Plan hinweg nicht dreimal dieselbe Küche.

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

Ein Platz, an dem nicht selbst gekocht wird, kommt ohne Rezept aus und trägt nur einen Titel. So
steht er später auch in Tandoor:

```json
{
  "title": "Besuch bei Anna",
  "meal_type_id": 2,
  "from_date": "2026-09-25",
  "to_date": "2026-09-25"
}
```

`meal_type_id` steht im Bündel unter `meal_types`, üblicherweise 1 für Mittagessen und 2 für
Abendessen. Die Daten sind reine Tage ohne Uhrzeit, die Uhrzeit setzt später `plan apply` aus der
Mahlzeit ein. `recipe_name` muss genau der Name aus dem Bündel sein, er ist die Sicherung gegen
eine vertauschte ID. `note` darf leer bleiben.

## Was `plan apply` daraus macht

Was in Tandoor steht, sieht anders aus als der Vorschlag, und das ist Absicht.

- **Die beiden Mittagsgerichte werden entfaltet**: aus zwei Einträgen über Montag bis Freitag
  werden zehn, einer je Tag und Esser zu einer Portion. Nur so steht im Plan, wer an welchem Tag
  welches der beiden Gerichte isst, und nur daraus lassen sich die Nährwerte eines Tages rechnen
- **`plan apply` fragt vorher**, welches der beiden Gerichte Leo dreimal isst. Fünf Tage gehen
  nicht glatt auf zwei Gerichte auf, und diese Antwort ist eine Entscheidung
- **Jedes Mittagessen mit Rezept trägt seine Esser** als `@leo` oder `@jazz` in der ersten Zeile
  seiner `note`. Deine `note` rutscht darunter und bleibt erhalten
- **Das Abendessen bekommt keine Marke.** Es essen alle, und SyncHealth teilt es auf die Esser im
  Haushalt auf. Eine Marke dort hieße, dass nur einer gegessen hat
- **Ein Eintrag ohne Rezept bekommt keine Marke.** An einem Termin wird gegessen, aber nicht aus
  der eigenen Küche

**Entfalte nicht selbst.** Der Vorschlag trägt die beiden Mittagsgerichte als je einen Eintrag
über die Arbeitswoche, wie in der Tabelle oben. Zehn fast gleiche Einträge von Hand zu schreiben
ist genau die Wiederholung, bei der ein Modell verrutscht, und die Marken setzt der Code.

In der `history` des Bündels stehen vergangene Mittagessen deshalb als Tageseinträge, ein Gericht
also mehrfach in derselben Woche. Für den Abstand zählt trotzdem die Woche, in der es stand, und
nicht die Zahl seiner Einträge.

## Was geprüft wird

`plan check` prüft, ob es das Rezept und die Mahlzeit gibt, ob Name und ID zusammenpassen, ob der
Zeitraum in der Woche liegt, ob ein belegter Platz überschrieben würde und ob an jedem Tag für
beide Mahlzeiten mindestens zwei Portionen eingeplant sind. Ein Eintrag ohne Rezept zählt dabei
als versorgt und braucht keine Portionen, muss aber einen Titel tragen.

`plan apply` prüft zusätzlich die Anteile der entfalteten Form: ein Eintrag muss so viele Portionen
am Tag tragen, wie Esser an ihm stehen, ohne Marke so viele, wie der Haushalt hat. Das trifft die beiden Mittagsgerichte über ungleiche
Zeiträume, etwa das eine von Montag bis Freitag und das andere bis Donnerstag. Sie decken die Woche,
bilden aber keinen geteilten Platz mehr, und jeder Anteil wäre still halbiert.

Alles andere prüfst du selbst, bevor du Leo den Plan zeigst: die Bewertung, vegetarisch, Eiweiß,
die Mischung aus Reis und Nudeln, die Abwechslung gegen die Historie und der Aufwand an den
Kochtagen.

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

Sagt Leo, so passe es, dann schreibt `uv run plan apply vorschlag/<woche>.json` die Woche nach
Tandoor. Der Befehl prüft noch einmal gegen den Stand, wie er jetzt in Tandoor ist, und legt nur
an, was dort noch fehlt. Ein zweiter Lauf schreibt deshalb nichts doppelt, und ein einzelner
nachgebesserter Eintrag lässt sich mit demselben Befehl nachschieben. `--dry-run` zeigt vorher, was
er tun würde und löscht die Datei nicht; die Frage nach der Aufteilung der Mittagessen stellt er
auch dann. Ohne `--dry-run` löscht `plan apply` die Vorschlagsdatei
nach dem Schreiben, Tandoor ist danach die einzige Wahrheit.

Was schon in Tandoor steht, ändert `plan apply` nicht. Soll ein bereits geschriebener Eintrag weg
oder anders aussehen, gehört das in Tandoors Oberfläche; sag Leo das, statt es zu umgehen.

## Hinweise zur Woche

Ein Hinweis kommt auf zwei Wegen: als Zusatz beim Aufruf, etwa `/wochenplan dieses Wochenende
wenig Zeit` oder `/wochenplan W41, Samstag Besuch`, oder als Antwort auf die Frage aus Schritt 3.
Er gilt vor den Regeln oben. Er beschreibt den Fall dieser Woche, und die Regeln beschreiben nur
den Normalfall.

Die Frage stellst du auch dann, wenn der Aufruf schon einen Hinweis trug, denn vergessen wird
gerade das, woran beim Aufruf niemand gedacht hat. Sie ist eine offene Frage im Gespräch, keine
Auswahl, und nennt Woche, Zeitraum und die schon belegten Plätze aus `occupied`:

> W41 (Sa 03.10. bis Fr 09.10.). In Tandoor steht schon: Mi Abend „Essen bei Eltern“.
> Muss ich etwas beachten? Etwa Mahlzeiten, die ausfallen (Wochenende weg, Besuch, auswärts),
> Gäste, Reste, die weg müssen, oder Wünsche.

Ist nichts belegt, fällt der Satz dazu weg. Ein „nein“ heißt Normalfall.

- **Eine Woche** (`W41`, `übernächste Woche`) → `plan bundle --week` entsprechend aufrufen
- **Wenig Zeit an einem Kochtag** → dort Rezepte mit kurzer `working_time`, und am Wochenende darf
  eine Frosterportion einspringen
- **Ein Wunschgericht** → fest einplanen und den Rest darum herum wählen, auch bei niedriger Note
- **Etwas muss weg**, Reste oder eine offene Packung → als `note` an den passenden Eintrag
- **Ein Platz fällt aus**, Besuch oder auswärts essen → trag einen Eintrag ohne Rezept ein, nur
  mit `title`, und stopf den Platz nicht mit einem Gericht, das niemand isst
- **Fallen Plätze aus, prüf die Gerichte, die über mehrere Plätze reichen.** Das Samstagsgericht
  trägt den Sonntagmittag, das Sonntagsgericht den Montagabend. Fällt das Wochenende weg, braucht
  der Montagabend einen eigenen Eintrag mit 2 Portionen, und die Mittagessen der Woche werden an
  einem anderen Tag vorgekocht. Sag Leo, wann

Widerspricht ein Hinweis einer Regel, folg dem Hinweis und sag in einem Satz, welche Regel dafür
weichen musste.

## Wenn Leo eine Bewertung ändern will

Die Noten stehen in `bewertung.tsv` im Repo, eine Zeile je Rezept, erste Spalte die Sterne. Die
Datei ist die Quelle, nicht Tandoor.

- **Ändere die Zeile in der Datei**, dann `uv run plan rate`. Der Befehl fasst den vorhandenen
  Eintrag im Kochprotokoll an, statt einen zweiten anzulegen
- **Nicht in Tandoors Oberfläche bewerten.** Tandoor mittelt die Noten eines Rezepts, statt die
  neueste zu nehmen → ein Klick dort verzieht die Note und die Datei stimmt nicht mehr
- **Eine Note auf 0 setzen löscht sie** in Tandoor, das Rezept gilt dann wieder als unbewertet
- **Ein neues Rezept fehlt in der Datei.** Häng eine Zeile an, Sterne und ID reichen, der Rest
  ist Gedächtnisstütze
