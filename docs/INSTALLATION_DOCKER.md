<p align="center">
  <img src="../app/static/img/logo.png" alt="Prismateams Logo" width="96">
</p>

<h1 align="center">Prismateams – Docker-Installation</h1>

<p align="center">
  <strong>Dokumentation · Version 3.4.12</strong><br>
  OS-unabhängiger Compose-Stack und Ubuntu-Installer (reine Docker-Variante)
</p>

<p align="center">
  <a href="README.md">Übersicht</a> ·
  <a href="INSTALLATION_SCRIPT.md">Ubuntu native</a> ·
  <a href="INSTALLATION.md">Manuell</a> ·
  <a href="WARTUNG.md">Wartung</a>
</p>

---

## Überblick

Prismateams kann als **Docker-Compose-Stack** betrieben werden:

| Service | Rolle | Standard (Opt-Out) | Profile |
|---------|--------|--------------------|---------|
| `proxy` | Nginx Reverse-Proxy (WebSockets, Euro-Office Routing) | aktiv (Opt-Out) | `proxy` |
| `app` | Flask + Gunicorn | immer aktiv | – |
| `db` | MySQL 8 | immer aktiv | – |
| `redis` | Redis (Sessions, Socket.IO, Limiter) | immer aktiv | – |
| `eurooffice` | Euro-Office Document Server | aktiv (Opt-Out) | `onlyoffice` |
| `excalidraw-room` | Live-Kollaboration | aktiv (Opt-Out) | `excalidraw` |
| `mirotalk` | MiroTalk SFU (Meetings) | aktiv (Opt-Out) | `mirotalk` |

> [!NOTE]
> Standardmäßig sind alle Dienste (`proxy`, `eurooffice`, `excalidraw-room`, `mirotalk`) **aktiviert** und in `COMPOSE_PROFILES=proxy,onlyoffice,excalidraw,mirotalk` in der `.env` hinterlegt.
> Der enthaltene `proxy`-Container routet automatisch `/`, `/eurooffice/`, `/cache/`, `/excalidraw-room/` und WebSockets – **Sie müssen keinen Webserver auf dem Host-Betriebssystem installieren**.

---

## 1. Universeller Schnellstart (100% OS-unabhängig)

Funktioniert auf **Windows (PowerShell/CMD)**, **macOS (Terminal)** und **jedem Linux** (Debian, Arch, Fedora, openSUSE, Ubuntu etc.):

```bash
git clone https://github.com/iAmCriptic/Prismateams_web.git
cd Prismateams_web

# Interaktiver Installer (Opt-Out für Sidecars, automatische Secrets & Start):
python scripts/setup_docker.py
```

*Oder vollautomatisch mit allen Standardwerten (Opt-Out per Flags):*

```bash
# Windows / macOS / Linux:
python scripts/setup_docker.py --defaults

# Einzelne Dienste abwählen (Opt-Out):
python scripts/setup_docker.py --defaults --skip-mirotalk
```

*Unter Linux/macOS kann alternativ das Shell-Script genutzt werden:*
```bash
bash scripts/setup_docker.sh
```

Das Portal ist anschließend sofort unter **http://localhost** erreichbar (bzw. auf dem konfigurierten Port/Domain). Euro-Office, Excalidraw und MiroTalk sind sofort einsatzbereit.

---

## Ubuntu: Installer (reine Docker-Variante)

Automatisiert Docker-CE, Repo-Clone, Secrets-Generierung, `.env`, `docker compose up` und optional Nginx/Apache + SSL + UFW.
Alle Sidecars (Euro-Office, Excalidraw, MiroTalk) sind standardmäßig vorausgewählt.

```bash
git clone https://github.com/iAmCriptic/Prismateams_web.git
cd Prismateams_web
chmod +x scripts/install_ubuntu_docker.sh
sudo bash scripts/install_ubuntu_docker.sh
```

Beispiel Produktion:

