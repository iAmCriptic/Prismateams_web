---
trigger: always_on
description: Verbindliche UI- und Styling-Vorgaben aus STYLEGUIDE.md fuer HTML, CSS, Templates und UI-Komponenten.
---

## UI & Frontend Styleguide Direktive

Beachte bei allen Anpassungen an HTML, CSS, Templates oder UI-Komponenten ausnahmslos die Vorgaben in `STYLEGUIDE.md`. Führe keine neuen Farben oder uneinheitlichen Bootstrap-Muster ein, die nicht im Styleguide definiert sind.

### Kernregeln im Überblick:
- **Styleguide als Single Source of Truth:** Vor jeder Änderung an Templates (`app/templates/`), CSS (`app/static/css/`) oder UI-Komponenten ist `STYLEGUIDE.md` zu konsultieren und strikt zu befolgen.
- **Nie Light- oder Dark-Mode hardcoden:** Farben und Oberflächen dürfen niemals statisch für einen Modus fixiert werden. Immer CSS-Tokens (`var(--bs-body-bg)`, `var(--bs-body-color)`, `var(--bs-border-color)`, `var(--portal-bg)`) verwenden, damit die UI jederzeit nahtlos zwischen Light, Dark und OLED umschaltbar bleibt.
- **Sprachen nie hardcoden (i18n):** Texte im Frontend dürfen niemals fest im HTML oder JS stehen. Immer `{{ _('...') }}` in Jinja bzw. `data-i18n-*` für JS verwenden (Ausnahme: vom Nutzer editierbare Inhalte wie E-Mail-Templates).
- **Navbar-Suche & nahtlose linke Sidebar:** Jedes Modul besitzt oben eine Suchleiste in der Navbar (`{% block navbar_search %}`) und links eine Sidebar (`.mod-sidebar`), die nahtlos ohne kastenartige Ränder ins Gesamtdesign übergeht.
- **Zurück-Button-Standard:** Ein Zurück-Button muss immer grau sein (`var(--bs-secondary-color, #6c757d)`), einen Pfeil nach links tragen (`bi bi-arrow-left`) und mit „Zurück“ (`{{ _('layout.nav.back') }}`) beschriftet sein (`.mod-back-link` oder `.mod-pill-btn--outline-muted`).
- **Tabellen & Grid-Views (Dateien-Standard):**
  - Listenansicht: `.mod-list-table-wrap` und `.table.mod-list-table`. Niemals `display: flex` auf `<td>` setzen (`display: table-cell;` beibehalten, Flex nur in innerem Container).
  - Kachelansicht: `#gridView.row.g-3` mit `.mod-grid-preview` (Höhe `7.5rem`), zweizeiligem `.mod-item-name` und Desktop-Hover-Aktionen (`.mod-grid-hover-actions`).
  - Umschaltung: `.mod-view-toggle` mit Schiebe-Indikator `.mod-view-toggle__indicator`.
  - Multi-Select: Animierte `.mod-bulk-bar` mit standardisierten Buttons (`.mod-bulk-btn--outline`, `--muted`, `--danger`) und Checkboxen `.mod-select-check`.
- **Pill-Design & Modul-Shell:** Neue Seiten und Modul-Views basieren immer auf der Modul-Shell (`{modul}-shell mod-shell--nav`) mit mobiler Offcanvas-Navigation.
- **Shared UI Element-Packs:** Verwende ausschließlich die kanonischen Shared-Klassen (`.mod-pill-btn*`, `.mod-search*`, `.mod-view-toggle*`, `.mod-toolbar*`, `.mod-pill-input`, `.mod-bulk-*`, `.mod-list-*`). Keine modulspezifischen Präfixe wie `*-pill-btn` oder `*-search`.
- **Farben & Tokens:** Keine neuen Farbdefinitionen oder willkürlichen Farbwerte. `#0d6efd` niemals hardcodieren, sondern `var(--accent-color, var(--bs-primary))` bzw. `var(--accent-style)` nutzen.
- **Keine willkürlichen Inline-Styles:** `style="..."` ist nur für dynamische Server-Werte (z. B. Ordnerfarben, Prozentbreiten von Ladebalken) erlaubt.
- **Modals außerhalb der Shell:** Alle Bootstrap-Modals müssen im Template außerhalb von `.mod-shell--nav` liegen, um Z-Index-Stacking-Konflikte mit dem Backdrop zu vermeiden.
- **CI-Guardrails ausführen:** Nach CSS- oder Template-Änderungen stets `python scripts/qa_css_design_guardrails.py` ausführen.
