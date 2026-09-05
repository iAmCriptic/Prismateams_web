# WebDAV / Windows-Explorer-Zugriff

Prismateams stellt die Dateien-Ablage unter **`/webdav`** als WebDAV-Endpunkt bereit. Windows Explorer kann die URL als Netzlaufwerk einbinden.

## Voraussetzungen

1. **HTTPS** (Basic Auth wird von Windows ohne SSL oft blockiert)
2. In den Admin-Einstellungen unter **Datei-Einstellungen** den Schalter **WebDAV / Explorer-Zugriff** aktivieren
3. Nginx-Block für `/webdav` (Installer ab aktueller Version; manuell siehe unten)
4. Python-Paket `WsgiDAV` installiert (`pip install -r requirements.txt`)

## Ordnerstruktur im Explorer

| Ordner | Inhalt |
|--------|--------|
| `Private` | Persönliche Ablage (wenn private Ordner aktiv) |
| `Public` | Öffentlicher Bereich |
| `Teams/<Teamname>` | Team-Ablagen (wenn Team-Ordner aktiv) |

Rechte entsprechen der Web-Oberfläche (Lesen/Schreiben nach ACL).

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
3. Explorer → **Dieser PC** → **Netzlaufwerk verbinden** (oder Netzwerkadresse hinzufügen)
4. Ordner: `https://ihre-domain.tld/webdav` (HTTPS bevorzugt)  
   Lokal alternativ: `\\localhost@5000\DavWWWRoot\webdav`
5. Andere Anmeldeinformationen → nur Portal-E-Mail + Portal-Passwort

Wenn der Explorer hartnäckig scheitert: **Cyberduck** oder **WinSCP** als WebDAV-Client (zuverlässiger bei HTTP/localhost).

Alternative (Netzwerkadresse): Explorer-Adresszeile `https://ihre-domain.tld/webdav` bzw. unter Windows teils  
`\\ihre-domain.tld@SSL\DavWWWRoot\webdav`.

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

- Kein SMB/Samba — nur WebDAV
- Kein separater „Freigaben“-Stammordner (ACL innerhalb Private/Public/Teams gilt weiterhin)
- Windows-WebDAV-Client kann bei sehr großen Dateien oder Offline-Sync eigene Limits haben
