# Prismateams UI & Frontend Styleguide

> **Status:** Verbindlich (Production Standard)  
> **Gültig für:** Alle HTML-Templates, CSS-Dateien und JavaScript-UI-Komponenten von Prismateams  
> **CI-Enforcement:** Automatisch überwacht via `scripts/qa_css_design_guardrails.py` und `.github/workflows/css-design-guardrails.yml`

Dieser Styleguide definiert die verbindlichen Gestaltungs- und Code-Standards für das Frontend von Prismateams. Grundlage ist das **Pill-Design-System** und die responsive Modul-Shell-Architektur (`mod-shell--nav`), orientiert an den Kernmodulen *Dateien*, *Media Downloader* und *File Converter*.

---

## 1. Farbpalette & Design Tokens

Prismateams verwendet ein dreistufiges Theming-System (**Light**, **Dark**, **OLED**) kombiniert mit einer mandanten- bzw. benutzerdefinierten Akzentfarbe.

### 1.1 Grundsatz: Niemals Light- oder Dark-Mode hardcoden (Immer voll umschaltbar)

> [!IMPORTANT]
> **Theme-Agilität ist Pflicht:** Es darf **niemals** von einem festen Farbmodus (weder Light noch Dark Mode) ausgegangen werden.  
> Feste Farbwerte wie `#ffffff`, `#000000`, `#1a1a1a` oder `#f0f2f5` dürfen in Modul-CSS oder Templates **nicht statisch hardcodiert** werden. Alle Flächen, Texte, Ränder, Badges, Modals und Dropdowns müssen ausschließlich über die semantischen CSS-Variablen gesteuert werden (`var(--bs-body-bg)`, `var(--bs-body-color)`, `var(--bs-border-color)`, `var(--portal-bg)`, `var(--bs-tertiary-bg)`). Nur so schaltet die gesamte Benutzeroberfläche ohne Darstellungs- oder Kontrastfehler zwischen allen Modi um.

### 1.2 Akzent- und Primärfarben

| Token / Variable | CSS-Wert / Fallback | Bedeutung & Verwendung |
| :--- | :--- | :--- |
| `--accent-color` | `var(--accent-color, var(--bs-primary))` | Dynamische Hauptakzentfarbe (vom Benutzer wählbar). Für Rahmen, Icons, Links, aktive Zustände. |
| `--accent-style` | `var(--accent-style, var(--bs-primary))` | Entweder einfarbig (`--accent-color`) oder linearer Gradient für Flächen, CTAs, Avatare. |
| `--bs-primary` | Bootstrap Standard `#0d6efd` | **Nur als CSS-Fallback** erlaubt. Niemals bare `#0d6efd` hardcoden! |

> [!CAUTION]
> **Hardcode-Verbot:** Der Farbwert `#0d6efd` darf im gesamten Codebase **nie** direkt als Hex-Code hardcodiert werden. Verwende ausnahmslos:  
> `var(--accent-color, var(--bs-primary))` bzw. `var(--accent-style)`. Dies wird im CI-Build über `scripts/qa_css_design_guardrails.py` erzwungen.

### 1.3 Semantische Statusfarben

Die semantischen Farben basieren auf den standardisierten Bootstrap 5 Utility-Tokens:

| Status | CSS-Variable | Typischer Hex-Wert | Kontrast-Vorgabe (Text) |
| :--- | :--- | :--- | :--- |
| **Success** | `var(--bs-success)` | `#198754` | Text immer weiß (`#ffffff`) |
| **Danger** | `var(--bs-danger)` | `#dc3545` | Text immer weiß (`#ffffff`) |
| **Warning** | `var(--bs-warning)` | `#ffc107` | Text **immer dunkel** (`#212529` bzw. `.text-dark`), niemals weiß! |
| **Info** | `var(--bs-info)` | `#0dcaf0` | Text dunkel (`#212529`) |
| **Muted / Secondary** | `var(--bs-secondary-color)` | `#6c757d` | Auf hellem Grund min. 4.5:1 |

### 1.4 Oberflächen, Hintergründe & Modi im Detail

Die Plattform unterstützt drei umschaltbare Oberflächenmodi:

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

### 1.5 Textfarben & Kontraste

