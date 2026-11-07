# Prismateams UI & Frontend Styleguide

> **Status:** Verbindlich (Production Standard)  
> **Gültig für:** Alle HTML-Templates, CSS-Dateien und JavaScript-UI-Komponenten von Prismateams  
> **CI-Enforcement:** Automatisch überwacht via `scripts/qa_css_design_guardrails.py` und `.github/workflows/css-design-guardrails.yml`

Dieser Styleguide definiert die verbindlichen Gestaltungs- und Code-Standards für das Frontend von Prismateams. Grundlage ist das **Pill-Design-System** und die responsive Modul-Shell-Architektur (`mod-shell--nav`), orientiert an den Kernmodulen *Dateien*, *Media Downloader* und *File Converter*.

---

## 1. Farbpalette & Design Tokens

Prismateams verwendet ein dreistufiges Theming-System (**Light**, **Dark**, **OLED**) kombiniert mit einer mandanten- bzw. benutzerdefinierten Akzentfarbe.

### 1.1 Akzent- und Primärfarben

| Token / Variable | CSS-Wert / Fallback | Bedeutung & Verwendung |
| :--- | :--- | :--- |
| `--accent-color` | `var(--accent-color, var(--bs-primary))` | Dynamische Hauptakzentfarbe (vom Benutzer wählbar). Für Rahmen, Icons, Links, aktive Zustände. |
| `--accent-style` | `var(--accent-style, var(--bs-primary))` | Entweder einfarbig (`--accent-color`) oder linearer Gradient für Flächen, CTAs, Avatare. |
| `--bs-primary` | Bootstrap Standard `#0d6efd` | **Nur als CSS-Fallback** erlaubt. Niemals bare `#0d6efd` hardcoden! |

> [!CAUTION]
> **Hardcode-Verbot:** Der Farbwert `#0d6efd` darf im gesamten Codebase **nie** direkt als Hex-Code hardcodiert werden. Verwende ausnahmslos:  
> `var(--accent-color, var(--bs-primary))` bzw. `var(--accent-style)`. Dies wird im CI-Build über `scripts/qa_css_design_guardrails.py` erzwungen.

### 1.2 Semantische Statusfarben

Die semantischen Farben basieren auf den standardisierten Bootstrap 5 Utility-Tokens:

| Status | CSS-Variable | Typischer Hex-Wert | Kontrast-Vorgabe (Text) |
| :--- | :--- | :--- | :--- |
| **Success** | `var(--bs-success)` | `#198754` | Text immer weiß (`#ffffff`) |
| **Danger** | `var(--bs-danger)` | `#dc3545` | Text immer weiß (`#ffffff`) |
| **Warning** | `var(--bs-warning)` | `#ffc107` | Text **immer dunkel** (`#212529` bzw. `.text-dark`), niemals weiß! |
| **Info** | `var(--bs-info)` | `#0dcaf0` | Text dunkel (`#212529`) |
| **Muted / Secondary** | `var(--bs-secondary-color)` | `#6c757d` | Auf hellem Grund min. 4.5:1 |

### 1.3 Oberflächen, Hintergründe & Modi

Die Plattform unterscheidet drei explizite Oberflächenmodi:

```
[data-bs-theme="light"]        Standard Light Mode (Grauer Portal-Canvas, weiße Karten)
[data-bs-theme="dark"]         Standard Dark Mode (Dunkelgrau #1a1a1a)
[data-oled-mode="true"]        Reiner OLED-Modus (Rechtes Tiefschwarz #000000, 1px Borders)
```

