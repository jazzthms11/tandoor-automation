# tandoor-automation

Automatisiert die Kette Wochenplan, Einkaufsliste, Lebensmittelbestand gegen die API von
Tandoor. Das Vorhaben und seine Begründungen stehen im Vault unter
`02 Projekte/Inventarverwaltung Lebensmittel (Tandoor).md`.

## Aufbau

- **Etappe 1 ist der Wochenplaner.** Holen, Projizieren, Prüfen und Schreiben stehen im Code,
  die Wahl der Gerichte macht ein Modell
- **Zwei Einstiegspunkte:** `plan bundle` gibt das Kontextbündel aus, `plan apply` validiert und
  schreibt nach `/api/meal-plan/`. Dazwischen sitzt der Wähler, im Gespräch Claude über den Skill
  unter `.claude/skills/`, im späteren Cron-Lauf Gemini
- **Regeln, die prüfbar sind, prüft der Code.** Das Modell entscheidet nur, was zusammenpasst
- **Etappe 2 ist der Bestand**, erst danach und nicht parallel

## Tests

**Sehr sparsam.** Nur dort, wo ein Fehler still bleibt und teuer wird, also vor allem bei der
Validierung vor dem Schreiben nach Tandoor und bei der Mengenrechnung. Nicht jede Funktion
braucht einen Test, und kein Test wird für Abdeckung geschrieben.

Das ist ein privates Projekt ohne Nutzer außer mir. Fehler fallen im Gebrauch auf, und ein
kaputter Wochenplan kostet zwei Klicks in Tandoors Oberfläche.

## Werkzeuge

`uv`, `ruff`, `ty`, `pytest`, Laufzeit 3.13. Details in `~/.claude/rules/python.md`.