- **Primärtext:** `var(--bs-body-color)` (`#212529` in Light, `#e9ecef` in Dark, `#ffffff` in OLED).
- **Sekundärtext / Muted:** `var(--bs-secondary-color, #6c757d)` (Light), `rgba(233, 236, 239, 0.65)` (Dark), `rgba(245, 245, 245, 0.62)` (OLED).
- **Kontrastregel:** Alle UI-Texte müssen die WCAG AA-Norm erfüllen (mindestens 4.5:1 für Normaltext, 3:1 für Überschriften und UI-Komponenten).
- **Interaktive Tönungen:** Nutze CSS `color-mix()` für Hover- und Fokus-States:
  ```css
  /* Beispiel: Dezente Akzent-Hintergrundtönung */
  background: color-mix(in srgb, var(--accent-color, var(--bs-primary)) 10%, transparent);
  ```

---

## 2. Typografie & Internationalisierung (i18n)

### 2.1 Grundsatz: Sprachen dürfen niemals hardcodiert sein

> [!IMPORTANT]
> **Vollständige Lokalisierbarkeit ist Pflicht:**  
> Texte, UI-Beschriftungen, Buttons, Fehlermeldungen, Tooltips, `placeholder`-Texte und `aria-label`-Attribute dürfen **niemals** als statischer Klartext in HTML-Templates oder JavaScript geschrieben werden.
> 
> - **In Jinja2-Templates:** Immer die Übersetzungsfunktion `{{ _('translation.key') }}` verwenden.
> - **In JavaScript:** Texte über `data-i18n-*`-Attribute am Container/Root-Element ins Skript übergeben (z. B. `data-i18n-delete="{{ _('common.delete') }}"`).
> - **Übersetzungsdateien:** Neue Text-Keys müssen stets in `app/translations/de.json` sowie den Partnerdateien (`en.json`, `es.json`, `pt.json`, `ru.json`) gepflegt werden.
> - **Einzige Ausnahme:** Vom Benutzer editierte Inhalte oder vorgefertigte Roh-Vorlagen (wie frei bearbeitbare E-Mail-Templates, Mustervorlagen oder Roh-Systemlogs).

### 2.2 Schriftfamilien

- **UI & Fließtext:** Nativer System-Font-Stack (keine externen Webfont-Ladezeiten, maximale Performance):
  ```css
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  ```
- **Code & Monospace:**
  ```css
  font-family: SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  ```
- **Icons:** Ausschließlich **Bootstrap Icons** (`bi bi-*`).

### 2.3 Schriftgrößen-Hierarchie

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

### 2.4 Schriftstärken (Font Weights)

- `400` (Regular): Fließtext, Tabellenwerte, Beschreibungen.
- `500` (Medium): Badges, sekundäre Navigationselemente, `.mod-back-link`.
- `600` (Semi-Bold): Standard für Buttons (`.mod-pill-btn`), Navbar-Titel (`.top-navbar-portal`), Modal-Titel, Card-Titles.
- `650` (Bold-Display): Modul-Sidebar-Titel (`.mod-sidebar-brand`), Badge-Zahlen.

---

## 3. Layout & Spacing: Modul-Shell & Navigation

### 3.1 Grundsatz: Navbar-Suche & nahtlose Sidebar für jedes Modul

> [!IMPORTANT]
> **Modul-Standardarchitektur:**  
> 1. **Suchleiste in der Navbar:** Jedes Modul-Template bindet im Top-Bereich zwingend den Block `{% block navbar_search %}` ein, damit das Suchfeld in der fixierten oberen Portal-Navbar (`.top-navbar-search`) erscheint.
> 2. **Nahtlose linke Sidebar:** Auf der linken Seite besitzt jedes Modul eine Sidebar (`.mod-sidebar`), die **nahtlos** in den Hintergrund übergeht (kein kastenartiger Rand, transparenter Canvas-Hintergrund `var(--portal-bg)`, dezent sticky, fließender Übergang zu `.mod-main`).

### 3.2 Globale Höhen & Viewport-Tokens

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

### 3.3 Die Modul-Shell-Architektur (`mod-shell--nav`)

Jede Modul-Hauptseite **muss** als Shell strukturiert werden. Die Shell sorgt auf Desktop (`>= 992px`) für Viewport-Locking (kein Window-Scroll, nur `.mod-main` scrollt) und stellt auf Mobilgeräten nahtlos auf die Offcanvas-Sidebar um.