| Token / Element | Light Mode (`data-bs-theme="light"`) | Dark Mode (`data-bs-theme="dark"`) | OLED Mode (`data-oled-mode="true"`) |
| :--- | :--- | :--- | :--- |
| `--portal-bg` | `#f0f2f5` (angenehmes Hellgrau) | `#1a1a1a` | `#000000` |
| `--bs-body-bg` | `#f0f2f5` | `#1a1a1a` | `#000000` |
| `--bs-tertiary-bg` | `#e9ecef` (Subtile Toolbars/Bulk-Bar) | `#2b3035` | `#111111` |
| Card-Oberfläche | `#ffffff` (Shadow: `0 2px 8px rgba(0,0,0,0.1)`) | `#242424` / Bootstrap Dark | `#000000` (`border: 1px solid #1a1a1a`, shadow: none) |
| Modal-Oberfläche | `#ffffff` | `#242424` | `#000000` (`border: 1px solid #1a1a1a`) |
| Trennlinien / Border | `var(--bs-border-color)` (`#dee2e6`) | `rgba(255, 255, 255, 0.15)` | `#1a1a1a` |

### 1.4 Textfarben & Kontraste

- **Primärtext:** `var(--bs-body-color)` (`#212529` in Light, `#e9ecef` in Dark, `#ffffff` in OLED).
- **Sekundärtext / Muted:** `var(--bs-secondary-color, #6c757d)` (Light), `rgba(233, 236, 239, 0.65)` (Dark), `rgba(245, 245, 245, 0.62)` (OLED).
- **Kontrastregel:** Alle UI-Texte müssen die WCAG AA-Norm erfüllen (mindestens 4.5:1 für Normaltext, 3:1 für Überschriften und UI-Komponenten).
- **Interaktive Tönungen:** Nutze CSS `color-mix()` für Hover- und Fokus-States:
  ```css
  /* Beispiel: Dezente Akzent-Hintergrundtönung */
  background: color-mix(in srgb, var(--accent-color, var(--bs-primary)) 10%, transparent);
  ```

---

## 2. Typografie

### 2.1 Schriftfamilien

- **UI & Fließtext:** Nativer System-Font-Stack (keine externen Webfont-Ladezeiten, maximale Performance):
  ```css
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  ```
- **Code & Monospace:**
  ```css
  font-family: SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  ```
- **Icons:** Ausschließlich **Bootstrap Icons** (`bi bi-*`).

### 2.2 Schriftgrößen-Hierarchie

| Element | Bootstrap-Klasse / CSS | Schriftgröße | Zeilenhöhe | Verwendung |
| :--- | :--- | :--- | :--- | :--- |
| **Modul-Brand** | `.mod-sidebar-brand` | `1.55rem` (24.8px) | `1.2` | Modulname oben in der Sidebar |
| **H1** | `h1`, `.h1` | `clamp(1.2rem, 5.5vw, 1.65rem)` | `1.2` | Seitentitel, Hauptansicht-Headings |
| **H2** | `h2`, `.h2` | `1.75rem` (28px) | `1.25` | Sektionsüberschriften, Modul-Tabs |
| **H3** | `h3`, `.h3` | `1.5rem` (24px) | `1.3` | Detailansichten, Widget-Titel |
| **H4** | `h4`, `.h4` | `1.25rem` (20px) | `1.35` | Sub-Sektionen, Listengruppen |
| **H5 / Modal** | `h5`, `.modal-title` | `1.1rem` – `1.25rem` | `1.4` | Modal-Titel, Karten-Titel (`.card-title`) |
| **H6** | `h6`, `.h6` | `1.0rem` (16px) | `1.4` | Meta-Labels, Tabellen-Kopfzeilen |
| **Fließtext** | `body`, `p` | `1.0rem` (16px) | `1.5` | Standard-Inhaltstexte |
| **Small / Meta** | `small`, `.small` | `0.875rem` (14px) | `1.4` | Datumsangaben, Dateigrößen, Toolbars |
| **Badges / Micro** | `.badge`, `.mod-pill-select__badge` | `0.72rem` – `0.8rem` | `1.2` | Status-Badges, Zähler, Chips |

### 2.3 Schriftstärken (Font Weights)

