# Agent Instructions — Prismateams

## Frontend & UI Styling Directive

> **Verbindliche Vorgabe:**
> Beachte bei allen Anpassungen an HTML, CSS, Templates oder UI-Komponenten ausnahmslos die Vorgaben in `STYLEGUIDE.md`. Führe keine neuen Farben oder uneinheitlichen Bootstrap-Muster ein, die nicht im Styleguide definiert sind.

### Wichtigste Grundsätze für alle Änderungen am Frontend:
1. **Styleguide als Referenz:** Vor Arbeiten an `app/templates/`, `app/static/css/` oder JS-UI-Komponenten immer die [STYLEGUIDE.md](STYLEGUIDE.md) als Referenz hinzuziehen.
2. **Nie Light- oder Dark-Mode hardcoden:** Niemals statische Farben wie `#fff`, `#000` oder `#1a1a1a` vorgeben. Verwende immer CSS-Tokens (`var(--bs-body-bg)`, `var(--bs-body-color)`, `var(--portal-bg)` etc.), damit Light, Dark und OLED stets frei umschaltbar bleiben.
3. **Sprachen nie hardcoden (i18n):** Keine UI-Texte, Beschriftungen oder Platzhalter als Klartext im HTML/JS schreiben. Immer `{{ _('...') }}` in Jinja bzw. `data-i18n-*` verwenden (außer bei frei editierbaren Inhalten wie E-Mail-Vorlagen).
4. **Navbar-Suche & nahtlose Sidebar:** Jedes Modul besitzt oben eine Suchleiste in der Navbar (`{% block navbar_search %}`) und auf der linken Seite eine `.mod-sidebar`, die nahtlos ins Portaldesign übergeht.
5. **Zurück-Button:** Immer grau (`var(--bs-secondary-color, #6c757d)`), mit Pfeil nach links (`bi bi-arrow-left`) und Beschriftung „Zurück“ (`{{ _('layout.nav.back') }}`).
6. **Tabellen & Grid-Views:** Einheitliche Listen- und Kachelstrukturen nach dem Dateien-Muster:
   - Listenansicht: `.mod-list-table-wrap` mit `.table.mod-list-table` (niemals `display: flex` auf `<td>`).
   - Kachelansicht: `#gridView.row.g-3` mit `.mod-grid-preview` (Höhe 7.5rem) und Hover-Shortcuts.
   - Umschaltung: `.mod-view-toggle` mit Schiebe-Indikator.
   - Multi-Select: `.mod-bulk-bar` und `.mod-select-check`.
7. **Modul-Shell (`mod-shell--nav`):** Neue Modulseiten müssen dem Shell-Muster mit `.mod-sidebar` und mobiler Offcanvas-Sidebar folgen.
8. **Pill-Design & Shared Packs:** Einheitliche Klassen nutzen (`.mod-pill-btn`, `.mod-search`, `.mod-view-toggle`, `.mod-toolbar`, `.mod-pill-input`). Keine neuen modulspezifischen Präfixe (`files-pill-btn`, `*-search` etc.).
9. **Farb-Tokens:** Immer `var(--accent-color, var(--bs-primary))` bzw. `var(--accent-style)` verwenden; niemals `#0d6efd` direkt schreiben.
10. **Keine willkürlichen Inline-Styles:** `style="..."` ausschließlich für dynamische Server-Werte (z. B. `folder.color` oder Progressbars).
11. **Modals außerhalb der Shell:** Modals stets außerhalb von `.mod-shell--nav` platzieren, um Z-Index-Konflikte mit dem Backdrop zu vermeiden.
12. **CI-Überprüfung:** Änderungen müssen `python scripts/qa_css_design_guardrails.py` fehlerfrei bestehen.