```bash
sudo bash scripts/install_ubuntu_docker.sh \
  --domain portal.example.com \
  --webserver nginx --ssl \
  --letsencrypt-email admin@example.com
```

Möchten Sie einzelne Dienste abwählen (Opt-Out):

```bash
sudo bash scripts/install_ubuntu_docker.sh \
  --domain portal.example.com \
  --webserver nginx --ssl \
  --skip-onlyoffice
```

| Option | Bedeutung |
|--------|-----------|
| `--install-dir PATH` | Standard `/var/www/teamportal` |
| `--skip-onlyoffice` | Euro-Office Document Server abwählen (Opt-Out) |
| `--skip-excalidraw` | Excalidraw-Room abwählen (Opt-Out) |
| `--skip-mirotalk` | MiroTalk SFU abwählen (Opt-Out) |
| `--webserver nginx\|apache` | Host-Proxy vor den Containern |
| `--no-webserver` | Nur Compose (App bindet auf 0.0.0.0) |
| `--ssl` | Certbot Let's Encrypt |
| `--non-interactive` | Keine Prompts (übernimmt alle Defaults inkl. Sidecars) |

**Nicht** installiert: Host-MySQL, Host-Redis, Python-venv, `teamportal.service`.

---

## Reverse-Proxy

Der Installer schreibt Nginx/Apache so, dass:

- `/` und `/socket.io/` → App-Container (`127.0.0.1:5000`)
- `/eurooffice`, `/onlyoffice`, `/cache`, Document-Server-Extras → Euro-Office (`:8080`)
- `/excalidraw-room/` → Excalidraw-Room (`:8082`)
- `meet.${DOMAIN}` → MiroTalk (`:3010`)

Manuell: dieselben Upstream-Ziele; WebSocket-Upgrade nicht vergessen.

---

## MiroTalk / WebRTC

- `SFU_ANNOUNCED_IP` = öffentliche IPv4 des Servers
- Firewall: UDP/TCP `40000–40100`
- Für Kamera/Mikrofon: **HTTPS** (Secure Context)
- App intern: `MIROTALK_API_URL=http://mirotalk:3010`
- Öffentlich: `MIROTALK_URL` (z. B. `https://meet.example.com`)

---

## Wartung

```bash
cd /var/www/teamportal   # oder Projektroot
docker compose ps
docker compose logs -f app
docker compose pull
docker compose up -d --build
```

Profiles mitstarten, falls genutzt:

```bash
docker compose --profile onlyoffice --profile excalidraw --profile mirotalk up -d
```

### Backup

- Volumes: `db_data`, `app_uploads`, `app_instance` (Namen je nach Compose-Projektpräfix)
- `.env` gesichert aufbewahren (Secrets)
- DB-Dump: `docker compose exec db mysqldump -u root -p… teamportal > backup.sql`

---

## Troubleshooting

| Problem | Prüfung |
|---------|---------|
| App startet nicht | `docker compose logs app` – DB-Wait, fehlende Keys |
| 502 am Proxy | App-Port / `docker compose ps` |
| Euro-Office JWT | `ONLYOFFICE_SECRET_KEY` = Container `JWT_SECRET` |
| MiroTalk schwarz | HTTPS, `SFU_ANNOUNCED_IP`, UDP-Firewall |
| Compose verlangt Passwort | `MYSQL_PASSWORD` / `MYSQL_ROOT_PASSWORD` in `.env` |

---

## Dateien

| Pfad | Zweck |
|------|--------|
| [`Dockerfile`](../Dockerfile) | App-Image |
| [`docker-compose.yml`](../docker-compose.yml) | Stack + Profiles |
| [`docker/entrypoint.sh`](../docker/entrypoint.sh) | DB-Wait, Schema-Init, Gunicorn |
| [`docs/env.docker.example`](env.docker.example) | `.env`-Vorlage |
| [`scripts/install_ubuntu_docker.sh`](../scripts/install_ubuntu_docker.sh) | Ubuntu Docker-Installer |