- `400` (Regular): Fließtext, Tabellenwerte, Beschreibungen.
- `500` (Medium): Badges, sekundäre Navigationselemente.
- `600` (Semi-Bold): Standard für Buttons (`.mod-pill-btn`), Navbar-Titel (`.top-navbar-portal`), Modal-Titel, Card-Titles.
- `650` (Bold-Display): Modul-Sidebar-Titel (`.mod-sidebar-brand`), Badge-Zahlen.

---

## 3. Layout & Spacing

### 3.1 Globale Höhen & Viewport-Tokens

```css
:root {
    --top-navbar-height: 64px;
    --portal-mobile-nav-height: calc(3.6rem + env(safe-area-inset-bottom, 0px));
    --portal-mobile-nav-clearance: calc(5.25rem + env(safe-area-inset-bottom, 0px));
    --mod-sidebar-width: 240px;
    --mod-gap: 1.25rem;
    --mod-radius-pill: 1.5rem;
    --mod-radius-card: 0.75rem;
}
```

### 3.2 Die Modul-Shell-Architektur (`mod-shell--nav`)

Jede Modul-Hauptseite **muss** als Shell strukturiert werden. Die Shell sorgt auf Desktop (`>= 992px`) für Viewport-Locking (kein Window-Scroll, nur `.mod-main` scrollt) und stellt auf Mobilgeräten nahtlos auf die Offcanvas-Sidebar um.

```html
<div class="{modul}-shell mod-shell--nav">
  <!-- Desktop Sidebar (>= 992px) -->
  <aside class="mod-sidebar d-none d-lg-flex flex-column">
    <div class="mod-sidebar-brand">
      <i class="bi bi-folder2-open"></i>
      <span>{{ _('modul.heading') }}</span>
    </div>
    
    <!-- Optional: Primäre Modul-Aktion (CTA) -->
    <div class="dropdown mod-sidebar-new-wrap w-100">
      <button class="btn mod-sidebar-new w-100 text-start" type="button" data-bs-toggle="dropdown">
        <i class="bi bi-plus-lg me-2"></i> {{ _('modul.new_button') }}
      </button>
      <ul class="dropdown-menu mod-dropdown-menu">...</ul>
    </div>

    <!-- Navigation -->
    <nav class="mod-sidebar-nav nav flex-column gap-1">
      <a class="nav-link mod-nav-link active" href="...">
        <i class="bi bi-grid me-2"></i>{{ _('modul.nav.overview') }}
      </a>
    </nav>
  </aside>

  <!-- Mobile Offcanvas Sidebar (< 992px) -->
  <div class="offcanvas offcanvas-start mod-offcanvas d-lg-none" id="{modul}SidebarOffcanvas" tabindex="-1">
    <div class="offcanvas-header">
      <h5 class="offcanvas-title">{{ _('modul.heading') }}</h5>
      <button type="button" class="btn-close" data-bs-dismiss="offcanvas"></button>
    </div>
    <div class="offcanvas-body">
      <!-- Gleiche Navigation via Makro mit dismiss_offcanvas=true -->
    </div>
  </div>

  <!-- Scrollbarer Hauptbereich -->
  <div class="mod-main">
    <!-- Toolbar, Filter, Grid/Table -->
  </div>
</div>
```

### 3.3 Bootstrap-Grid & Container

- **Haupt-Container:** `<div class="main-content">` > `<div class="container-fluid">`.
- **Keine horizontalen Scrollbalken:** `overflow-x: clip` ist auf `html`, `body` und `.main-content` aktiv. Alle Flex-Kinder müssen `min-width: 0` besitzen.
- **Card-Raster:** Standardmäßig Bootstrap 12-Spalten-Raster mit `g-3` (1rem Abstand):
  ```html
  <div class="row g-3">
    <div class="col-12 col-md-6 col-lg-4">...</div>
  </div>
  ```

### 3.4 Standard-Abstände & Spacing-Regeln

Verwende strikt die Bootstrap-Spacing-Skala (`$spacer: 1rem = 16px`):

