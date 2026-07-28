<p align="center">
  <img src="../app/static/img/logo.png" alt="Prismateams Logo" width="96">
</p>

<h1 align="center">Prismateams – Installationsskript (Ubuntu)</h1>

<p align="center">
  <strong>Dokumentation · Version 3.0.0</strong><br>
  <img src="https://img.shields.io/badge/version-3.0.0-7c3aed?style=flat-square" alt="Version 3.0.0">
  <img src="https://img.shields.io/badge/Ubuntu-24.04-E95420?style=flat-square&logo=ubuntu&logoColor=white" alt="Ubuntu 24.04">
  <img src="https://img.shields.io/badge/Ubuntu-26.04-E95420?style=flat-square&logo=ubuntu&logoColor=white" alt="Ubuntu 26.04">
  <img src="https://img.shields.io/badge/Installer-ready-22c55e?style=flat-square" alt="Installer ready">
</p>

<p align="center">
  <a href="README.md">Übersicht</a> ·
  <a href="INSTALLATION.md">Manuelle Installation</a> ·
  <a href="WARTUNG.md">Wartung</a> ·
  <a href="ERROR_HANDLING.md">Fehlerbehebung</a>
</p>

---

> **Einsatzbereit**  
> Der modulare Ubuntu-Installer (`scripts/install_ubuntu.sh` + `scripts/install_ubuntu/*.sh`) ist für **Produktion freigegeben**. Empfohlener Weg auf Ubuntu Server **24.04** und **26.04** LTS. Manuelle Schritte nur bei Sonderfällen: [INSTALLATION.md](INSTALLATION.md).

Skript-Pfad (beide Batches gleich):

- Entry: [`scripts/install_ubuntu.sh`](../scripts/install_ubuntu.sh)
- Module: [`scripts/install_ubuntu/`](../scripts/install_ubuntu/)

## Unterstützte Ubuntu-Batches

Der Installer erkennt `/etc/os-release` und akzeptiert beide LTS-Batches ohne Extra-Prompt:

| Batch | Version | Codename | Status |
|-------|---------|----------|--------|
| **Batch 1** | Ubuntu **24.04** LTS | Noble Numbat | freigegeben |
| **Batch 2** | Ubuntu **26.04** LTS | Resolute Raccoon | freigegeben |

Andere Ubuntu-Versionen: Warnung + Nachfrage (im Non-Interactive-Modus: Warnung, dann weiter). Nicht-Ubuntu: Abbruch.

Beide Batches nutzen denselben modularen Ablauf (Pakete, MySQL, Redis, Docker/OnlyOffice, venv, Nginx/Apache, Gunicorn). Kein separates Skript nötig.

## Voraussetzungen

- Ubuntu **24.04** LTS oder **26.04** LTS
- Root-Zugriff (`sudo`)
- Internet-Verbindung
- Mindestens 4 GB RAM empfohlen (für OnlyOffice)

## Schnellstart

```bash
git clone https://github.com/iAmCriptic/Prismateams_web.git
cd Prismateams_web
chmod +x scripts/install_ubuntu.sh
sudo bash scripts/install_ubuntu.sh
```

Ohne Optionen fragt das Skript interaktiv alle leeren Werte ab und zeigt vor dem Start eine Kurzbestätigung.

## Architektur

Jeder Installationsschritt ist ein eigenes Modul und meldet Status `ok` / `skipped` / `failed` / `aborted`. Am Ende erscheint eine Übersicht inkl. generierter Passwörter; zusätzlich wird `$INSTALL_DIR/install-report.txt` geschrieben (chmod 600).

| Modul | Aufgabe |
|-------|---------|
| `common.sh` | Logging, Hilfsfunktionen, manuelle Hinweise |
| `args.sh` | CLI-Parser / `--help` |
| `prompts.sh` | Interaktive Abfragen (nur wenn Wert leer) |
| `steps.sh` | `run_step` + Status-Registry |
| `step_*.sh` | Einzelne Installationsschritte |
| `summary.sh` | Abschlussbericht + Credentials |

## Was kann konfiguriert werden?

- Installationsverzeichnis
- Git-Repository-URL und Branch (Fork / Development)
- Gunicorn-Port, Worker-Anzahl, Service ja/nein
- Nginx oder Apache (oder manuell)
- MySQL ja/nein (inkl. DB-Name/User/Passwort)
- Redis ja/nein
- OnlyOffice inkl. JWT (`JWT_SECRET` = `ONLYOFFICE_SECRET_KEY`) und Proxy `/onlyoffice` + `/cache`
- FFmpeg / Media Downloader
- `.env`: Modus `auto` | `manual` | `file` (`--env-file`)

## Media Downloader (yt-dlp)

Beim Aktivieren von FFmpeg setzt der Installer u. a.:

- `FFMPEG_PATH`
- `MEDIA_DOWNLOADER_PLAYER_CLIENT=ios,web_creator,mweb` (Default gegen Bot-Checks in Rechenzentren)

**Cookies sind optional.** Interaktiv kann ein Pfad zu einer Netscape-`cookies.txt` angegeben werden (`MEDIA_DOWNLOADER_COOKIES_FILE`). Details, Export und Rotation: [INSTALLATION.md](INSTALLATION.md) (Schritt 6b).

## Kommandozeilen-Optionen

```bash
sudo bash scripts/install_ubuntu.sh --help
```

