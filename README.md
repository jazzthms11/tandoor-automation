# tandoor-automation

Wochenplan und Lebensmittelbestand in [Tandoor](https://tandoor.dev) automatisieren.

## Was es tut

Tandoor kann Wochenplan zu Einkaufsliste. Was fehlt, ist der Plan selbst und der Abgleich mit
dem, was zu Hause steht. Genau diese beiden Lücken füllt dieses Projekt.

1. **Wochenplaner**: holt Rezepte und Planhistorie, dampft sie auf die planungsrelevanten Felder
   ein, lässt ein Modell die Gerichte wählen, prüft das Ergebnis und schreibt es als Planeinträge
   zurück
2. **Bestand** (später): Kassenbons aus der Lidl-Plus-App füllen die Pantry, der Verbrauch geht
   über den Wochenplan oder einen Barcode-Scan ab, und die Einkaufsliste rechnet gegen den Bestand

## Einrichtung

```bash
uv sync
cp .env.example .env   # Tandoor-Token eintragen
```

Ein Token wird in Tandoor unter *Einstellungen, API* erzeugt.

## Wochenplan

```bash
uv run plan bundle                            # Kontextbündel der kommenden Woche
uv run plan check vorschlag/2026-W39.json     # Vorschlag gegen das Bündel prüfen
uv run plan apply vorschlag/2026-W39.json     # prüfen und nach Tandoor schreiben
uv run plan rate                              # Grundbewertung aus bewertung.tsv abgleichen
```

Zwischen `bundle` und `check` sitzt der Wähler: im Gespräch Claude über den Skill unter
`.claude/skills/wochenplan/`, später ein unbeaufsichtigter Lauf. Beide gehen durch dieselbe
Prüfung.

`apply` holt den Stand frisch aus Tandoor und legt nur an, was dort noch fehlt. Ein zweiter Lauf
über denselben Vorschlag schreibt deshalb nichts doppelt. `--dry-run` zeigt, was er tun würde.

## Bewertung

`bewertung.tsv` trägt je Rezept eine Note von 0 bis 5. Sie misst nicht Geschmack, sondern wie oft
ein Gericht darf: 5 geht quasi immer, 3 nur wenn es lange her ist, 1 nie, 0 heißt unbewertet.

Tandoor hat dafür kein eigenes Feld, es mittelt die Noten im Kochprotokoll. `plan rate` hält
deshalb genau einen Eintrag je Rezept vor und ändert ihn, statt einen zweiten anzulegen. Die Datei
ist die Quelle: wer in Tandoors Oberfläche bewertet, verzieht den Durchschnitt.