| Klasse | Pixelwert | Vorgesehener Einsatzbereich |
| :--- | :--- | :--- |
| `gap-1` / `mb-1` / `p-1` | `0.25rem` (4px) | Subtiles Icon-Spacing, engste Listen-Items |
| `gap-2` / `mb-2` / `p-2` | `0.5rem` (8px) | Toolbars, Button-Gruppen, Tabellenzellen-Paddings |
| `gap-3` / `mb-3` / `p-3` | `1.0rem` (16px) | Card-Body-Padding, Standard-Abstand zwischen Modulblöcken |
| `gap-4` / `mb-4` / `p-4` | `1.5rem` (24px) | Sektionsabstände, Modul-Gap (`--mod-gap: 1.25rem`) |
| `mb-5` / `py-5` | `3.0rem` (48px) | Empty-State-Container, Auth-Screens |

---

## 4. Komponenten-Standards

### 4.1 Buttons: Das Pill-Design

Alle Buttons im Modul-Bereich basieren auf `.mod-pill-btn` (`border-radius: var(--mod-radius-pill, 1.5rem)`).

```html
<!-- Primärer Akzent-Button (CTA) -->
<button type="button" class="btn mod-pill-btn mod-pill-btn--accent">
  <i class="bi bi-check2"></i>
  <span>Speichern</span>
</button>

<!-- Subtiler Outline-Button -->
<button type="button" class="btn mod-pill-btn mod-pill-btn--outline">
  <i class="bi bi-arrow-repeat"></i>
  <span>Aktualisieren</span>
</button>

<!-- Neutraler Muted-Button (Abbrechen / Zurück) -->
<button type="button" class="btn mod-pill-btn mod-pill-btn--outline-muted" data-bs-dismiss="modal">
  Abbrechen
</button>

<!-- Destruktiver Button (Löschen) -->
<button type="button" class="btn mod-pill-btn mod-pill-btn--danger">
  <i class="bi bi-trash"></i>
  <span>Löschen</span>
</button>

<!-- Icon-Only Button (exakt quadratisch 2.15rem x 2.15rem) -->
<button type="button" class="btn mod-pill-btn mod-pill-btn--icon" aria-label="Aktionen">
  <i class="bi bi-three-dots-vertical"></i>
</button>
```

### 4.2 Toolbar, Suche & Ansichts-Toggle

Jedes Listen-/Karten-Modul besitzt eine Toolbar (`.mod-toolbar`) mit einheitlicher Suche und Ansichts-Toggle:

```html
<div class="mod-toolbar mb-3">
  <!-- Zentrales Pill-Suchfeld -->
  <div class="mod-search" role="search">
    <label class="mod-search-field" for="modSearchInput">
      <i class="bi bi-search" aria-hidden="true"></i>
      <input type="text" id="modSearchInput" class="mod-search-input" placeholder="Suchen..." autocomplete="off">
    </label>
    <button type="button" class="btn mod-search-clear d-none" id="modSearchClear" aria-label="Suche leeren">
      <i class="bi bi-x-lg"></i>
    </button>
  </div>

  <!-- Aktionen & View Toggle (List/Grid) -->
  <div class="mod-toolbar-actions">
    <div class="mod-view-toggle" data-view="list">
      <div class="mod-view-toggle__indicator"></div>
      <button type="button" class="mod-view-toggle__btn active" data-view-target="list" aria-label="Listenansicht">
        <i class="bi bi-list-ul"></i>
      </button>
      <button type="button" class="mod-view-toggle__btn" data-view-target="grid" aria-label="Kachelansicht">
        <i class="bi bi-grid"></i>
      </button>
    </div>
  </div>
</div>
```

### 4.3 Cards & Kachelansicht

Cards dürfen nicht mehr als Fullscreen-Ersatz ohne Shell genutzt werden, sondern dienen als strukturierende Container für Inhalte und Grid-Items:

