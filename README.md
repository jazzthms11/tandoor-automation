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

Jeder Befehl startet einen Container und räumt ihn danach weg. Gearbeitet wird im Klon selbst,
dort landen `bundle/`, `vorschlag/` und die Exporte der Tabellen. Alles Veränderliche liegt
außerhalb davon unter `/srv/data/tandoor-automation`, im Container `/data`: die Datenbank, die
Rohbons unter `bons/` und der Zugang zu Lidl. Der Ordner gehört dem Nutzer aus `user:`, sonst
kann der Container dort nicht schreiben:

```bash
sudo mkdir -p /srv/data/tandoor-automation
sudo chown 1000:1000 /srv/data/tandoor-automation
```

`TZ=Europe/Berlin` setzt die Compose-Datei, sonst stünden die Planeinträge zwei Stunden daneben.
In `user:` steht die eigene ID auf dem Server, nachzusehen mit `id`.

### Oberfläche

Neben der CLI läuft auf dem Server eine Oberfläche im Browser, aus demselben Image:

```bash
docker compose up -d          # startet den Dienst web, nach einem Neustart von selbst wieder
docker compose ps             # zeigt, ob er läuft und healthy ist
docker compose logs -f web    # was er tut
```

Erreichbar unter `http://leosserver:8095`, nur im Heimnetz und über WireGuard. Ein Login gibt es
nicht, abgesichert ist sie über den Netzweg. Einen anderen Port setzt `WEB_PORT` in der `.env`.

| Seite | ersetzt | was sie tut |
|---|---|---|
| Wochenplan | `plan clear` | Einträge einer Woche, eigene zum Auswählen und Zurücknehmen |
| Einkauf | `plan shop` | Bestandsfragen nach Ort als Knöpfe, Vorschau, dann buchen und Liste schreiben |
| Bewertung | `plan rate` | alle Rezepte mit Sternen, ein Klick schreibt sofort nach Tandoor |
Nach `git pull` holen `docker compose build` und `docker compose up -d` die neue Fassung.

Gebaut ist sie mit FastAPI, Jinja2 und htmx: der Server liefert fertiges HTML, ein Klick tauscht
nur den Teil der Seite, der sich ändert. htmx und Pico CSS liegen unter `web/static/` im Paket,
ohne CDN und ohne Build-Schritt. Lokal startet sie mit:

```bash
uv run uvicorn tandoor_automation.web.app:app --reload
```

Die Datenbank auf dem Server ist die einzige. `plan shop`, `plan rate` und alles unter `bon`
laufen deshalb dort: auf dem Laptop legte jeder Befehl eine eigene, leere Datenbank unter `data/`
an. Was nur Tandoor braucht, also `plan bundle`, `check`, `apply` und `clear`, geht weiter überall.

### Eigene Tabellen

Was Tandoor nicht kennt, steht in SQLite: Grundbewertung, Klassen, Ausnahmen, Intervalle, die
Zuordnung der Bonnamen und welche Bons gebucht sind. Die Bewertung hat eine Seite in der
Oberfläche, für den Rest ist die TSV-Datei der Weg zum Ändern, bis auch er eine hat:

```bash
plan data export klassen          # schreibt klassen.tsv in den aktuellen Ordner
plan data import klassen          # liest sie zurück, die Datei ersetzt die Tabelle
plan data import --dry-run        # zählt nur, was sich änderte
plan data backup                  # Kopie nach backup/ im Datenordner, sicher auch im Betrieb
```

Eine Zeile, die in der Datei fehlt, wird gelöscht. Ausgenommen ist `importiert`, der Stand der
Bons: dort kommt nur dazu, ein vergessener Eintrag würde einen Bon doppelt buchen. Ein Export
überschreibt keine Datei, die noch nicht Eingelesenes trägt. Die Zuordnung geht nicht über
`export`, sondern über `bon map`, weil ihre Lesehilfe Tandoor und die Bons braucht.

Neue Spalten oder Tabellen kommen über Alembic, angewendet beim ersten Zugriff:

```bash
uv run alembic revision --autogenerate -m "was sich ändert"
```

Die Datenbank darf restic nicht mitten im Schreiben greifen. `backup.sh` ruft deshalb vor dem
Sichern `docker compose run --rm app plan data backup` auf, die Kopie liegt unter `/srv` mit.

### Umzug aus den TSV-Dateien

Bis M2 lagen die Tabellen als TSV-Dateien im Repo und der Laufzustand daneben. Der neueste Stand
von beidem liegt auf dem Laptop, und `git pull` nimmt die TSV-Dateien mit. Einmalig, in dieser
Reihenfolge:

```bash
# Server: Datenordner anlegen
sudo mkdir -p /srv/data/tandoor-automation/umzug
sudo chown -R 1000:1000 /srv/data/tandoor-automation

# Laptop, im Klon und vor dem nächsten git pull
scp bewertung.tsv klassen.tsv ausnahmen.tsv intervalle.tsv zuordnung.tsv \
    leosserver:/srv/data/tandoor-automation/umzug/
scp -r bons leosserver:/srv/data/tandoor-automation/
scp .lidl-token leosserver:/srv/data/tandoor-automation/lidl-token

# Server, im Klon
D=/srv/data/tandoor-automation
mv $D/bons/.importiert $D/umzug/importiert.txt
git pull && docker compose build
docker compose run --rm app plan data import --ordner /data/umzug
rm -r $D/umzug
```

