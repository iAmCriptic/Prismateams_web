# Push-Benachrichtigungen Setup Guide

## Problem: "Keine aktiven Push-Subscriptions gefunden"

Wenn du die Fehlermeldung "Keine aktiven Push-Subscriptions gefunden" erhältst, bedeutet das, dass du dich noch nicht für Push-Benachrichtigungen registriert hast.

## Lösung: Schritt-für-Schritt Anleitung

### 1. Browser-Berechtigung erteilen

1. **Gehe zu Einstellungen → Benachrichtigungen**
2. **Sektion: "Browser-Berechtigungen"**
3. **Klicke auf "Push-Benachrichtigungen aktivieren"**
4. **Browser fragt nach Berechtigung → Klicke "Erlauben"**

### 2. Push-Subscription wird automatisch registriert

Nach der Berechtigung sollte automatisch eine Push-Subscription erstellt werden.

### 3. Test-Push senden

1. **Klicke auf "Test senden"**
2. **Du solltest eine Erfolgsmeldung sehen**
3. **Eine System-Benachrichtigung sollte erscheinen**

## Troubleshooting

### Problem: "Push-Benachrichtigungen aktivieren" funktioniert nicht

**Mögliche Ursachen:**
- Browser unterstützt keine Web Push API
- HTTPS erforderlich (außer localhost)
- VAPID Keys nicht konfiguriert

**Lösung:**
```bash
# Prüfe VAPID Keys
python scripts/check_vapid_keys.py

# Falls Keys fehlen:
python scripts/generate_vapid_keys.py
```

### Problem: Browser-Berechtigung wird verweigert

**Lösung:**
1. **Browser-Einstellungen öffnen**
2. **Benachrichtigungen → Team Portal**
3. **Status auf "Erlaubt" setzen**
4. **Seite neu laden**

### Problem: "VAPID Keys nicht konfiguriert"

**Lösung:**
1. **Generiere VAPID Keys:**
   ```bash
   python scripts/generate_vapid_keys.py
   ```

2. **Kopiere Keys in .env Datei:**
   ```env
   VAPID_PRIVATE_KEY=your-private-key
   VAPID_PUBLIC_KEY=your-public-key
   ```

3. **App neu starten**

## Debug-Informationen

### Push-Subscriptions prüfen

```bash
# Prüfe aktive Push-Subscriptions
python -c "
from app import create_app
from app.models.notification import PushSubscription
app = create_app()
app.app_context().push()
print('Aktive Subscriptions:', PushSubscription.query.filter_by(is_active=True).count())
"
```

### Browser-Konsole prüfen

1. **F12 → Console**
2. **Suche nach Fehlermeldungen**
3. **Prüfe ob Service Worker aktiv ist**

### Service Worker prüfen

1. **F12 → Application → Service Workers**
2. **Service Worker sollte aktiv sein**
3. **Status sollte "activated" sein**

## Erwartetes Verhalten

### Erfolgreiche Registrierung

1. **Toast-Nachricht**: "Push-Benachrichtigungen erfolgreich aktiviert!"
2. **Status-Badge**: Wechselt zu "Aktiv"
3. **Test-Push**: Funktioniert ohne Fehler

### Fehlgeschlagene Registrierung

1. **Toast-Nachricht**: Fehlermeldung mit spezifischem Grund
2. **Status-Badge**: Bleibt "Nicht registriert"
3. **Test-Push**: Zeigt Fehlermeldung

## Browser-Unterstützung

### Vollständig unterstützt
- ✅ Chrome Desktop (alle Versionen)
- ✅ Chrome Mobile (Android)
- ✅ Firefox Desktop
- ✅ Edge

### Bedingt unterstützt
- ⚠️ Safari Desktop (macOS 13+ mit Safari 16.4+)
- ⚠️ Safari Mobile (iOS 16.4+)

### Nicht unterstützt
- ❌ Internet Explorer
- ❌ Ältere Browser ohne Web Push API

## Häufige Fehler

### "Web Push API wird nicht unterstützt"
- **Ursache**: Browser unterstützt keine Web Push API
- **Lösung**: Verwende unterstützten Browser

### "Service Worker nicht aktiv"
- **Ursache**: Service Worker konnte nicht registriert werden
- **Lösung**: Prüfe HTTPS, Browser-Konsole

### "VAPID Key konnte nicht geladen werden"
- **Ursache**: Server-seitige VAPID Keys fehlen
- **Lösung**: Generiere und konfiguriere VAPID Keys

## Support

Bei anhaltenden Problemen:

1. **Prüfe Browser-Konsole** (F12 → Console)
2. **Prüfe Server-Logs** (Flask Debug-Modus)
3. **Teste in anderem Browser**
4. **Prüfe HTTPS-Verbindung**

## Test-Checkliste

- [ ] Browser unterstützt Web Push API
- [ ] HTTPS aktiviert (außer localhost)
- [ ] VAPID Keys konfiguriert
- [ ] Browser-Berechtigung erteilt
- [ ] Service Worker aktiv
- [ ] Push-Subscription registriert
- [ ] Test-Push funktioniert