```html
<article class="card h-100">
  <div class="card-body d-flex flex-column p-3">
    <div class="d-flex align-items-start justify-content-between gap-2 mb-2">
      <div class="mod-grid-preview flex-shrink-0">
        <i class="bi bi-file-earmark-text"></i>
      </div>
      <div class="dropdown">
        <button class="btn btn-sm btn-link" type="button" data-bs-toggle="dropdown" data-bs-popper-config='{"strategy":"fixed"}'>
          <i class="bi bi-three-dots-vertical"></i>
        </button>
        <ul class="dropdown-menu dropdown-menu-end mod-dropdown-menu">...</ul>
      </div>
    </div>
    <h5 class="card-title text-truncate mb-1">Dateiname.pdf</h5>
    <div class="small text-muted mb-3">2.4 MB · 12.03.2026</div>
    <div class="mt-auto pt-2 border-top">
      <span class="badge bg-success">Fertig</span>
    </div>
  </div>
</article>
```

### 4.4 Formulare & Inputs

- **Pill Input:** Inputs und reguläre Selects erhalten die Klasse `.mod-pill-input`:
  ```html
  <input type="text" class="form-control mod-pill-input" placeholder="Name eingeben">
  ```
- **Custom Pill Select:** Für fortgeschrittene Selects mit Badge/Icon nutze `.mod-pill-select` aus `mod-forms.css`.
- **Labels:** Stets `<label class="form-label small fw-semibold">` verwenden.

### 4.5 Modals (Dialoge)

> [!IMPORTANT]
> **Modals niemals innerhalb der Modul-Shell platzieren!**  
> Modals müssen im Template stets **außerhalb** von `<div class="...-shell mod-shell--nav">` (am Ende der Datei vor `{% endblock %}`) deklariert werden. Andernfalls entsteht durch CSS-Transforms und Stacking-Contexts ein z-index-Bug, bei dem das Modal hinter dem grauen Backdrop liegt!

Standard-Aufbau eines Bootstrap 5 Modals im Prismateams-Design:

```html
<div class="modal fade" id="itemActionModal" tabindex="-1" aria-labelledby="itemActionModalLabel" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered modal-dialog-scrollable">
    <div class="modal-content">
      <div class="modal-header border-0 pb-0">
        <h5 class="modal-title" id="itemActionModalLabel">
          <i class="bi bi-pencil-square me-2" aria-hidden="true"></i>Eintrag bearbeiten
        </h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Schließen"></button>
      </div>
      <div class="modal-body pt-3">
        <!-- Formular-Felder -->
      </div>
      <div class="modal-footer border-0 pt-0 gap-2">
        <button type="button" class="btn btn-secondary mod-pill-btn" data-bs-dismiss="modal">Abbrechen</button>
        <button type="button" class="btn btn-accent mod-pill-btn mod-pill-btn--accent">Speichern</button>
      </div>
    </div>
  </div>
</div>
```

### 4.6 Badges & Counter

- **Standard-Badge:** `<span class="badge bg-success">Aktiv</span>`
- **Pill-Badge:** `<span class="badge rounded-pill bg-accent">Neu</span>`
- **Navigations-Zähler (Sidebar):** `<span class="badge mod-nav-badge ms-auto">12</span>`

---

## 5. Regeln & No-Gos (Verbindliche Coding-Vorschriften)

### 5.1 Verbotene Muster (Strict CI Rules)