Fehlt `bons/.importiert` auf dem Laptop, war dort nie etwas gebucht, dann entfällt das `mv`.

## Wochenplan

```bash
uv run plan bundle                            # Kontextbündel der kommenden Woche
uv run plan check vorschlag/2026-W39.json     # Vorschlag gegen das Bündel prüfen
uv run plan apply vorschlag/2026-W39.json     # prüfen und nach Tandoor schreiben
uv run plan rate                              # Grundbewertung aus der Datenbank abgleichen
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
stehen in der Ausgabe von `plan clear --dry-run`. In der Oberfläche ist das die Seite *Wochenplan*,
dort werden die Einträge angehakt statt per ID genannt.

## Kassenbons

```bash
uv run bon fetch --dry-run   # zeigen, welche Bons fehlen
uv run bon fetch             # fehlende Bons holen, unverändert nach bons/lidl/ im Datenordner
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

Der Token landet in `lidl-token` im Datenordner und wird dort bei jedem Erneuern überschrieben. Läuft er
irgendwann ab, stellt derselbe Befehl den Zugang wieder her.

### Zuordnung der Bonnamen

Lidl druckt `Gehackte Tomaten`, Tandoor führt `Stückige Tomaten (Konserve)`. Dass beides dasselbe
meint, ist keine Ableitung, sondern eine Entscheidung. Sie steht in der Tabelle `zuordnung`, eine
Zeile je Bonname, über beide Läden hinweg: `Soja Schnetzel` bei Lidl und `Soja Granulat` bei Kaufland zeigen
auf dasselbe Lebensmittel und werden im Bestand addiert.

```bash
uv run bon map                      # neue Namen aufnehmen, zuordnung.tsv schreiben, prüfen
uv run plan data import zuordnung   # die Entscheidungen aus der Datei einlesen
uv run bon map --katalog            # die Lebensmittel aus Tandoor, als Vorlage zum Zuordnen
```

Von Hand kommen die ersten zwei Spalten. Die erste trägt eine ID oder `-` für alles, was es in
Tandoor nicht gibt; angelegt wird nie etwas. Leer heißt, dass noch nicht entschieden wurde, und so
landen neue Artikel bei jedem Lauf in der Tabelle. Die übrigen Spalten schreibt der Befehl, sie
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
wird, entscheidet die Tabelle `klassen`. Das `-` heißt deshalb nie "führt keinen Bestand".

### Zugänge in den Bestand

```bash
uv run bon apply --seit 2026-09-01 --dry-run   # zeigen, was gebucht würde
uv run bon apply --seit 2026-09-01             # buchen
```

Gebucht wird nur, was einen Abgangsweg hat, also die Klassen `rezept` und `vorrat` aus der
Tabelle `klassen`. Der Ort kommt aus derselben Zeile. Mehrere Positionen desselben Lebensmittels
werden addiert, auch über Bons hinweg, und auf einen vorhandenen Eintrag aufgeschlagen statt
danebengelegt. Zusammengeführt wird über Lebensmittel und Einheit, nicht über den Ort: ein
Eintrag, der woanders steht, ist umgeräumt worden, und dann gewinnt der echte Schrank.

`--seit` grenzt ab, was noch im Haus steht. Beim ersten Lauf ist die Angabe nötig, sonst liefe
die ganze Historie in den Bestand. Ältere Bons gelten danach als abgehandelt und kommen nicht wieder.

Welche Bons gebucht sind, steht in der Tabelle `importiert`. Anders als beim Holen trägt die Ablage das
nicht: ein gebuchter Bon sieht aus wie ein ungebuchter, und ein zweiter Lauf würde die Mengen
verdoppeln.

Ein Artikelname ohne Entscheidung in der Zuordnung hält den Lauf an. Ein stiller Bestandsverlust
fällt erst vor dem leeren Schrank auf, ein abgebrochener Lauf sofort.

## Bewertung

Die Tabelle `bewertung` trägt je Rezept eine Note von 0 bis 5. Sie misst nicht Geschmack, sondern wie oft
ein Gericht darf: 5 geht quasi immer, 3 nur wenn es lange her ist, 1 nie, 0 heißt unbewertet.

Tandoor hat dafür kein eigenes Feld, es mittelt die Noten im Kochprotokoll. `plan rate` hält
deshalb genau einen Eintrag je Rezept vor und ändert ihn, statt einen zweiten anzulegen. Die Tabelle
ist die Quelle: wer in Tandoors Oberfläche bewertet, verzieht den Durchschnitt.

Bewertet wird auf der Seite *Bewertung* der Oberfläche. Ein Klick auf einen Stern speichert in der
Datenbank und schreibt sofort nach Tandoor, der gesetzte Stern nochmal nimmt die Note zurück. War
Tandoor gerade nicht erreichbar, holt *Mit Tandoor abgleichen* das nach, wie `plan rate`.

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
