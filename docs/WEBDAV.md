# WebDAV / Explorer-Zugriff

Prismateams stellt die Dateien-Ablage unter **`/webdav`** als WebDAV-Endpunkt bereit. Windows Explorer, macOS Finder und Linux-Dateimanager können die URL als Netzlaufwerk einbinden.

## Voraussetzungen

1. **HTTPS** (Basic Auth wird von Windows ohne SSL oft blockiert)
2. In den Admin-Einstellungen unter **Datei-Einstellungen** den Schalter **WebDAV / Explorer-Zugriff** aktivieren
3. Nginx-Block für `/webdav` (Installer ab aktueller Version; manuell siehe unten)
4. Python-Paket `WsgiDAV` installiert (`pip install -r requirements.txt`)
5. Bei **mehreren Gunicorn-Workern**: `REDIS_ENABLED=True` — WebDAV-Locks werden sonst nur prozesslokal gehalten (Shelve-Datei unter `uploads/.webdav_locks`)

## Ordnerstruktur im Explorer

| Ordner | Inhalt |
|--------|--------|
| `Private` | Persönliche Ablage (wenn private Ordner aktiv) |
| `Public` | Öffentlicher Bereich |
| `Teams/<Teamname>` | Team-Ablagen (wenn Team-Ordner aktiv) |

Rechte entsprechen der Web-Oberfläche (Lesen/Schreiben nach ACL).

Der WebDAV-Root meldet als Anzeigename den Hostnamen (z. B. `ulbr.de`). Das ändert **nicht** den Windows-UNC-Pfad.

## Anmeldung

- **Benutzername:** nur die Portal-E-Mail (ohne `MicrosoftAccount\`)
- **Passwort:** Portal-Login-Passwort (nicht das Microsoft-Konto-Passwort)

**Wichtig:** Zwei-Faktor-Authentifizierung (2FA) wird bei WebDAV **nicht** geprüft — nur E-Mail und Passwort. Gast-Accounts sind ausgeschlossen.

Windows füllt oft `MicrosoftAccount\ihre@email.de` vor — im Dialog **Weitere Optionen → Anderes Konto** wählen und nur die E-Mail lassen.

## Windows: Netzlaufwerk verbinden

1. Dienst **WebClient** starten (`services.msc`)
2. Bei **HTTP/localhost** zusätzlich Registry:  
   `HKLM\SYSTEM\CurrentControlSet\Services\WebClient\Parameters` → DWORD `BasicAuthLevel` = `2`, danach WebClient neu starten  
   (sonst sendet Windows die Anmeldedaten nicht und der Login-Dialog wiederholt sich)
3. Explorer → **Dieser PC** → **Netzlaufwerk verbinden** (besser als „Netzwerkadresse hinzufügen“)
4. Ordner: `https://ihre-domain.tld/webdav` (HTTPS bevorzugt)  
   Lokal alternativ: `\\localhost@5000\DavWWWRoot\webdav`
5. Laufwerk einen **kurzen Namen** geben (z. B. Domain oder „Prismateams“)
6. Andere Anmeldeinformationen → nur Portal-E-Mail + Portal-Passwort

### Windows-Anzeige `host@SSL\DavWWWRoot`

Das ist **feste WebClient-Syntax** (HTTPS + Magic-Token) und lässt sich serverseitig **nicht** entfernen. Der von Ihnen vergebene Laufwerksname erscheint trotzdem als Label, z. B. `Ulbr.de (U:)`.

Wenn der Explorer hartnäckig scheitert: **Cyberduck** oder **WinSCP** als WebDAV-Client (zuverlässiger bei HTTP/localhost).

Alternative (Netzwerkadresse): Explorer-Adresszeile `https://ihre-domain.tld/webdav` bzw. unter Windows teils  
`\\ihre-domain.tld@SSL\DavWWWRoot\webdav`.

## macOS (Finder)

1. Finder → **Gehe zu** → **Mit Server verbinden…** (⌘K)
2. URL: `https://ihre-domain.tld/webdav`
3. Als registrierter Benutzer mit Portal-E-Mail und Passwort anmelden

## Linux (GNOME / KDE)

1. Datei-Manager → Mit Server verbinden / Netzwerkordner
2. Adresse: `davs://ihre-domain.tld/webdav` (oder die HTTPS-URL)
3. Portal-E-Mail und Passwort; Freigabe als Lesezeichen speichern

## Bearbeitung & Sperren

- **Euro-Office** im Browser: mehrere Nutzer können dasselbe Dokument gemeinsam bearbeiten (Kollaboration).
- **WebDAV / Desktop-Office** (Excel, LibreOffice, …): exklusiv über WebDAV-Locks.
- **Kanalübergreifend:** Ist eine Datei in Euro-Office geöffnet, blockiert WebDAV Schreibzugriff (HTTP 423). Hält Desktop-Office einen WebDAV-Lock, öffnet Euro-Office die Datei **schreibgeschützt**. Markdown-Editor und WebDAV sind ebenso abgestimmt.
- Shared Lock-Backend: **Redis** wenn `REDIS_ENABLED`, sonst **Shelve**-Datei. Ohne Redis und mit mehreren Workern können Locks inkonsistent sein („Datei ist in Gebrauch“ trotz freier Datei).
- Antwort-Header `MS-Author-Via: DAV` hilft Microsoft Office, den Share als DAV-editierbar zu erkennen.

Typische Client-Fallen: Datei doppelt geöffnet, WebClient-Cache nach Absturz, Offline-Dateien. Nach einem Crash ggf. Office/Explorer neu starten oder kurz warten, bis der Lock abläuft.

## Nginx (manuell)

Vor dem `location /`-Block einfügen:

```nginx
location /webdav {
    proxy_pass http://teamportal_backend;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Authorization $http_authorization;
    proxy_pass_header Authorization;
    proxy_http_version 1.1;
    proxy_request_buffering off;
    proxy_buffering off;
    client_max_body_size 100M;
    proxy_connect_timeout 600;
    proxy_send_timeout 600;
    proxy_read_timeout 600;
    send_timeout 600;
}
```

Danach: `sudo nginx -t && sudo systemctl reload nginx`.

## Grenzen

- Kein SMB/Samba — nur WebDAV (bewusst, für Windows / macOS / Linux)
- Kein separates „Freigaben“-Stammverzeichnis (ACL innerhalb Private/Public/Teams gilt weiterhin)
- Windows-WebDAV-Client kann bei sehr großen Dateien oder Offline-Sync eigene Limits haben
- Kein Echtzeit-Co-Editing zwischen Microsoft-Desktop-Office und Euro-Office (nur gegenseitige Sperre)