| Verboten ❌ | Erlaubt / Vorgeschrieben ✅ | Begründung |
| :--- | :--- | :--- |
| **Modul-Präfixe bei Pill-Buttons**<br>`files-pill-btn`, `kanban-pill-btn`, `wiki-pill-btn`, `contacts-pill-btn` | `.mod-pill-btn` + ggf. `.mod-pill-btn--*` | Shared UI Pack (`mod-buttons.css`) garantiert konsistentes Design und verhindert CSS-Duplizierung. |
| **Legacy-Search-Klassen**<br>`files-search`, `wiki-search`, `calendar-search` etc. | `.mod-search` mit `.mod-search-field` | Shared Search Pack (`mod-search.css`) verwenden. |
| **Cross-Loading von `files.css`**<br>`<link rel="stylesheet" href="...files.css">` in Fremdmodulen | Shared Packs in `core_css`: `mod-list-chrome.css`, `mod-buttons.css` etc. | Verhindert CSS-Bloat und unvorhersehbare Kaskadenkonflikte. |
| **Hardcodiertes `#0d6efd` in CSS** | `var(--accent-color, var(--bs-primary))` | Zerstört benutzerdefinierte Akzentfarben und Dark/OLED-Kontraste. |
| **Alter globaler Zurück-Button**<br>`back-button`, `back-button-container`, `get_back_url`, `btn-outline-secondary` mit Pfeil links oben | `.mod-back-link` innerhalb der Shell oder Breadcrumbs | Existiert im neuen Design nicht mehr. Navigation erfolgt über Sidebar oder In-Shell-Back-Link. |
| **Isolierte Bootstrap-Card als Seitenlayout** | `{modul}-shell mod-shell--nav` mit Sidebar | Veraltetes Tabellen-/Kartenlayout ohne Shell bricht das einheitliche Responsive-Verhalten. |
| **Modals innerhalb der Modul-Shell** | Modals ans Ende des Templates außerhalb `.mod-shell--nav` | Verhindert Z-Index-Trapping hinter dem Backdrop. |
| **`display: flex` direkt auf `<td>`** | `<td>` behält `display: table-cell;`, Flexbox nur in innerem Wrapper | Zerstört Browser-Tabellenberechnung und Spaltenausrichtung. |

### 5.2 Keine willkürlichen Inline-Styles

- **Verboten:** `style="margin-top: 15px; color: #333; font-size: 14px;"`
- **Erlaubt:** Ausschließlich dynamische Server-Werte, die zur Laufzeit generiert werden:
  - Ordner-/Teamfarben: `style="color: {{ folder.color }};"`
  - Dynamische Fortschrittsbalken: `style="width: {{ job.percent }}%"`
  - CSS-Variablen: `style="--pill-badge-hue: 210;"`

### 5.3 Responsive & Accessibility Vorgaben

1. **Touch Targets:** Interaktive Elemente auf Mobilgeräten (Buttons, Nav-Links, Checkboxen) müssen mindestens `44 × 44 px` bzw. `2.5rem × 2.5rem` groß sein.
2. **Safe-Area Insets:** Bei fixierten Elementen am unteren Rand immer `env(safe-area-inset-bottom)` berücksichtigen.
3. **Dropdowns & Modals:** Für Dropdowns in Tabellenzeilen stets `data-bs-popper-config='{"strategy":"fixed"}'` setzen, damit überlaufende Tabellenzellen Dropdown-Menüs nicht abschneiden.
4. **Icons & Screenreader:** Reine Icon-Buttons müssen mit `aria-label="..."` versehen werden; rein dekorative Icons mit `aria-hidden="true"`.

---

## 6. Checkliste für neue Modul-Entwicklungen

- [ ] **Blueprint & Route:** Unter `app/blueprints/{modul}.py` angelegt und in Navigation registriert.
- [ ] **Template-Struktur:** `app/templates/{modul}/index.html` verwendet `<div class="{modul}-shell mod-shell--nav">`.
- [ ] **Sidebar-Komponente:** `_sidebar.html` definiert Desktop- und Offcanvas-Variante (`mod-sidebar-nav`, `mod-nav-link`).
- [ ] **Modul-CSS:** Nur Domänen-Layouts unter `app/static/css/{modul}.css` (alle Shared Elements nutzen `mod-*`).
- [ ] **CSS-Einbindung:** `base.html` lädt `app/static/css/{modul}.css` geschützt per `request.endpoint.startswith('{modul}.')`.
- [ ] **CI Guardrails Check:** Lokaler Test mit `python scripts/qa_css_design_guardrails.py` liefert `Exit 0 (Alle Checks bestanden)`.