```html
{% extends "base.html" %}

{% block title %}{{ _('modul.page_title') }}{% endblock %}

{# 1. Pflicht-Suchleiste in der oberen Navbar #}
{% block navbar_search %}
<div class="mod-search" role="search">
    <label class="mod-search-field" for="modSearchInput">
        <i class="bi bi-search" aria-hidden="true"></i>
        <input type="text"
               id="modSearchInput"
               class="mod-search-input"
               placeholder="{{ _('modul.search_placeholder') }}"
               autocomplete="off"
               spellcheck="false"
               enterkeyhint="search">
    </label>
    <button type="button" class="btn mod-search-clear d-none" id="modSearchClear" aria-label="{{ _('common.cancel') }}">
        <i class="bi bi-x-lg"></i>
    </button>
</div>
{% endblock %}

{% block content %}
<div class="{modul}-shell mod-shell--nav">
  <!-- 2. Nahtlose Desktop Sidebar (>= 992px) -->
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
{% endblock %}
```

### 3.4 Bootstrap-Grid & Container

- **Haupt-Container:** `<div class="main-content">` > `<div class="container-fluid">`.
- **Keine horizontalen Scrollbalken:** `overflow-x: clip` ist auf `html`, `body` und `.main-content` aktiv. Alle Flex-Kinder müssen `min-width: 0` besitzen.
- **Card-Raster:** Standardmäßig Bootstrap 12-Spalten-Raster mit `g-3` (1rem Abstand):
  ```html
  <div class="row g-3">
    <div class="col-12 col-md-6 col-lg-3">...</div>
  </div>
  ```

### 3.5 Standard-Abstände & Spacing-Regeln

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
  <span>{{ _('common.save') }}</span>
</button>

<!-- Subtiler Outline-Button -->
<button type="button" class="btn mod-pill-btn mod-pill-btn--outline">
  <i class="bi bi-arrow-repeat"></i>
  <span>{{ _('common.refresh') }}</span>
</button>

<!-- Destruktiver Button (Löschen) -->
<button type="button" class="btn mod-pill-btn mod-pill-btn--danger">
  <i class="bi bi-trash"></i>
  <span>{{ _('common.delete') }}</span>
</button>

<!-- Icon-Only Button (exakt quadratisch 2.15rem x 2.15rem) -->
<button type="button" class="btn mod-pill-btn mod-pill-btn--icon" aria-label="{{ _('common.actions') }}">
  <i class="bi bi-three-dots-vertical"></i>
