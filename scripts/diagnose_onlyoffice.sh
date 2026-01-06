#!/bin/bash
# OnlyOffice Diagnose Script
# Dieses Skript testet, ob OnlyOffice korrekt konfiguriert ist

echo "=== OnlyOffice Diagnose ==="
echo ""

# Test 1: Prüfe ob OnlyOffice Container läuft
echo "1. Prüfe OnlyOffice Docker Container..."
if sudo docker ps | grep -q onlyoffice; then
    echo "   ✓ OnlyOffice Container läuft"
    sudo docker ps | grep onlyoffice
else
    echo "   ✗ OnlyOffice Container läuft NICHT"
    echo "   Starten Sie OnlyOffice mit: sudo docker start onlyoffice-documentserver"
fi
echo ""

# Test 2: Prüfe ob Port 8080 erreichbar ist
echo "2. Prüfe Port 8080 (direkt)..."
if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/welcome/ | grep -q "200"; then
    echo "   ✓ OnlyOffice ist auf Port 8080 erreichbar"
    echo "   Welcome-Seite: http://127.0.0.1:8080/welcome/"
else
    echo "   ✗ OnlyOffice ist NICHT auf Port 8080 erreichbar"
    echo "   Prüfen Sie: sudo docker logs onlyoffice-documentserver"
fi
echo ""

# Test 3: Prüfe Nginx-Konfiguration
echo "3. Prüfe Nginx-Konfiguration..."
if sudo nginx -t 2>&1 | grep -q "successful"; then
    echo "   ✓ Nginx-Konfiguration ist gültig"
else
    echo "   ✗ Nginx-Konfiguration hat Fehler:"
    sudo nginx -t
fi
echo ""

# Test 4: Prüfe ob /onlyoffice Location existiert
echo "4. Prüfe Nginx /onlyoffice Location..."
if grep -q "location /onlyoffice" /etc/nginx/sites-available/teamportal 2>/dev/null; then
    echo "   ✓ /onlyoffice Location gefunden"
    # Prüfe auf trailing slash Problem
    if grep -A 1 "location /onlyoffice" /etc/nginx/sites-available/teamportal | grep -q "proxy_pass http://127.0.0.1:8080/"; then
        echo "   ⚠ WARNUNG: proxy_pass hat einen trailing slash - das kann Probleme verursachen!"
        echo "   Korrigieren Sie zu: proxy_pass http://127.0.0.1:8080;"
    else
        echo "   ✓ proxy_pass ist korrekt (kein trailing slash)"
    fi
else
    echo "   ✗ /onlyoffice Location NICHT gefunden in Nginx-Konfiguration"
fi
echo ""

# Test 5: Prüfe ob OnlyOffice API über Nginx erreichbar ist
echo "5. Prüfe OnlyOffice API über Nginx..."
API_URL="http://192.168.188.142/onlyoffice/web-apps/apps/api/documents/api.js"
RESPONSE=$(curl -s -w "\n%{http_code}" "$API_URL" 2>/dev/null)
HTTP_CODE=$(echo "$RESPONSE" | tail -n 1)
CONTENT=$(echo "$RESPONSE" | head -n -1)

if [ "$HTTP_CODE" = "200" ]; then
    # Prüfe ob es JavaScript ist
    if echo "$CONTENT" | head -n 1 | grep -qE "(var |function |!function|\(function)"; then
        echo "   ✓ OnlyOffice API ist erreichbar und liefert JavaScript"
    elif echo "$CONTENT" | grep -qi "<html"; then
        echo "   ✗ OnlyOffice API liefert HTML statt JavaScript!"
        echo "   Das ist das Problem! Die API-Datei wird als HTML-Fehlerseite zurückgegeben."
        echo "   Mögliche Ursachen:"
        echo "   - Nginx wurde nicht neu geladen: sudo systemctl reload nginx"
        echo "   - OnlyOffice läuft nicht: sudo docker ps | grep onlyoffice"
        echo "   - Proxy-Pass ist falsch konfiguriert"
    else
        echo "   ⚠ OnlyOffice API ist erreichbar, aber Inhalt ist unklar"
        echo "   Erste Zeile: $(echo "$CONTENT" | head -n 1 | cut -c1-80)"
    fi
else
    echo "   ✗ OnlyOffice API ist NICHT erreichbar (HTTP $HTTP_CODE)"
fi
echo ""

# Test 6: Prüfe Nginx Status
echo "6. Prüfe Nginx Status..."
if systemctl is-active --quiet nginx; then
    echo "   ✓ Nginx läuft"
    echo "   Nginx wurde zuletzt neu geladen: $(systemctl show nginx --property=ActiveEnterTimestamp --value)"
else
    echo "   ✗ Nginx läuft NICHT"
fi
echo ""

# Zusammenfassung
echo "=== Zusammenfassung ==="
echo "Wenn OnlyOffice nicht funktioniert:"
echo "1. Stellen Sie sicher, dass OnlyOffice läuft: sudo docker ps | grep onlyoffice"
echo "2. Prüfen Sie die Nginx-Konfiguration: sudo nano /etc/nginx/sites-available/teamportal"
echo "3. Laden Sie Nginx neu: sudo nginx -t && sudo systemctl reload nginx"
echo "4. Prüfen Sie die OnlyOffice-Logs: sudo docker logs onlyoffice-documentserver"
echo ""