### Wichtige Flags

| Option | Beschreibung |
|--------|--------------|
| `--install-dir PATH` | Installationsverzeichnis |
| `--repo-url URL` | Git-Remote (Fork/Dev) |
| `--branch BRANCH` | Git-Branch |
| `--port PORT` | Gunicorn-Port (Standard 5000) |
| `--workers N` | Gunicorn-Worker (bei N>1: One-Shot-DB-Init, dann N Worker) |
| `--no-gunicorn` | Keinen systemd-Service anlegen |
| `--no-webserver` | Kein Nginx/Apache |
| `--webserver nginx\|apache` | Webserver-Typ |
| `--domain DOMAIN` | Domain/IP |
| `--ssl` / `--letsencrypt-email` | Let's Encrypt |
| `--skip-mysql` / `--skip-redis` | DB/Redis manuell |
| `--db-name` `--db-user` `--db-pass` `--mysql-root-pass` | DB-Parameter |
| `--skip-docker` | Docker + OnlyOffice überspringen |
| `--skip-onlyoffice` / `--onlyoffice` | OnlyOffice |
| `--skip-media-downloader` / `--ffmpeg` | FFmpeg |
| `--env-mode auto\|manual\|file` | `.env`-Strategie |
| `--env-file PATH` | Bestehende `.env` mergen |
| `--timezone` / `--vapid-claim-email` | Häufige `.env`-Werte |
| `--non-interactive` | Keine Prompts (fehlende Pflichtwerte = Fehler) |
| `--continue-on-error` | Optionale Schritte bei Fehler fortsetzen |

### Beispiele

```bash
# Standard interaktiv
sudo bash scripts/install_ubuntu.sh

# Fork / Development-Branch
sudo bash scripts/install_ubuntu.sh \
  --repo-url https://github.com/MEINUSER/Prismateams_web.git \
  --branch Development

# Nur App + FFmpeg, ohne Webserver/OnlyOffice
sudo bash scripts/install_ubuntu.sh --no-webserver --skip-onlyoffice --ffmpeg --port 8000

# Produktion mit Nginx, 4 Workern
sudo bash scripts/install_ubuntu.sh \
  --webserver nginx --domain portal.example.com --workers 4 --onlyoffice

# Non-interactive mit vorbereiteter .env
sudo bash scripts/install_ubuntu.sh --non-interactive \
  --install-dir /var/www/teamportal \
  --domain portal.example.com --webserver nginx \
  --env-mode file --env-file /root/teamportal.env
```

Regel: **CLI setzt Werte vorab → Prompt nur für leere Felder.**

## OnlyOffice-Verdrahtung

Das Skript installiert **ONLYOFFICE Docs (Document Server)** (`onlyoffice/documentserver:latest`), nicht Community Server/Workspace.

Bei Installation setzt das Skript:

1. `docker pull` + Container mit offiziellen Volumes (`data`, `logs`, `lib`), `JWT_ENABLED=true`, `JWT_SECRET=<secret>`, `ALLOW_PRIVATE_IP_ADDRESS=true`, Bind `127.0.0.1:8080`
2. Warte auf `/healthcheck` bzw. `/welcome/` (bis 180s)
3. In `.env`: `ONLYOFFICE_ENABLED=True`, `ONLYOFFICE_DOCUMENT_SERVER_URL=/onlyoffice`, `ONLYOFFICE_SECRET_KEY=<gleiches Secret>`
4. Optional `ONLYOFFICE_PUBLIC_URL` aus Domain (+ SSL)
5. Nginx/Apache-Proxy für `/cache` und `/onlyoffice`

Bei Fehler: `docker logs onlyoffice-documentserver` und Schritt-Tabelle (`Fehlercode 1` = Start/Pull fehlgeschlagen).

## Gunicorn-Worker

- Default: 1 Worker (DB-Init beim ersten Start)
- `--workers N` mit N>1: One-Shot `create_app()` vor Service-Start, dann systemd mit N Workern
- Redis empfohlen bei mehreren Workern (Warnung, falls `--skip-redis`)

## Abschlussübersicht

Am Ende (auch bei Abbruch, soweit möglich):

1. Schritt-Tabelle mit Status
2. Zugangsdaten (MySQL-Root, DB-Passwort, OnlyOffice-JWT)
3. Gewählte Config (Pfad, Repo, Port, Worker, Webserver)
4. `[MANUELL]`-Hinweise für übersprungene Schritte
5. Datei `$INSTALL_DIR/install-report.txt`

**WICHTIG:** Generierte Passwörter und Keys sicher speichern.

## Nach der Installation

1. `.env` prüfen (`$INSTALL_DIR/.env`) — siehe auch [env.example](env.example)
2. Anwendung öffnen (`http://` oder `https://` Domain)
3. Admin über Setup-Assistent anlegen
4. Status: `systemctl status teamportal` · `docker ps` (falls Docker)

Weitere Schritte: [WARTUNG.md](WARTUNG.md) · Probleme: [ERROR_HANDLING.md](ERROR_HANDLING.md) · manuell: [INSTALLATION.md](INSTALLATION.md)

---

<p align="center">
  <img src="../app/static/img/logo.png" alt="" width="40"><br>
  <sub>Prismateams 3.0.0 · Modularer Ubuntu-Installer · 24.04 & 26.04 LTS · einsatzbereit</sub>
</p>
