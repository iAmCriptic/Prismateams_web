# Agent Instructions — Prismateams

## Frontend & UI Styling Directive

> **Verbindliche Vorgabe:**
> Beachte bei allen Anpassungen an HTML, CSS, Templates oder UI-Komponenten ausnahmslos die Vorgaben in `STYLEGUIDE.md`. Führe keine neuen Farben oder uneinheitlichen Bootstrap-Muster ein, die nicht im Styleguide definiert sind.

### Wichtigste Grundsätze für alle Änderungen am Frontend:
1. **Styleguide als Referenz:** Vor Arbeiten an `app/templates/`, `app/static/css/` oder JS-UI-Komponenten immer die [STYLEGUIDE.md](STYLEGUIDE.md) als Referenz hinzuziehen.
2. **Modul-Shell (`mod-shell--nav`):** Neue Modulseiten müssen dem Shell-Muster mit `.mod-sidebar` und mobiler Offcanvas-Sidebar folgen.
3. **Pill-Design & Shared Packs:** Einheitliche Klassen nutzen (`.mod-pill-btn`, `.mod-search`, `.mod-view-toggle`, `.mod-toolbar`, `.mod-pill-input`). Keine neuen modulspezifischen Präfixe (`files-pill-btn`, `*-search` etc.).
4. **Farb-Tokens:** Immer `var(--accent-color, var(--bs-primary))` bzw. `var(--accent-style)` verwenden; niemals `#0d6efd` direkt schreiben.
5. **Keine willkürlichen Inline-Styles:** `style="..."` ausschließlich für dynamische Server-Werte (z. B. `folder.color` oder Progressbars).
6. **Modals außerhalb der Shell:** Modals stets außerhalb von `.mod-shell--nav` platzieren, um Z-Index-Konflikte mit dem Backdrop zu vermeiden.
7. **CI-Überprüfung:** Änderungen müssen `python scripts/qa_css_design_guardrails.py` fehlerfrei bestehen.
