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

### Im Container

Auf dem Server läuft dieselbe CLI als Image, gebaut aus dem Klon unter
`/srv/config/tandoor-automation`. Die `.env` liegt daneben und kommt nie ins Image.

```bash
git pull
docker compose build
docker compose run --rm app plan bundle
docker compose run --rm app plan shop --dry-run
```

Jeder Befehl startet einen Container und räumt ihn danach weg. Gearbeitet wird im Klon selbst:
die TSV-Dateien kommen aus Git, `bundle/`, `vorschlag/`, `bons/` und `.lidl-token` liegen
daneben. `TZ=Europe/Berlin` setzt die Compose-Datei, sonst stünden die Planeinträge zwei Stunden
daneben. In `user:` steht die eigene ID auf dem Server, nachzusehen mit `id`.

Bons werden nur an einer Stelle gebucht, solange `bons/.importiert` eine Datei ist. Laptop und
Server führen sonst je eine eigene Liste, und ein Bon landet zweimal im Bestand.

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
Prüfung und wählen nach denselben Regeln: sie stehen in `src/tandoor_automation/regeln/wochenplan.md`,
der Skill trägt nur den Ablauf im Gespräch.

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

### Kaufland

Kaufland gibt nichts her, was sich abholen ließe: keine öffentliche API, und der Host der digitalen
Bons ist certificate-pinned. Der Beleg kommt deshalb von Hand, als PDF aus der App geteilt, und
wird eingeworfen:

```bash
uv run bon import-pdf ~/Downloads/beleg.pdf --dry-run   # zeigen, was abgelegt würde
uv run bon import-pdf ~/Downloads/beleg.pdf             # ablegen nach bons/kaufland/
```

Die Datei wird kopiert, nicht verschoben, und liegt danach unter ihrer Bonnummer. Ein Beleg, der
schon vorliegt, wird genannt und nicht überschrieben. Gelesen wird die Textebene über `pdftotext`
aus poppler-utils; ein Beleg von vor Juli 2024 ist ein Bild ohne Textebene und geht nicht.

Anders als bei Lidl kann beim Lesen einer Textspalte eine Zeile stillschweigend durchfallen. Der
Parser rechnet deshalb die Positionen samt Rabatten gegen die gedruckte Summe und verweigert den
Beleg, wenn beides nicht aufgeht.

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
Bonname, über beide Läden hinweg: `Soja Schnetzel` bei Lidl und `Soja Granulat` bei Kaufland zeigen
auf dasselbe Lebensmittel und werden im Bestand addiert.

```bash
uv run bon map             # Datei auf den Stand der Bons bringen und gegen Tandoor prüfen
uv run bon map --katalog   # die Lebensmittel aus Tandoor ausgeben, als Vorlage zum Zuordnen
```

Von Hand kommen die ersten zwei Spalten. Die erste trägt eine ID oder `-` für alles, was es in
Tandoor nicht gibt; angelegt wird nie etwas. Leer heißt, dass noch nicht entschieden wurde, und so
landen neue Artikel bei jedem Lauf in der Datei. Die übrigen Spalten schreibt der Befehl, sie
zeigen beim Durchsehen, wohin eine ID führt und wie oft der Name vorkommt.

Die zweite Spalte ist der Laden und bleibt fast immer leer: derselbe Name meint fast überall
dasselbe, und eine Zeile je Laden wäre für fast alle Namen Rauschen. Steht dort ein Laden, gilt die
Zeile nur für ihn und sticht die Zeile ohne Laden.

```
id     laden     bonname          lebensmittel     anzahl
426              Soja Schnetzel   Sojagranulat     3
623    kaufland  Soja Schnetzel   Sojaschnetzel    1
```

Lidl druckt `Soja Schnetzel` für das feine Granulat, Kaufland für das grobe Geschnetzelte und
führt das Granulat daneben als eigenen Artikel. Ohne die Ladenzeile wäre eines von beiden falsch
gebucht, und zwar stumm.

Damit dieser Fall auffällt, nennt `bon map` jeden Namen, dessen eine Entscheidung für mehr als
einen Laden gilt:

```
Soja Schnetzel: steht bei kaufland, lidl und ist einmal entschieden
```

Die Meldung verschwindet, sobald eine Ladenzeile dasteht. Ob ein Name überall dasselbe meint, weiß
nur der Einkauf, nicht der Code; die Meldung sagt bloß, wo hinzusehen ist. Eine Ladenzeile, deren
Name in diesem Laden nie vorkommt, meldet `bon map` umgekehrt als Ballast.

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

`--seit` grenzt ab, was noch im Haus steht. Beim ersten Lauf ist die Angabe nötig, sonst liefe
die ganze Historie in den Bestand. Ältere Bons gelten danach als abgehandelt und kommen nicht wieder.

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

## Nährwerte

Tandoor rechnet die Nährwerte eines Rezepts selbst, aus den Eigenschaften seiner Lebensmittel. Vier
Typen kommen aus dem Open Data Projekt, Zucker und Ballaststoffe fehlen dort und werden einmalig
nachgetragen:

```bash
uv run python naehrwerte.py --dry-run   # zeigen, was geschrieben würde
uv run python naehrwerte.py             # Typen anlegen und Werte schreiben
```

Drei Quellen. Die Lebensmittel mit `fdc_id` holt das Skript aus der FDC-Datenbank des USDA, dafür
braucht es einen Schlüssel von [api.data.gov](https://fdc.nal.usda.gov/api-key-signup) in der
`.env`. Die ohne Nummer stehen in `naehrwerte.tsv`, von Hand. Und die Lebensmittel, die selbst ein
Rezept sind, rechnet das Skript aus ihrer Rezeptsumme; das muss zuletzt laufen.

FDC führt Zucker in vielen Datensätzen nicht, in Foundation-Daten außerdem unter einer anderen
Nummer als sonst. Was unvollständig zurückkommt, schreibt das Skript nicht als 0, sondern nennt es
als fertige Zeile für `naehrwerte.tsv` und hält an. Der Lauf ist deshalb einer je Durchsicht, und
wiederholbar: geschrieben wird immer die vollständige Eigenschaftsliste.

Tandoors eigener FDC-Knopf am Lebensmittel taugt dafür nicht. Er überschreibt die vier vorhandenen
Werte mit, setzt die Basis hart auf 100 g und kennt nur die eine Zuckernummer.

Ein Lebensmittel ohne Wert hält nicht nur sich selbst auf: Tandoor meldet das ganze Rezept als
unvollständig. Am Ende des Laufs wird deshalb jedes Rezept nachgerechnet.
