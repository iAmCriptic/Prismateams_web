<p align="center">
  <img src="../app/static/img/logo.png" alt="Prismateams Logo" width="96">
</p>

<h1 align="center">Prismateams – Installationsskript (Ubuntu)</h1>

<p align="center">
  <strong>Dokumentation · Version 3.4.12</strong><br>
  <img src="https://img.shields.io/badge/version-3.4.12-7c3aed?style=flat-square" alt="Version 3.4.12">
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

Beide Batches nutzen denselben modularen Ablauf (Pakete, MySQL, Redis, Docker/Euro-Office, venv, Nginx/Apache, Gunicorn). Kein separates Skript nötig.

## Voraussetzungen

- Ubuntu **24.04** LTS oder **26.04** LTS
- Root-Zugriff (`sudo`)
- Internet-Verbindung
- Mindestens 4 GB RAM empfohlen (für Euro-Office)

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
- Nginx oder Apache (oder manuell) — Nginx setzt Gzip für CSS/JS/JSON; optional Brotli
- MySQL ja/nein (inkl. DB-Name/User/Passwort)
- Redis ja/nein
- Euro-Office inkl. JWT (`JWT_SECRET` = `ONLYOFFICE_SECRET_KEY`) und Proxy `/eurooffice` + `/onlyoffice` + `/cache`
- Excalidraw-Room (optional)
- MiroTalk SFU (Meetings): Docker `mirotalk/sfu`; Hostname → `meet.${DOMAIN}` → `127.0.0.1:3010`; IP/LAN → `http://IP:3010`; UDP `40000–40100`
- FFmpeg / Media Downloader
- `.env`: Modus `auto` | `manual` | `file` (`--env-file`)

## Media Downloader (Browser-Download + FFmpeg)

Beim Aktivieren von FFmpeg setzt der Installer u. a.:

- `FFMPEG_PATH`

Downloads erfolgen im Browser des Nutzers; der Server konvertiert die hochgeladene Rohdatei per FFmpeg. Details: [INSTALLATION.md](INSTALLATION.md) (Schritt 6b).

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
| `--workers N` | Gunicorn-Worker (Standard 2; Redis für SocketIO bei N>1) |
| `--no-gunicorn` | Keinen systemd-Service anlegen |
| `--no-webserver` | Kein Nginx/Apache |
| `--webserver nginx\|apache` | Webserver-Typ |
| `--domain DOMAIN` | Domain/IP |
| `--ssl` / `--letsencrypt-email` | Let's Encrypt |
| `--skip-mysql` / `--skip-redis` | DB/Redis manuell |
| `--db-name` `--db-user` `--db-pass` `--mysql-root-pass` | DB-Parameter |
| `--skip-docker` | Docker, Euro-Office, Excalidraw, MiroTalk überspringen |
| `--skip-onlyoffice` / `--onlyoffice` | Euro-Office Document Server |
| `--skip-excalidraw` / `--excalidraw` | Excalidraw-Room |
| `--skip-mirotalk` / `--mirotalk` | MiroTalk SFU (Meetings) |
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

# Nur App + FFmpeg, ohne Webserver/Euro-Office
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

## Euro-Office-Verdrahtung

Das Skript installiert **Euro-Office Document Server** (`ghcr.io/euro-office/documentserver:latest`), API-kompatibel zu ONLYOFFICE Docs. ENV-Keys bleiben `ONLYOFFICE_*`.

Bei Installation setzt das Skript:

1. Host-Schriftarten: `ttf-mscorefonts-installer` (EULA non-interactive) – nur Arial/Times/… nach `/var/lib/eurooffice/DocumentServer/fonts`. Carlito/Liberation/DejaVu nicht kopieren (liegen im Image; Duplikate zerstören Calibri→Carlito)
2. `docker pull` + Container mit Euro-Office-Volumes (`data`, `logs`, `config`, **`fonts` → `/usr/share/fonts/truetype/custom`**), `JWT_ENABLED=true`, `JWT_SECRET=<secret>`, `ALLOW_PRIVATE_IP_ADDRESS=true`, Bind `127.0.0.1:8080`
3. Warte auf `/healthcheck` bzw. `/welcome/` (bis 180s). Der Entrypoint indexiert das Fonts-Volume beim Start – kein Live-`documentserver-generate-allfonts.sh`
4. In `.env` (neu): `ONLYOFFICE_ENABLED=True`, `ONLYOFFICE_DOCUMENT_SERVER_URL=/eurooffice`, `ONLYOFFICE_SECRET_KEY=<gleiches Secret>` — bestehende URL `/onlyoffice` wird nicht überschrieben
5. Optional `ONLYOFFICE_PUBLIC_URL` aus Domain (+ SSL)
6. Nginx/Apache-Proxy für `/cache`, `/eurooffice` und `/onlyoffice` (Parallelbetrieb)

