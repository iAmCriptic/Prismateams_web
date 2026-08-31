#!/usr/bin/env python3
"""Funktionales QA-Audit aller Portal-Module (ohne Sicherheitstests).

Prüft ob Hauptseiten und zentrale API-Endpunkte erreichbar sind und keine
Serverfehler oder leeren/fehlerhaften Antworten liefern.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Projektroot auf sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import create_app, db  # noqa: E402
from app.models.user import User  # noqa: E402
from app.utils.common import is_module_enabled  # noqa: E402
from app.utils.navigation import NAV_LINK_REGISTRY, resolve_nav_link  # noqa: E402

# HTML-Fehlerindikatoren (keine Sicherheitsprüfung, nur sichtbare Fehler)
ERROR_PATTERNS = [
    (r"Internal Server Error", "Internal Server Error im HTML"),
    (r"Traceback \(most recent call last\)", "Python-Traceback sichtbar"),
    (r"class=\"alert alert-danger\"[^>]*>\s*[^<]*(?:Fehler|Error|Exception)", "Danger-Alert mit Fehlertext"),
    (r"500 Internal", "HTTP-500-Hinweis im Body"),
    (r"UndefinedError|TemplateNotFound|BuildError", "Jinja/Template-Fehler"),
]

REDIRECT_OK = {301, 302, 303, 307, 308}


@dataclass
class CheckResult:
    name: str
    url: str
    module_key: str | None
    module_enabled: bool
    status: str  # OK | WARN | FAIL | SKIP | DISABLED
    http_status: int | None = None
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _find_test_user() -> User | None:
    user = User.query.filter_by(is_active=True, is_admin=True).first()
    if user:
        return user
    return User.query.filter_by(is_active=True).first()


def _login(client, user: User) -> bool:
    """Authentifiziert den Test-Client mit gültiger DB-Session."""
    from app.models.user_session import UserSession
    import secrets

    session_id = secrets.token_urlsafe(32)
    user_session = UserSession(
        user_id=user.id,
        session_id=session_id,
        ip_address="127.0.0.1",
        user_agent="QA-Audit-Script",
        is_active=True,
    )
    db.session.add(user_session)
    db.session.commit()

    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True
        sess["session_id"] = session_id

    resp = client.get("/dashboard", follow_redirects=False)
    if resp.status_code in REDIRECT_OK:
        loc = resp.headers.get("Location", "")
        if "login" in loc.lower():
            return False
    return resp.status_code == 200 or resp.status_code in REDIRECT_OK


def _scan_html(body: str) -> list[str]:
    issues = []
    text = body[:500_000]
    for pattern, label in ERROR_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            issues.append(label)
    if len(body.strip()) < 100 and "<html" in text.lower():
        issues.append("Sehr kurzer/leerer HTML-Inhalt")
    return issues


def _get_page(client, url: str, follow: bool = False):
    """GET mit optionalem Redirect-Follow; liefert finale Response + Kette."""
    chain = []
    resp = client.get(url, follow_redirects=False)
    chain.append((url, resp.status_code))
    if follow:
        seen = {url}
        while resp.status_code in REDIRECT_OK:
            loc = resp.headers.get("Location", "")
            if not loc or loc in seen:
                break
            seen.add(loc)
            # Relative URLs
            if loc.startswith("/"):
                next_url = loc
            else:
                from urllib.parse import urljoin
                next_url = urljoin(url, loc)
            url = next_url.split("?")[0] if "?" in next_url else next_url
            resp = client.get(next_url, follow_redirects=False)
            chain.append((next_url, resp.status_code))
    return resp, chain


def _classify_page(name: str, url: str, module_key: str | None, resp, chain: list | None = None) -> CheckResult:
    enabled = True if module_key is None else is_module_enabled(module_key)
    chain = chain or []

    if module_key and not enabled:
        return CheckResult(
            name=name,
            url=url,
            module_key=module_key,
            module_enabled=False,
            status="DISABLED",
            http_status=resp.status_code,
            detail="Modul in Systemeinstellungen deaktiviert",
        )

    code = resp.status_code
    final_url = chain[-1][0] if chain else url

    if code >= 500:
        return CheckResult(
            name=name, url=url, module_key=module_key, module_enabled=enabled,
            status="FAIL", http_status=code, detail=f"HTTP {code} Serverfehler",
            extra={"final_url": final_url, "chain": chain},
        )

    if code == 403:
        return CheckResult(
            name=name, url=url, module_key=module_key, module_enabled=enabled,
            status="WARN", http_status=code, detail="HTTP 403 – kein Zugriff für Testnutzer",
            extra={"final_url": final_url},
        )

    if code == 404:
        return CheckResult(
            name=name, url=url, module_key=module_key, module_enabled=enabled,
            status="FAIL", http_status=code, detail="HTTP 404 – Seite nicht gefunden",
            extra={"final_url": final_url},
        )

    if code in REDIRECT_OK and not chain:
        loc = resp.headers.get("Location", "")
        if "login" in loc.lower():
            return CheckResult(
                name=name, url=url, module_key=module_key, module_enabled=enabled,
                status="FAIL", http_status=code, detail=f"Redirect zum Login: {loc}",
            )
        return CheckResult(
            name=name, url=url, module_key=module_key, module_enabled=enabled,
            status="OK", http_status=code, detail=f"Redirect ({code}) -> {loc}",
        )

    if code != 200:
        return CheckResult(
            name=name, url=url, module_key=module_key, module_enabled=enabled,
            status="WARN", http_status=code, detail=f"Unerwarteter HTTP-Status {code}",
            extra={"final_url": final_url},
        )

    ct = (resp.content_type or "").lower()
    if "html" in ct:
        issues = _scan_html(resp.get_data(as_text=True))
        if issues:
            return CheckResult(
                name=name, url=url, module_key=module_key, module_enabled=enabled,
                status="FAIL", http_status=code, detail="; ".join(issues),
                extra={"final_url": final_url},
            )

    if "json" in ct:
        try:
            data = resp.get_json(silent=True)
            if data is None:
                return CheckResult(
                    name=name, url=url, module_key=module_key, module_enabled=enabled,
                    status="FAIL", http_status=code, detail="Ungültiges JSON",
                )
            if isinstance(data, dict) and data.get("error"):
                return CheckResult(
                    name=name, url=url, module_key=module_key, module_enabled=enabled,
                    status="FAIL", http_status=code, detail=f"API-Fehler: {data.get('error')}",
                )
        except Exception as exc:
            return CheckResult(
                name=name, url=url, module_key=module_key, module_enabled=enabled,
                status="FAIL", http_status=code, detail=f"JSON-Parse-Fehler: {exc}",
            )

    detail = "Seite/API antwortet normal"
    if chain and len(chain) > 1:
        detail = f"OK nach Redirect-Kette -> {final_url}"

    return CheckResult(
        name=name, url=url, module_key=module_key, module_enabled=enabled,
        status="OK", http_status=code, detail=detail,
        extra={"final_url": final_url, "chain": chain},
    )


MODULE_PAGES: list[tuple[str, str, str | None]] = [
    ("Dashboard", "/dashboard", None),
    ("Chat", "/chat/", "module_chat"),
    ("Dateien", "/files/", "module_files"),
    ("Kalender", "/calendar/", "module_calendar"),
    ("Veranstaltungen", "/events/", "module_events"),
    ("E-Mail", "/email/", "module_email"),
    ("Kontakte", "/contacts/", "module_contacts"),
    ("Zugangsdaten", "/credentials/", "module_credentials"),
    ("Anleitungen", "/manuals/", "module_manuals"),
    ("Lagerverwaltung", "/inventory/", "module_inventory"),
    ("Wiki", "/wiki/", "module_wiki"),
    ("Kurzlinks", "/shortlinks", "module_shortlinks"),
    ("Kanban", "/kanban/", "module_kanban"),
    ("Excalidraw", "/excalidraw/", "module_excalidraw"),
    ("Umfragen", "/surveys/", "module_surveys"),
    ("Buchungen", "/booking/requests", "module_booking"),
    ("Musik", "/music/", "module_music"),
    ("Media Downloader", "/media-downloader/", "module_media_downloader"),
    ("Dateikonverter", "/file-converter/", "module_file_converter"),
    ("Bewertungen", "/assessment/", "module_assessment"),
    ("Einstellungen", "/settings/", None),
]

API_CHECKS: list[tuple[str, str, str | None]] = [
    ("Benachrichtigungen (pending)", "/api/notifications/pending?limit=1", None),
    ("Dashboard-Optionen", "/api/dashboard/options", None),
    ("E-Mail Unread-Count", "/api/email/unread-count", "module_email"),
    ("Dateien Speicher", "/files/api/storage-usage", "module_files"),
    ("Dateien Presence", "/files/api/presence?folder_id=", "module_files"),
    ("Push VAPID-Key", "/api/push/vapid-key", None),
    ("Manifest", "/manifest.json", None),
]

# Unterseiten / typische Nutzeraktionen (GET-only Smoke-Tests)
SUBPAGE_CHECKS: list[tuple[str, str, str | None]] = [
    ("Lager: Bestand", "/inventory/stock", "module_inventory"),
    ("Lager: Ausleihen", "/inventory/borrows", "module_inventory"),
    ("Lager: Sets", "/inventory/sets", "module_inventory"),
    ("Kalender: Erstellen", "/calendar/create", "module_calendar"),
    ("Wiki: Erstellen", "/wiki/create", "module_wiki"),
    ("Umfragen: Erstellen", "/surveys/create", "module_surveys"),
    ("Kurzlinks: Erstellen", "/shortlinks/create", "module_shortlinks"),
    ("Kanban: Templates-API", "/kanban/api/templates", "module_kanban"),
    ("Bewertungen: Home", "/assessment/home", "module_assessment"),
    ("Buchungen: Formular-Liste", "/booking/", "module_booking"),
    ("Einstellungen: Profil", "/settings/profile", None),
    ("Einstellungen: Admin", "/settings/admin", None),
    ("Auth: Login-Seite", "/login", None),
]


def run_audit() -> dict[str, Any]:
    app = create_app(os.getenv("FLASK_ENV", "development"))
    results: list[CheckResult] = []

    with app.app_context():
        user = _find_test_user()
        if not user:
            return {"error": "Kein aktiver Benutzer in der Datenbank gefunden", "results": []}

        with app.test_client() as client:
            if not _login(client, user):
                return {
                    "error": f"Login fehlgeschlagen für User id={user.id}",
                    "results": [],
                }

            # Nav-Registry-Konsistenz
            for key, entry in NAV_LINK_REGISTRY.items():
                if key == "settings":
                    continue
                link = resolve_nav_link(key, user)
                if link is None and entry.get("module") and is_module_enabled(entry["module"]):
                    results.append(CheckResult(
                        name=f"Navigation: {key}",
                        url=entry["endpoint"],
                        module_key=entry.get("module"),
                        module_enabled=True,
                        status="WARN",
                        detail="Modul aktiv, aber Nav-Link nicht auflösbar",
                    ))

            for name, url, module_key in MODULE_PAGES:
                resp, chain = _get_page(client, url, follow=True)
                results.append(_classify_page(name, url, module_key, resp, chain))

            for name, url, module_key in API_CHECKS:
                if module_key and not is_module_enabled(module_key):
                    results.append(CheckResult(
                        name=f"API: {name}", url=url, module_key=module_key,
                        module_enabled=False, status="DISABLED",
                        detail="Modul deaktiviert – API nicht geprüft",
                    ))
                    continue
                resp, chain = _get_page(client, url, follow=False)
                results.append(_classify_page(f"API: {name}", url, module_key, resp, chain))

            for name, url, module_key in SUBPAGE_CHECKS:
                if module_key and not is_module_enabled(module_key):
                    results.append(CheckResult(
                        name=name, url=url, module_key=module_key,
                        module_enabled=False, status="DISABLED",
                        detail="Modul deaktiviert",
                    ))
                    continue
                resp, chain = _get_page(client, url, follow=True)
                results.append(_classify_page(name, url, module_key, resp, chain))

            # Root-Redirect
            root_resp, root_chain = _get_page(client, "/", follow=True)
            results.append(_classify_page("Startseite (/)", "/", None, root_resp, root_chain))

    summary = {
        "OK": sum(1 for r in results if r.status == "OK"),
        "WARN": sum(1 for r in results if r.status == "WARN"),
        "FAIL": sum(1 for r in results if r.status == "FAIL"),
        "SKIP": sum(1 for r in results if r.status == "SKIP"),
        "DISABLED": sum(1 for r in results if r.status == "DISABLED"),
    }

    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "test_user": {"id": user.id, "email": user.email, "is_admin": user.is_admin},
        "summary": summary,
        "results": [r.__dict__ for r in results],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# QA-Audit – Modul-Funktionalität",
        "",
        f"**Datum:** {report.get('timestamp', '–')}",
        "",
    ]

    if report.get("error"):
        lines.extend([
            f"> **Abbruch:** {report['error']}",
            "",
        ])
        return "\n".join(lines)

    user = report["test_user"]
    lines.extend([
        f"**Testnutzer:** {user['email']} (ID {user['id']}, Admin: {user['is_admin']})",
        "",
        "## Zusammenfassung",
        "",
        "| Status | Anzahl |",
        "|--------|--------|",
    ])
    labels = {
        "OK": "Funktioniert",
        "WARN": "Warnung",
        "FAIL": "Fehler",
        "DISABLED": "Modul deaktiviert",
        "SKIP": "Übersprungen",
    }
    for key, label in labels.items():
        lines.append(f"| {label} | {report['summary'].get(key, 0)} |")

    lines.extend(["", "## Modul-Checks", ""])
    lines.append("| Modul | URL | Status | HTTP | Detail |")
    lines.append("|-------|-----|--------|------|--------|")

    status_icon = {"OK": "OK", "WARN": "WARN", "FAIL": "FAIL", "DISABLED": "–", "SKIP": "SKIP"}

    for r in report["results"]:
        icon = status_icon.get(r["status"], r["status"])
        http = r.get("http_status") or "–"
        lines.append(f"| {r['name']} | `{r['url']}` | **{icon}** | {http} | {r.get('detail', '')} |")

    fails = [r for r in report["results"] if r["status"] == "FAIL"]
    warns = [r for r in report["results"] if r["status"] == "WARN"]

    if fails:
        lines.extend(["", "## Kritische Fehler", ""])
        for r in fails:
            lines.append(f"- **{r['name']}** (`{r['url']}`): {r.get('detail', '')}")

    if warns:
        lines.extend(["", "## Warnungen", ""])
        for r in warns:
            lines.append(f"- **{r['name']}** (`{r['url']}`): {r.get('detail', '')}")

    disabled = [r for r in report["results"] if r["status"] == "DISABLED"]
    if disabled:
        lines.extend(["", "## Deaktivierte Module (nicht geprüft)", ""])
        for r in disabled:
            lines.append(f"- {r['name']}")

    lines.extend([
        "",
        "---",
        "*Rein funktionales Audit – keine Sicherheitsprüfungen.*",
    ])
    return "\n".join(lines)


def main():
    report = run_audit()
    md = render_markdown(report)

    out_dir = os.path.join(ROOT, "docs")
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, "QA_MODULE_AUDIT.md")
    json_path = os.path.join(out_dir, "QA_MODULE_AUDIT.json")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(md.encode("utf-8", errors="replace").decode("utf-8"))
    print(f"\n---\nBericht gespeichert: {md_path}")
    return 1 if report.get("summary", {}).get("FAIL", 0) > 0 or report.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
