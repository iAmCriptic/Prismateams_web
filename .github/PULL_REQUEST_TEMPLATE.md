## Beschreibung

<!-- Kurze Zusammenfassung der Änderungen und Motivation -->

## Art der Änderung

- [ ] Bugfix
- [ ] Neues Feature
- [ ] Refactoring / Wartung
- [ ] Dokumentation / CI

## Checkliste vor dem Merge

- [ ] `pytest` läuft lokal fehlerfrei
- [ ] `python scripts/qa_css_design_guardrails.py` läuft fehlerfrei (bei UI-/CSS-/Template-Änderungen)
- [ ] Neue Übersetzungskeys in `app/translations/de.json` und `app/translations/en.json` ergänzt (falls UI geändert)
- [ ] Datenbank-Migrationen geprüft (falls Modelle geändert)
- [ ] Keine Secrets, `.env`-Dateien oder temporären Debug-Dateien enthalten
