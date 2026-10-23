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

| Service | Rolle | Immer / Profile |
|---------|--------|-----------------|
| `app` | Flask + Gunicorn | immer |
| `db` | MySQL 8 | immer |
| `redis` | Redis (Sessions, Socket.IO, Limiter) | immer |
| `eurooffice` | Euro-Office Document Server | `--profile onlyoffice` |
| `excalidraw-room` | Live-Kollaboration | `--profile excalidraw` |
| `mirotalk` | MiroTalk SFU (Meetings) | `--profile mirotalk` |

Die App erreicht Sidecars im Compose-Netz per **Service-Name** (`db`, `redis`, `eurooffice`, `mirotalk`, …). Der Browser erreicht Euro-Office / Excalidraw / MiroTalk typischerweise über einen **Reverse-Proxy** (`/eurooffice`, `/excalidraw-room`, `meet.`-Host).

**Abgrenzung:** Der klassische Weg auf Ubuntu Server bleibt [`INSTALLATION_SCRIPT.md`](INSTALLATION_SCRIPT.md) (`scripts/install_ubuntu.sh` – venv + systemd). Diese Seite beschreibt die **reine Docker-Variante**.

---

## Voraussetzungen

- Docker Engine + Compose Plugin (v2)
- ca. **2 GB RAM** für den Kern; **≥ 4 GB** mit Euro-Office
- Ports: App (Standard `5000` auf Loopback), optional `8080` / `8082` / `3010` + UDP `40000–40100` (MiroTalk)

---

## Docker Hub

App-Image: **[iamcriptic/prismateams](https://hub.docker.com/r/iamcriptic/prismateams)**

Bei Push auf `main`/`master` (relevante Pfade) oder Tag `v*` baut GitHub Actions und pusht nach Hub  
(Workflow: [`.github/workflows/docker-publish.yml`](../.github/workflows/docker-publish.yml)).  
Manuell: GitHub → **Actions** → **Docker Hub publish** → **Run workflow**.

Compose nutzt standardmäßig `iamcriptic/prismateams:latest` (`APP_IMAGE` in `.env` überschreibbar).

## Schnellstart (beliebiges OS)

```bash
git clone https://github.com/iAmCriptic/Prismateams_web.git
cd Prismateams_web
cp docs/env.docker.example .env
# Secrets in .env setzen (mindestens MYSQL_PASSWORD, MYSQL_ROOT_PASSWORD, SECRET_KEY, Encryption-/VAPID-Keys)

# Image von Hub ziehen (nach erstem erfolgreichen CI-Push):
docker compose pull app
docker compose up -d

# Oder lokal bauen:
docker compose up -d --build
```

Keys erzeugen (nach erstem Image-Build):

```bash
docker compose run --rm --no-deps app python scripts/generate_encryption_keys.py
docker compose run --rm --no-deps app python scripts/generate_vapid_keys.py
# Ausgaben in .env eintragen, dann:
docker compose up -d
```

Portal lokal: **http://127.0.0.1:5000/** (Binding laut `APP_HOST_BIND` / `APP_HOST_PORT` in `.env`).

### Mit optionalen Sidecars

```bash
# .env: ONLYOFFICE_*, EXCALIDRAW_*, MIROTALK_*, SFU_ANNOUNCED_IP setzen
docker compose --profile onlyoffice --profile excalidraw --profile mirotalk up -d --build
```

---

## Ubuntu: Installer (reine Docker-Variante)

Automatisiert Docker-CE, Repo-Clone, `.env`, `docker compose up` und optional Nginx/Apache + SSL + UFW.

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
  --letsencrypt-email admin@example.com \
  --onlyoffice --excalidraw --mirotalk
```

| Option | Bedeutung |
|--------|-----------|
| `--install-dir PATH` | Standard `/var/www/teamportal` |
| `--onlyoffice` / `--excalidraw` / `--mirotalk` | Compose-Profiles |
| `--webserver nginx\|apache` | Host-Proxy vor den Containern |
| `--no-webserver` | Nur Compose (App auf Loopback-Port) |
| `--ssl` | Certbot Let's Encrypt |
| `--non-interactive` | Keine Prompts |

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
