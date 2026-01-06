# Troubleshooting Guide

## Service neu starten

### Teamportal Service neu starten
```bash
# Service neu starten
sudo systemctl restart teamportal

# Service-Status prüfen
sudo systemctl status teamportal

# Logs anzeigen (letzte 50 Zeilen)
sudo journalctl -u teamportal -n 50 --no-pager

# Logs in Echtzeit verfolgen
sudo journalctl -u teamportal -f
```

### Nginx neu starten
```bash
# Nginx neu starten
sudo systemctl restart nginx

# Nginx-Status prüfen
sudo systemctl status nginx

# Nginx-Konfiguration testen
sudo nginx -t
```

### MariaDB/MySQL neu starten
```bash
# MariaDB neu starten
sudo systemctl restart mariadb
# oder
sudo systemctl restart mysql

# Status prüfen
sudo systemctl status mariadb
```

## Häufige Fehler und Lösungen

### 1. DataError bei email_attachments (Dateiname zu lang)

**Fehler:**
```
sqlalchemy.exc.DataError: (pymysql.err.DataError) 
[SQL: INSERT INTO email_attachments (email_id, filename, ...)]
```

**Ursache:** Der Dateiname ist länger als 255 Zeichen (Maximallänge des `filename`-Feldes).

**Lösung:** 
1. Prüfe die Datenbankstruktur:
```bash
mysql -u teamportal -p teamportal -e "DESCRIBE email_attachments;"
```

2. Erweitere das `filename`-Feld auf VARCHAR(500) oder TEXT:
```sql
mysql -u teamportal -p teamportal
ALTER TABLE email_attachments MODIFY filename VARCHAR(500) NOT NULL;
EXIT;
```

3. Service neu starten:
```bash
sudo systemctl restart teamportal
```

### 2. Datenbankverbindungsfehler

**Fehler:** `Can't connect to MySQL server`

**Lösung:**
```bash
# MariaDB-Status prüfen
sudo systemctl status mariadb

# MariaDB neu starten
sudo systemctl restart mariadb

# Verbindung testen
mysql -u teamportal -p teamportal

# .env-Datei prüfen
sudo cat /var/www/teamportal/.env | grep DATABASE_URI
```

### 3. Permission-Fehler

**Fehler:** `Permission denied` bei Uploads oder Logs

**Lösung:**
```bash
cd /var/www/teamportal

# Berechtigungen korrigieren
sudo chown -R www-data:www-data uploads/
sudo chown -R www-data:www-data instance/
sudo chmod -R 755 uploads/
sudo chmod -R 755 instance/
```

### 4. OnlyOffice weißer Bildschirm

**Lösung:**
1. Prüfe die .env-Datei (Kommentare entfernen):
```bash
sudo cat /var/www/teamportal/.env | grep ONLYOFFICE
```

2. Prüfe Docker-Container:
```bash
sudo docker ps | grep onlyoffice
sudo docker logs onlyoffice-documentserver --tail 50
```

3. Prüfe Nginx-Konfiguration:
```bash
sudo nginx -t
sudo systemctl restart nginx
```

4. Service neu starten:
```bash
sudo systemctl restart teamportal
```

### 5. Import-Fehler oder Module nicht gefunden

**Lösung:**
```bash
cd /var/www/teamportal

# Virtual Environment aktivieren und Dependencies prüfen
source venv/bin/activate
pip install -r requirements.txt

# Service neu starten
sudo systemctl restart teamportal
```

## Logs prüfen

### Teamportal Logs
```bash
# Letzte 100 Zeilen
sudo journalctl -u teamportal -n 100 --no-pager

# Fehler nur
sudo journalctl -u teamportal -p err --no-pager

# Seit heute
sudo journalctl -u teamportal --since today --no-pager

# Echtzeit
sudo journalctl -u teamportal -f
```

### Nginx Logs
```bash
# Access Log
sudo tail -f /var/log/nginx/access.log

# Error Log
sudo tail -f /var/log/nginx/error.log
```

### MariaDB Logs
```bash
# MariaDB Error Log
sudo tail -f /var/log/mysql/error.log
```

## System neu starten

Falls alles andere fehlschlägt:
```bash
# System neu starten
sudo reboot
```

Nach dem Neustart prüfen:
```bash
# Alle Services prüfen
sudo systemctl status teamportal
sudo systemctl status nginx
sudo systemctl status mariadb
sudo docker ps
```