</button>
```

### 4.2 Der verbindliche Zurück-Button-Standard

> [!IMPORTANT]
> **Vorgabe für den Zurück-Button:**  
> Der Zurück-Button muss **immer grau** gehalten sein (`var(--bs-secondary-color, #6c757d)`), besitzt **einen Pfeil nach links** (`bi bi-arrow-left`) und trägt **immer die Beschriftung „Zurück“** (bzw. übersetzbar: `{{ _('layout.nav.back') }}` oder `{{ _('common.back') }}`).

Es gibt zwei verbindliche Varianten:

#### Variante A: Dezent in der Modul-Shell (Standard auf Unterseiten)
Wird direkt oberhalb des Inhalts oder Tabellentitels platziert:
```html
<div class="mod-back-row mb-3">
  <a href="{{ url_for('modul.index') }}" class="mod-back-link">
    <i class="bi bi-arrow-left"></i>
    <span>{{ _('layout.nav.back') }}</span>
  </a>
</div>
```

#### Variante B: Als Pill-Button (z. B. in Formularen, Detail-Headern oder Modals)
```html
<a href="{{ url_for('modul.index') }}" class="btn mod-pill-btn mod-pill-btn--outline-muted">
  <i class="bi bi-arrow-left"></i>
  <span>{{ _('layout.nav.back') }}</span>
</a>
```

### 4.3 Toolbar & Ansichts-Toggle (List / Grid)

Jedes Listen- oder Karten-Modul besitzt eine Toolbar (`.mod-toolbar`) mit einheitlicher Suche und dem Schieberegler-Ansichts-Toggle `.mod-view-toggle`:

```html
<div class="mod-toolbar mb-3">
  <!-- Zentrales Pill-Suchfeld (optional zusätzlich zur Navbar-Suche) -->
  <div class="mod-search" role="search">
    <label class="mod-search-field" for="modSearchInput">
      <i class="bi bi-search" aria-hidden="true"></i>
      <input type="text" id="modSearchInput" class="mod-search-input" placeholder="{{ _('common.search') }}" autocomplete="off">
    </label>
    <button type="button" class="btn mod-search-clear d-none" id="modSearchClear" aria-label="{{ _('common.cancel') }}">
      <i class="bi bi-x-lg"></i>
    </button>
  </div>

  <!-- Aktionen & View Toggle (List/Grid) -->
  <div class="mod-toolbar-actions">
    <div class="mod-view-toggle" data-view="grid" role="group" aria-label="{{ _('common.list_view') }} / {{ _('common.grid_view') }}">
      <span class="mod-view-toggle__indicator" aria-hidden="true"></span>
      <button type="button" class="mod-view-toggle__btn" id="listViewBtn" title="{{ _('common.list_view') }}">
        <i class="bi bi-list"></i>
      </button>
      <button type="button" class="mod-view-toggle__btn active is-active" id="gridViewBtn" title="{{ _('common.grid_view') }}">
        <i class="bi bi-grid-3x3-gap"></i>
      </button>
    </div>
  </div>
</div>
```

---

### 4.4 Tabellen-Design (Listenansicht nach Dateien-Muster)

Die tabellarische Listenansicht basiert auf `.mod-list-table-wrap` und `.table.mod-list-table`.

> [!CAUTION]
> **Tabellenzellen-Regel:** Niemals `display: flex` direkt auf ein `<td>`-Element setzen! Dies zerstört die automatische Tabellenbreiten-Berechnung des Browsers. `<td>` behält immer `display: table-cell;`, während innere Inhalte mit Flex-Wrappern formatiert werden.

#### Tabellen-Markup

```html
<div class="mod-list-table-wrap">
  <table class="table mod-list-table align-middle mb-0">
    <thead>
      <tr>
        <th scope="col">
          <span class="mod-list-select-all-wrap" title="{{ _('common.select_all') }}">
            <input type="checkbox" class="form-check-input" id="selectAllCheckbox">
          </span>
          {{ _('common.name') }}
        </th>
        <th scope="col" class="d-none d-md-table-cell">{{ _('common.owner') }}</th>
        <th scope="col" class="d-none d-lg-table-cell">{{ _('common.modified') }}</th>
        <th scope="col" class="d-none d-md-table-cell">{{ _('common.size') }}</th>
        <th scope="col" class="text-end">{{ _('common.actions') }}</th>
      </tr>
    </thead>
    <tbody id="listTableBody">
      <tr class="mod-list-row" data-item-id="{{ item.id }}">
        <!-- 1. Namens- & Auswahlzelle -->
        <td class="mod-list-name-cell">
          <label class="mod-select-check mod-select-check--list" onclick="event.stopPropagation()" title="{{ _('common.select') }}">
            <input type="checkbox" class="form-check-input item-checkbox" data-item-id="{{ item.id }}">
          </label>
          <a class="mod-list-name text-decoration-none mod-item-name" href="...">
            <i class="bi bi-file-earmark-text flex-shrink-0 text-primary"></i>
            <span class="mod-item-name-text text-truncate" title="{{ item.name }}">{{ item.name }}</span>
          </a>
        </td>

        <!-- 2. Responsive Metadaten-Spalten -->
        <td class="d-none d-md-table-cell text-muted">{{ item.owner_name }}</td>
        <td class="d-none d-lg-table-cell text-muted">{{ item.updated_at|localdatetime }}</td>
        <td class="d-none d-md-table-cell text-muted">{{ item.size_formatted }}</td>

        <!-- 3. Aktionen (Hover-Shortcuts + Dropdown) -->
        <td class="text-end">
          <div class="mod-list-actions">
            <!-- Schnellauswahl auf Desktop (>= 992px) -->
            <div class="mod-list-hover-actions">
              <button type="button" class="btn btn-sm btn-link" title="{{ _('common.edit') }}">
                <i class="bi bi-pencil"></i>
              </button>
            </div>
            <!-- Standard Dropdown für alle Geräte -->
            <div class="dropdown d-inline-block">
              <button class="btn btn-sm btn-link" data-bs-toggle="dropdown" data-bs-popper-config='{"strategy":"fixed"}' aria-label="{{ _('common.actions') }}">
                <i class="bi bi-three-dots-vertical"></i>
              </button>
              <ul class="dropdown-menu dropdown-menu-end mod-dropdown-menu">
                <li>
                  <a class="dropdown-item" href="...">
                    <i class="bi bi-pencil me-2"></i>{{ _('common.edit') }}
                  </a>
                </li>
                <li><hr class="dropdown-divider"></li>
                <li>
                  <button class="dropdown-item text-danger" type="button">
                    <i class="bi bi-trash me-2"></i>{{ _('common.delete') }}
                  </button>
                </li>
              </ul>
            </div>
          </div>
        </td>
      </tr>
    </tbody>
  </table>
</div>
```

---

### 4.5 Kachelansicht (Grid-View nach Dateien-Muster)

In der Kachelansicht werden Elemente im responsiven Bootstrap-Raster (`row g-3`) als standardisierte Karten dargestellt.

#### Grid-Markup

```html
<div id="gridView" class="row g-3">
  <div class="col-12 col-md-6 col-lg-3" data-item-id="{{ item.id }}">
    <article class="card h-100 position-relative">
      <!-- 1. Checkbox oben links (erscheint bei Hover oder aktiver Selektion) -->
      <label class="mod-select-check" onclick="event.stopPropagation()" title="{{ _('common.select') }}">
        <input type="checkbox" class="form-check-input item-checkbox" data-item-id="{{ item.id }}">
      </label>

      <div class="card-body d-flex flex-column p-3">
        <!-- 2. Große visuelle Vorschau-Fläche (7.5rem Höhe, zentriertes Icon / Bild) -->
        <div class="mod-grid-preview text-center mb-3">
          <i class="bi bi-file-earmark-text text-primary"></i>
          <!-- Alternativ: <img src="..." alt="" class="image-mini-preview"> -->
        </div>

        <!-- 3. Kopfzeile mit zweizeiligem Titel und Aktionen -->
        <div class="d-flex justify-content-between align-items-start gap-1 mb-1">
          <div class="flex-grow-1 min-width-0">
            <h6 class="mb-0 mod-item-name" title="{{ item.name }}">
              <span class="mod-item-name-text">{{ item.name }}</span>
            </h6>
          </div>
          <div class="d-flex align-items-start gap-1" onclick="event.stopPropagation()">
            <!-- Desktop-Hover-Aktionen -->
            <div class="mod-grid-hover-actions">
              <button type="button" class="btn btn-sm btn-link" title="{{ _('common.edit') }}">
                <i class="bi bi-pencil"></i>
              </button>
            </div>
            <!-- Dropdown -->
            <div class="dropdown">
              <button class="btn btn-sm btn-link" data-bs-toggle="dropdown" data-bs-popper-config='{"strategy":"fixed"}' aria-label="{{ _('common.actions') }}">
                <i class="bi bi-three-dots-vertical"></i>
              </button>
              <ul class="dropdown-menu dropdown-menu-end mod-dropdown-menu">
                <li><a class="dropdown-item" href="#"><i class="bi bi-pencil me-2"></i>{{ _('common.edit') }}</a></li>
                <li><hr class="dropdown-divider"></li>
                <li><button class="dropdown-item text-danger" type="button"><i class="bi bi-trash me-2"></i>{{ _('common.delete') }}</button></li>
              </ul>
            </div>
          </div>
        </div>

        <!-- 4. Metadaten & Status am Fuß -->
        <div class="small text-muted mt-auto pt-2 border-top d-flex justify-content-between align-items-center">
          <span>{{ item.size_formatted }}</span>
          <span class="badge bg-success">{{ _('status.ready') }}</span>
        </div>
      </div>
    </article>
  </div>
</div>
```

---

### 4.6 Multi-Select & Bulk-Aktionen (`.mod-bulk-bar`)

Sobald ein oder mehrere Elemente per Checkbox ausgewählt werden, schiebt sich die Bulk-Toolbar animiert über die Ansicht:

```html
<div id="bulkToolbar" class="mod-bulk-bar mb-3" style="display: none;">
  <div class="mod-bulk-inner">
    <div>
      <span class="text-muted">
        <strong id="bulkSelectedCount">0</strong> {{ _('common.selected') }}
      </span>
    </div>
    <div class="mod-bulk-actions">
      <!-- Auswahlschalter -->
      <button type="button" id="bulkSelectAllBtn" class="btn btn-sm mod-bulk-btn mod-bulk-btn--outline">
        <i class="bi bi-check-square"></i> {{ _('common.select_all') }}
      </button>
      <button type="button" id="bulkDeselectBtn" class="btn btn-sm mod-bulk-btn mod-bulk-btn--muted">
        <i class="bi bi-square"></i> {{ _('common.select_none') }}
      </button>

      <!-- Fachliche Aktionen -->
      <button type="button" id="bulkDownloadBtn" class="btn btn-sm mod-bulk-btn mod-bulk-btn--outline">
        <i class="bi bi-download"></i> {{ _('common.download') }}
      </button>

      <!-- Destruktiv -->
      <button type="button" id="bulkDeleteBtn" class="btn btn-sm mod-bulk-btn mod-bulk-btn--danger">
        <i class="bi bi-trash"></i> {{ _('common.delete') }}
      </button>
    </div>
  </div>
</div>
```

---

### 4.7 Formulare & Inputs

- **Pill Input:** Inputs und reguläre Selects erhalten die Klasse `.mod-pill-input`:
  ```html
  <input type="text" class="form-control mod-pill-input" placeholder="{{ _('modul.form.name_placeholder') }}">
  ```
- **Custom Pill Select:** Für fortgeschrittene Selects mit Badge/Icon nutze `.mod-pill-select` aus `mod-forms.css`.
- **Labels:** Stets `<label class="form-label small fw-semibold">` verwenden.

### 4.8 Modals (Dialoge)

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
          <i class="bi bi-pencil-square me-2" aria-hidden="true"></i>{{ _('modul.modal.title') }}
        </h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="{{ _('common.close') }}"></button>
      </div>
      <div class="modal-body pt-3">
        <!-- Formular-Felder -->
      </div>
      <div class="modal-footer border-0 pt-0 gap-2">
        <button type="button" class="btn mod-pill-btn mod-pill-btn--outline-muted" data-bs-dismiss="modal">
          <i class="bi bi-arrow-left"></i>
          <span>{{ _('common.cancel') }}</span>
        </button>
        <button type="button" class="btn btn-accent mod-pill-btn mod-pill-btn--accent">
          {{ _('common.save') }}
        </button>
      </div>
    </div>
  </div>
</div>
```

### 4.9 Badges, Counter & Empty-States

- **Standard-Badge:** `<span class="badge bg-success">{{ _('status.active') }}</span>`
- **Pill-Badge:** `<span class="badge rounded-pill bg-accent">{{ _('status.new') }}</span>`
- **Navigations-Zähler (Sidebar):** `<span class="badge mod-nav-badge ms-auto">12</span>`
- **Empty-State-Hinweis:**
  ```html
  <div class="mod-empty-state text-muted small text-center py-5">
    <i class="bi bi-inbox fs-1 d-block mb-2 opacity-50"></i>
    {{ _('common.no_items_found') }}
  </div>
  ```

---

## 5. Regeln & No-Gos (Verbindliche Coding-Vorschriften)

### 5.1 Verbotene Muster (Strict CI Rules)

| Verboten ❌ | Erlaubt / Vorgeschrieben ✅ | Begründung |
| :--- | :--- | :--- |
| **`display: flex` direkt auf `<td>`** | `<td>` behält `display: table-cell;`, Flexbox nur im inneren Element `.mod-list-name-cell > ...` | Zerstört Browser-Tabellenberechnung und Spaltenausrichtung. |
| **Feste Annahme von Light- oder Dark-Mode**<br>Statische Farben für Flächen/Texte (`#fff`, `#000`, `#1a1a1a`) | CSS-Tokens: `var(--bs-body-bg)`, `var(--bs-body-color)`, `var(--bs-border-color)`, `var(--portal-bg)` | Das Portal muss jederzeit ohne Layoutbrüche zwischen Light, Dark und OLED umschaltbar sein. |
| **Hardcodierte Sprache/Texte im Frontend**<br>`<button>Speichern</button>` oder `placeholder="Suchen..."` | `{{ _('common.save') }}`, `{{ _('common.search') }}`, `data-i18n-*` | Prismateams ist mehrsprachig (de, en, es, pt, ru). Jeder String muss lokalisierbar sein (Ausnahme: Nutzer-Templates/E-Mails). |
| **Falscher Zurück-Button**<br>Blaue Buttons, Buttons ohne Pfeil, `btn-outline-secondary` mit Pfeil links oben außerhalb der Shell | Grauer Zurück-Button mit Pfeil links: `.mod-back-link` oder `.mod-pill-btn--outline-muted` mit `bi-arrow-left` und "Zurück"-Label | Konsistente UX und einheitliches Farbmuster für Navigation. |
| **Fehlende Navbar-Suche im Modul**<br>Modul ohne `{% block navbar_search %}` | Jedes Modul implementiert `{% block navbar_search %}` mit `.mod-search` | Garantierte globale Erreichbarkeit der Suchfunktion in der fixierten Top-Navbar. |
| **Kastenartige / isolierte Sidebar**<br>Eigene Border, abweichender Hintergrund | Nahtlose `.mod-sidebar` mit `var(--portal-bg)` | Die linke Modul-Sidebar geht nahtlos in das Portaldesign über. |
| **Modul-Präfixe bei Pill-Buttons**<br>`files-pill-btn`, `kanban-pill-btn`, `wiki-pill-btn`, `contacts-pill-btn` | `.mod-pill-btn` + ggf. `.mod-pill-btn--*` | Shared UI Pack (`mod-buttons.css`) garantiert konsistentes Design und verhindert CSS-Duplizierung. |
| **Legacy-Search-Klassen**<br>`files-search`, `wiki-search`, `calendar-search` etc. | `.mod-search` mit `.mod-search-field` | Shared Search Pack (`mod-search.css`) verwenden. |
| **Cross-Loading von `files.css`**<br>`<link rel="stylesheet" href="...files.css">` in Fremdmodulen | Shared Packs in `core_css`: `mod-list-chrome.css`, `mod-buttons.css` etc. | Verhindert CSS-Bloat und unvorhersehbare Kaskadenkonflikte. |
| **Hardcodiertes `#0d6efd` in CSS** | `var(--accent-color, var(--bs-primary))` | Zerstört benutzerdefinierte Akzentfarben und Dark/OLED-Kontraste. |
| **Isolierte Bootstrap-Card als Seitenlayout** | `{modul}-shell mod-shell--nav` mit Sidebar | Veraltetes Tabellen-/Kartenlayout ohne Shell bricht das einheitliche Responsive-Verhalten. |
| **Modals innerhalb der Modul-Shell** | Modals ans Ende des Templates außerhalb `.mod-shell--nav` | Verhindert Z-Index-Trapping hinter dem Backdrop. |

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

- [ ] **Navbar-Suche implementiert:** `{% block navbar_search %}` im Modul-Template eingebunden.
- [ ] **Nahtlose Sidebar integriert:** `app/templates/{modul}/_sidebar.html` definiert Desktop- und Offcanvas-Variante (`mod-sidebar-nav`, `mod-nav-link`).
- [ ] **Theme-Umschaltbar:** Keine hardcodierten Light/Dark-Farben, rein tokenbasierte Stile.
- [ ] **Vollständig übersetzt (i18n):** Kein Klartext in Templates oder Skripten (`{{ _('...') }}` genutzt, de.json etc. gepflegt).
- [ ] **Zurück-Button-Konformität:** Grau mit Pfeil nach links (`bi bi-arrow-left`) und Label „Zurück“.
- [ ] **Tabellen & Grid-Views:**
  - Tabellen nutzen `.mod-list-table-wrap` und `.table.mod-list-table` (kein `display:flex` auf `<td>`).
  - Kachelansichten nutzen `#gridView.row.g-3` mit `.mod-grid-preview` (Höhe 7.5rem) und Hover-Shortcuts.
  - Multi-Select über `.mod-bulk-bar` und `.mod-select-check`.
  - Umschaltung über `.mod-view-toggle` mit Schiebe-Indikator.
- [ ] **Template-Struktur:** `app/templates/{modul}/index.html` verwendet `<div class="{modul}-shell mod-shell--nav">`.
- [ ] **Modals außerhalb der Shell:** Modals am Dateiende außerhalb von `.mod-shell--nav` platziert.
- [ ] **Modul-CSS:** Nur Domänen-Layouts unter `app/static/css/{modul}.css` (alle Shared Elements nutzen `mod-*`).
- [ ] **CSS-Einbindung:** `base.html` lädt `app/static/css/{modul}.css` geschützt per `request.endpoint.startswith('{modul}.')`.
- [ ] **CI Guardrails Check:** Lokaler Test mit `python scripts/qa_css_design_guardrails.py` liefert `Exit 0 (Alle Checks bestanden)`.
