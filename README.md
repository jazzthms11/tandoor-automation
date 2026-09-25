# tandoor-automation

Wochenplan und Lebensmittelbestand in [Tandoor](https://tandoor.dev) automatisieren.

## Was es tut

Tandoor kann Wochenplan zu Einkaufsliste. Was fehlt, ist der Plan selbst und der Abgleich mit
dem, was zu Hause steht. Genau diese beiden Lücken füllt dieses Projekt.

1. **Wochenplaner**: holt Rezepte und Planhistorie, dampft sie auf die planungsrelevanten Felder
   ein, lässt ein Modell die Gerichte wählen, prüft das Ergebnis und schreibt es als Planeinträge
   zurück
2. **Bestand** (im Bau): Kassenbons füllen den Bestand, der Abgang wird beim Schreiben der
   Einkaufsliste bestätigt statt gemessen, und die Liste rechnet gegen den Bestand

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
uv run plan clear --dry-run                   # zeigen, was aus der kommenden Woche fiele
uv run plan clear --week 2026-W40             # die eigenen Einträge der Woche löschen
uv run plan clear --eintrag 181               # nur diesen Eintrag löschen
```

Zwischen `bundle` und `check` sitzt der Wähler: im Gespräch Claude über den Skill unter
`.claude/skills/wochenplan/`, später ein unbeaufsichtigter Lauf. Beide gehen durch dieselbe
Prüfung.

`apply` holt den Stand frisch aus Tandoor und legt nur an, was dort noch fehlt. Ein zweiter Lauf
über denselben Vorschlag schreibt deshalb nichts doppelt. `--dry-run` zeigt, was er tun würde.

`clear` ist der Rückweg und löscht nur, was unter dem eigenen Token angelegt wurde: die Instanz ist
geteilt, der Platz eines Mitessers bleibt stehen und wird genannt. Maßgeblich ist der erste Tag
eines Eintrags, ein Abendessen für zwei Abende darf also über den Freitag hinausragen. Die IDs
stehen in der Ausgabe von `plan clear --dry-run`.

## Kassenbons

```bash
uv run bon fetch --dry-run   # zeigen, welche Bons fehlen
uv run bon fetch             # fehlende Bons holen, unverändert nach bons/lidl/
```

Der Ordner ist zugleich der Stand: was dort liegt, wird nicht noch einmal geholt. Abgelegt wird
die Antwort der API unverändert, denn was ein Bon für den Bestand hergibt, entscheidet erst die
Zuordnung, und ein Fehler dort soll keinen neuen Abruf kosten.

### Zugang zu Lidl Plus

Die App-API hängt an einem Refresh-Token. Ihn holt ein einmaliger Anmeldelauf:

```bash
uv run bon login
```

Der Befehl gibt die Adresse des Anmeldebildschirms aus. Sie gehört Lidl, Benutzername und
Passwort gehen also nirgendwo anders hin. Nach der Anmeldung leitet Lidl auf
`com.lidlplus.app://callback?code=...` weiter, eine Adresse für die App, die kein Browser öffnen
kann. Genau sie wird gebraucht.

Am sichersten zu finden ist sie in den Entwicklerwerkzeugen: vor der Anmeldung F12 drücken, Tab
*Netzwerkanalyse*, *Log beibehalten* anhaken, nach der Anmeldung die Zeile mit `callback?code=`
kopieren. Oft steht sie auch einfach in der Adresszeile.

Der Token landet in `.lidl-token` und wird dort bei jedem Erneuern überschrieben. Läuft er
irgendwann ab, stellt derselbe Befehl den Zugang wieder her.

### Zuordnung der Bonnamen

Lidl druckt `Gehackte Tomaten`, Tandoor führt `Stückige Tomaten (Konserve)`. Dass beides dasselbe
meint, ist keine Ableitung, sondern eine Entscheidung. Sie steht in `zuordnung.tsv`, eine Zeile je
Bonname.

```bash
uv run bon map             # Datei auf den Stand der Bons bringen und gegen Tandoor prüfen
uv run bon map --katalog   # die Lebensmittel aus Tandoor ausgeben, als Vorlage zum Zuordnen
```

Von Hand kommt allein die erste Spalte: eine ID, oder `-` für alles, was es in Tandoor nicht gibt.
Angelegt wird nie etwas. Die übrigen Spalten schreibt der Befehl, sie zeigen beim Durchsehen,
wohin eine ID führt und wie oft der Name vorkommt.

Eine leere erste Spalte heißt, dass noch nicht entschieden wurde. Neue Artikel landen bei jedem
Lauf so in der Datei.

Die Klasse steht hier nicht. Zugeordnet wird auch, was nie in den Bestand kommt; was davon geführt
wird, entscheidet `klassen.tsv`. Das `-` heißt deshalb nie "führt keinen Bestand".

### Zugänge in den Bestand

```bash
uv run bon apply --seit 2026-09-01 --dry-run   # zeigen, was gebucht würde
uv run bon apply --seit 2026-09-01             # buchen
```

Gebucht wird nur, was einen Abgangsweg hat, also die Klassen `rezept` und `vorrat` aus
`klassen.tsv`. Der Ort kommt aus derselben Zeile. Mehrere Positionen desselben Lebensmittels
werden addiert, auch über Bons hinweg, und auf einen vorhandenen Eintrag aufgeschlagen statt
danebengelegt. Zusammengeführt wird über Lebensmittel und Einheit, nicht über den Ort: ein
Eintrag, der woanders steht, ist umgeräumt worden, und dann gewinnt der echte Schrank.

`--seit` grenzt ab, was noch im Haus steht. Beim ersten Lauf ist die Angabe nötig, sonst liefen
alle 245 Bons in den Bestand. Ältere Bons gelten danach als abgehandelt und kommen nicht wieder.

Welche Bons gebucht sind, steht in `bons/.importiert`. Anders als beim Holen trägt die Ablage das
nicht: ein gebuchter Bon sieht aus wie ein ungebuchter, und ein zweiter Lauf würde die Mengen
verdoppeln.

Ein Artikelname ohne Entscheidung in `zuordnung.tsv` hält den Lauf an. Ein stiller Bestandsverlust
fällt erst vor dem leeren Schrank auf, ein abgebrochener Lauf sofort.

## Bewertung

`bewertung.tsv` trägt je Rezept eine Note von 0 bis 5. Sie misst nicht Geschmack, sondern wie oft
ein Gericht darf: 5 geht quasi immer, 3 nur wenn es lange her ist, 1 nie, 0 heißt unbewertet.

Tandoor hat dafür kein eigenes Feld, es mittelt die Noten im Kochprotokoll. `plan rate` hält
deshalb genau einen Eintrag je Rezept vor und ändert ihn, statt einen zweiten anzulegen. Die Datei
ist die Quelle: wer in Tandoors Oberfläche bewertet, verzieht den Durchschnitt.
