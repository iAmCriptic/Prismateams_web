---
trigger: always_on
description: Verbindliche UI- und Styling-Vorgaben aus STYLEGUIDE.md fuer HTML, CSS, Templates und UI-Komponenten.
---

## UI & Frontend Styleguide Direktive

Beachte bei allen Anpassungen an HTML, CSS, Templates oder UI-Komponenten ausnahmslos die Vorgaben in `STYLEGUIDE.md`. Führe keine neuen Farben oder uneinheitlichen Bootstrap-Muster ein, die nicht im Styleguide definiert sind.

### Kernregeln im Überblick:
- **Styleguide als Single Source of Truth:** Vor jeder Änderung an Templates (`app/templates/`), CSS (`app/static/css/`) oder UI-Komponenten ist `STYLEGUIDE.md` zu konsultieren und strikt zu befolgen.
- **Pill-Design & Modul-Shell:** Neue Seiten und Modul-Views basieren immer auf der Modul-Shell (`{modul}-shell mod-shell--nav`) mit `.mod-sidebar` und mobiler Offcanvas-Navigation.
- **Shared UI Element-Packs:** Verwende ausschließlich die kanonischen Shared-Klassen (`.mod-pill-btn*`, `.mod-search*`, `.mod-view-toggle*`, `.mod-toolbar*`, `.mod-pill-input`, `.mod-bulk-*`, `.mod-list-*`). Führe keine modulspezifischen Präfixe wie `*-pill-btn` oder `*-search` ein.
- **Farben & Tokens:** Keine neuen Farbdefinitionen oder willkürlichen Farbwerte. `#0d6efd` niemals hardcodieren, sondern `var(--accent-color, var(--bs-primary))` bzw. `var(--accent-style)` nutzen.
- **Keine willkürlichen Inline-Styles:** `style="..."` ist nur für dynamische Server-Werte (z. B. Ordnerfarben, Prozentbreiten von Ladebalken) erlaubt.
- **Modals außerhalb der Shell:** Alle Bootstrap-Modals müssen im Template außerhalb von `.mod-shell--nav` liegen, um Z-Index-Stacking-Konflikte mit dem Backdrop zu vermeiden.
- **CI-Guardrails ausführen:** Nach CSS- oder Template-Änderungen stets `python scripts/qa_css_design_guardrails.py` ausführen.