Ohne mscorefonts fehlen Arial/Times in PDF/Druck; Calibri bleibt über Carlito im Image nutzbar. Details: [INSTALLATION.md – Schritt 5, Schriftarten](INSTALLATION.md#schriftarten-für-rendering--pdf--druck).

Bei Fehler: `docker logs eurooffice-documentserver` und Schritt-Tabelle (`Fehlercode 1` = Start/Pull fehlgeschlagen). Legacy-Container `onlyoffice-documentserver` wird bei Re-Install belassen, solange er Port 8080 belegt.

## MiroTalk SFU (Meetings)

Das Skript installiert **MiroTalk SFU** (`mirotalk/sfu:latest`) mit `network_mode: host`.

Zwei Modi je nach `DOMAIN`:

### Hostname (Produktion)

1. `/var/lib/mirotalk-sfu/.env` mit `HOST_PROTECTED`, `API_KEY_SECRET`, `HOST_USERS`, `SFU_ANNOUNCED_IP`, `SERVER_HOST_URL=https?://meet.${DOMAIN}`
2. Container `--network host`, HTTP nur `127.0.0.1:3010`, Medien UDP/TCP `40000–40100`
3. Nginx/Apache-vHost `meet.${DOMAIN}` → `127.0.0.1:3010` (WebSocket, **kein** Path-Prefix `/mirotalk/`)
4. `X-Forwarded-Proto` wird auf das öffentliche Schema (`http`/`https` laut SSL-Wahl) gesetzt — verhindert falsche `https://…`-Join-URLs unter MiroTalk `TRUST_PROXY`
5. UFW: `40000:40100/udp` und `/tcp`
6. Optional Let's Encrypt für `meet.${DOMAIN}` (eigener Certbot-Lauf; DNS-A-Record nötig)
7. Portal-`.env` (Skript schreibt **immer** alle Felder):
   - `MIROTALK_ENABLED=True`
   - `MIROTALK_URL=https://meet.${DOMAIN}` (bei SSL) bzw. `http://…` ohne SSL
   - `MIROTALK_API_URL=http://127.0.0.1:3010`
   - `MIROTALK_API_KEY` (= `API_KEY_SECRET`)
   - `MIROTALK_HOST_USER` / `MIROTALK_HOST_PASSWORD` (= `HOST_USERS`)
8. Ohne SSL fragt das Skript bei Hostname-Install erneut nach Let's Encrypt (empfohlen): Browser brauchen **HTTPS** für Kamera/Mikrofon (Secure Context), sonst Blackscreen.

### IP / LAN (ohne DNS)

Wenn `DOMAIN` eine IPv4-Adresse ist (oder kein Hostname):

1. **Kein** `meet.${IP}`-vHost — Browser können das ohne Hosts-Datei nicht auflösen
2. `MIROTALK_URL` / `SERVER_HOST_URL` = `http://IP:3010`
3. Container lauscht `0.0.0.0:3010`, UFW zusätzlich `3010/tcp`
4. `SFU_ANNOUNCED_IP` = Install-IP (LAN), nicht zwingend die WAN-IP — sonst WebRTC schwarz
5. `ALLOWED_EMBED_ORIGINS` / CORS = Portal-Origin `http://IP` plus Meet-URL
6. Portal-`.env` erhält dieselben Secrets wie oben — **nicht** weglassen
7. **Hinweis:** Unter `http://IP` blockieren Chromium-Browser `getUserMedia` → produktive Calls brauchen später Domain + HTTPS

Details: [INSTALLATION.md – Schritt 6d](INSTALLATION.md#schritt-6d-optionale-installation---mirotalk-sfu-meetings).

## Gunicorn-Worker

- Default: **2 Worker**, `--timeout 180`, `--max-requests 1000` (hängender Request blockiert nicht das ganze Portal)
- Schema-Init läuft als One-Shot vor dem Service (`scripts/init_database.py`), unabhängig von der Worker-Zahl
- Redis in Produktion für Kanban-SSE, SocketIO und mehrere Worker (Warnung, falls `--skip-redis`)
- Ohne Redis: `--workers 1` (SocketIO sonst nur im jeweiligen Prozess)

## Abschlussübersicht

Am Ende (auch bei Abbruch, soweit möglich):

1. Schritt-Tabelle mit Status
2. Zugangsdaten (MySQL-Root, DB-Passwort, Euro-Office-JWT / `ONLYOFFICE_SECRET_KEY`)
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
  <sub>Prismateams 3.4.12 · Modularer Ubuntu-Installer · 24.04 & 26.04 LTS · einsatzbereit</sub>
</p>
