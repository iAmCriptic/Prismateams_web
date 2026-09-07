#!/usr/bin/env python3
"""CI / lokal: Design-Konventionen gegen Regression (CSS-15).

Prüft:
1. Verbotene Modul-Pill-/Chrome-Klassen (files-pill-btn, files-bulk-*, files-dropdown-menu, …)
2. files.css nur über files.*-Endpoints (base.html) bzw. kein Cross-Load in Fremd-Templates
3. Bare #0d6efd Hardcodes in app/static/css (Fallback var(--accent-color, #0d6efd) ok)
4. Dual-Search-Wrapper-Klassen (files-search, wiki-search, …) in Templates

Exit 0 = OK, 1 = Fehler. Warnungen werden mitgezählt und failen ebenfalls
(strict), damit CI nicht stillschweigend driftet.

Usage:
  python scripts/qa_css_design_guardrails.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
TEMPLATES = APP / "templates"
STATIC_CSS = APP / "static" / "css"
BASE_HTML = TEMPLATES / "base.html"

FORBIDDEN_PILL = re.compile(
    r"\b(?:"
    r"files-pill-btn|inventory-pill-btn|kanban-pill-btn|wiki-pill-btn|"
    r"contacts-pill-btn|credentials-pill-btn|manuals-pill-btn|"
    r"events-form-btn-pill|chat-list-new-btn|"
    r"files-dropdown-menu|"
    r"files-bulk-bar|files-bulk-btn|files-select-check|files-grid-preview|"
    r"files-item-name|files-details-card|files-has-selection|files-list-name-cell"
    r")\b"
)

FORBIDDEN_SEARCH_WRAPPER = re.compile(
    r"\b(?:"
    r"files-search|wiki-search|contacts-search|credentials-search|"
    r"manuals-search|inventory-search|surveys-search|shortlinks-search|"
    r"email-search|protocols-search|excalidraw-search|settings-search|"
    r"calendar-search"
    r")\b"
)

# Allow data-attrs / result UI / API names that contain the substring
SEARCH_ALLOW = re.compile(
    r"data-(?:settings|calendar|contacts)-search|"
    r"(?:settings|calendar)-search-(?:results|result|item|empty|id|root|clear|submit)|"
    r"contacts\.search|"
    r"search_query|search_term|SearchForm|search-url"
)

BARE_PRIMARY = re.compile(r"(?<![\w-])#0d6efd\b", re.I)
ACCENT_FALLBACK = re.compile(
    r"var\(\s*--accent-color\s*,\s*#0d6efd\s*\)", re.I
)

FILES_CSS_HREF = re.compile(
    r"""url_for\(\s*['\"]static['\"]\s*,\s*filename\s*=\s*['\"]css/files\.css['\"]\s*\)"""
)


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def iter_text_files(root: Path, suffixes: tuple[str, ...]):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in suffixes:
            continue
        if "__pycache__" in path.parts or "node_modules" in path.parts:
            continue
        yield path


def check_forbidden_pills() -> list[str]:
    errors = []
    roots = [TEMPLATES, STATIC_CSS, APP / "static" / "js"]
    for root in roots:
        if not root.exists():
            continue
        for path in iter_text_files(root, (".html", ".css", ".js")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if FORBIDDEN_PILL.search(line):
                    errors.append(f"{rel(path)}:{i}: verbotene Pill-Klasse → {line.strip()[:120]}")
    return errors


def check_search_dual_classes() -> list[str]:
    errors = []
    for path in iter_text_files(TEMPLATES, (".html",)):
        text = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if SEARCH_ALLOW.search(line):
                continue
            m = FORBIDDEN_SEARCH_WRAPPER.search(line)
            if m:
                errors.append(
                    f"{rel(path)}:{i}: Legacy-Search-Klasse '{m.group(0)}' "
                    f"(nur mod-search / mod-search--icon) → {line.strip()[:120]}"
                )
    return errors


def check_files_css_cross_loads() -> list[str]:
    """files.css darf nur für files.*-Endpoints bzw. unter templates/files/ geladen werden."""
    errors = []
    endpoint_guard = re.compile(
        r"startswith\(\s*['\"]files\.",
        re.I,
    )

    if BASE_HTML.exists():
        text = BASE_HTML.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            if "css/files.css" not in line:
                continue
            # Look back far enough to cover Jinja elif chains / wrapping.
            window = "\n".join(lines[max(0, i - 20) : i])
            if not endpoint_guard.search(window):
                errors.append(
                    f"{rel(BASE_HTML)}:{i}: files.css ohne files.*-Endpoint-Guard"
                )

    for path in iter_text_files(TEMPLATES, (".html",)):
        text = path.read_text(encoding="utf-8", errors="replace")
        if not FILES_CSS_HREF.search(text):
            continue
        rel_path = path.relative_to(TEMPLATES).as_posix()
        if rel_path == "base.html":
            continue
        if not rel_path.startswith("files/"):
            for i, line in enumerate(text.splitlines(), 1):
                if FILES_CSS_HREF.search(line):
                    errors.append(
                        f"{rel(path)}:{i}: files.css-Cross-Load außerhalb files/ "
                        f"(nutze Shared Packs)"
                    )
    return errors


def check_hardcoded_primary() -> list[str]:
    errors = []
    if not STATIC_CSS.exists():
        return errors
    for path in iter_text_files(STATIC_CSS, (".css",)):
        text = path.read_text(encoding="utf-8", errors="replace")
        # strip known-good fallbacks temporarily
        scrubbed = ACCENT_FALLBACK.sub("var(--accent-color, var(--bs-primary))", text)
        for i, line in enumerate(scrubbed.splitlines(), 1):
            if BARE_PRIMARY.search(line):
                errors.append(
                    f"{rel(path)}:{i}: bare #0d6efd → var(--accent-color, var(--bs-primary)) "
                    f"→ {line.strip()[:120]}"
                )
    return errors


def main() -> int:
    suites = [
        ("Modul-Pill-Klassen", check_forbidden_pills),
        ("Legacy-Search-Klassen", check_search_dual_classes),
        ("files.css-Cross-Loads", check_files_css_cross_loads),
        ("#0d6efd Hardcodes", check_hardcoded_primary),
    ]
    all_errors: list[str] = []
    print("CSS Design Guardrails")
    print("=" * 60)
    for name, fn in suites:
        errs = fn()
        status = "OK" if not errs else f"FAIL ({len(errs)})"
        print(f"[{status}] {name}")
        for e in errs[:40]:
            print(f"  - {e}")
        if len(errs) > 40:
            print(f"  … +{len(errs) - 40} weitere")
        all_errors.extend(errs)

    print("=" * 60)
    if all_errors:
        print(f"{len(all_errors)} Verstoß/Verstöße — bitte beheben.")
        return 1
    print("Alle Checks bestanden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
