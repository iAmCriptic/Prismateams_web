# Test-Push-Benachrichtigungen

## Übersicht

Das serverbasierte Push-Benachrichtigungssystem ermöglicht es, Test-Push-Benachrichtigungen zu senden, um die Funktionalität zu überprüfen.

## Voraussetzungen

### 1. VAPID Keys konfiguriert

```bash
# Prüfe VAPID Keys
python scripts/check_vapid_keys.py
```

Falls Keys fehlen:
```bash
# Generiere neue VAPID Keys
python scripts/generate_vapid_keys.py
```

### 2. Push-Subscription registriert

Der Benutzer muss sich für Push-Benachrichtigungen registriert haben:
- Browser-Berechtigung für Benachrichtigungen erteilt
- Push-Subscription beim Server registriert

## Test-Push senden

### Über die Benutzeroberfläche

1. **Einstellungen öffnen**
   - Gehe zu: Einstellungen → Benachrichtigungen
   - Sektion: "Browser-Berechtigungen"

2. **Push-Subscription aktivieren**
   - Klicke auf "Push-Benachrichtigungen aktivieren"
   - Erteile Browser-Berechtigung wenn gefragt

3. **Test-Push senden**
   - Klicke auf "Test senden"
   - Du solltest eine Toast-Benachrichtigung mit dem Ergebnis sehen

### Über die API

```bash
# Test-Push über API senden
curl -X POST http://localhost:5000/api/push/test \
  -H "Content-Type: application/json" \
  -b "session_cookie=your_session_cookie"
```

### Über Python Script

```python
from app.utils.notifications import send_push_notification

# Test-Push an User ID 1
send_push_notification(
    user_id=1,
    title="Test-Benachrichtigung",
    body="Dies ist eine Test-Push-Benachrichtigung.",
    url="/dashboard/"
)
```

## Fehlerbehandlung

### "Keine aktiven Push-Subscriptions gefunden"

**Problem**: Benutzer hat sich nicht für Push-Benachrichtigungen registriert.

**Lösung**:
1. Gehe zu Einstellungen → Benachrichtigungen
2. Klicke "Push-Benachrichtigungen aktivieren"
3. Erteile Browser-Berechtigung
4. Versuche Test-Push erneut

### "VAPID Keys nicht konfiguriert"

**Problem**: Server-seitige VAPID Keys fehlen.

**Lösung**:
```bash
# Generiere VAPID Keys
python scripts/generate_vapid_keys.py

# Prüfe Konfiguration
python scripts/check_vapid_keys.py

# App neu starten
```

### "Fehler beim Senden der Test-Benachrichtigung"

**Mögliche Ursachen**:
1. **VAPID Keys falsch konfiguriert**
   - Prüfe .env Datei
   - Starte App neu

2. **Push-Subscription ungültig**
   - Browser hat Subscription widerrufen
   - Registriere Push-Subscription erneut

3. **Netzwerk-Probleme**
   - Prüfe Internetverbindung
   - Prüfe Firewall-Einstellungen

## Debug-Informationen

### Browser-Entwicklertools

1. **Service Worker prüfen**
   - F12 → Application → Service Workers
   - Service Worker sollte aktiv sein

2. **Push-Subscription prüfen**
   - F12 → Application → Storage → Push Messaging
   - Subscription sollte vorhanden sein

3. **Console-Logs prüfen**
   - F12 → Console
   - Suche nach Push-bezogenen Fehlern

### Server-Logs prüfen

```bash
# Flask-App mit Debug-Logging starten
export FLASK_DEBUG=1
python app.py
```

### Push-Subscription Status prüfen

```python
from app.models.notification import PushSubscription

# Alle aktiven Subscriptions
subscriptions = PushSubscription.query.filter_by(is_active=True).all()
print(f"Aktive Subscriptions: {len(subscriptions)}")

# Subscriptions für bestimmten User
user_subscriptions = PushSubscription.query.filter_by(
    user_id=1, 
    is_active=True
).all()
print(f"User 1 Subscriptions: {len(user_subscriptions)}")
```

## Erwartete Verhalten

### Erfolgreicher Test

1. **Toast-Benachrichtigung**: "Test-Benachrichtigung erfolgreich gesendet an X Gerät(e)"
2. **Browser-Benachrichtigung**: System-Benachrichtigung erscheint
3. **Server-Log**: "Push-Benachrichtigung erfolgreich gesendet"

### Fehlgeschlagener Test

1. **Toast-Benachrichtigung**: Fehlermeldung mit spezifischem Grund
2. **Keine Browser-Benachrichtigung**
3. **Server-Log**: Fehler-Details

## Häufige Probleme

### Safari-spezifische Probleme

- **Safari 16.4+ erforderlich** (macOS Ventura+)
- **HTTPS erforderlich** für Web Push
- **VAPID Keys müssen korrekt sein**

### Chrome-spezifische Probleme

- **Service Worker muss aktiv sein**
- **Push-Subscription muss gültig sein**
- **Browser-Berechtigung muss erteilt sein**

### Mobile Chrome

- **Background Sync** muss unterstützt werden
- **Service Worker** läuft auch bei geschlossenem Browser
- **Battery-Optimierungen** können Push blockieren

## Monitoring

### Push-Subscription Status

```sql
-- Aktive Subscriptions prüfen
SELECT user_id, COUNT(*) as subscription_count 
FROM push_subscriptions 
WHERE is_active = 1 
GROUP BY user_id;
```

### Fehlerhafte Subscriptions bereinigen

```python
from app.utils.notifications import cleanup_inactive_subscriptions

# Bereinige inaktive Subscriptions
cleanup_inactive_subscriptions()
```

## Erweiterte Tests

### Mehrere Geräte testen

1. **Desktop Chrome**: Standard-Test
2. **Mobile Chrome**: Background-Push testen
3. **Safari Desktop**: VAPID-basierter Push
4. **Geschlossener Browser**: Push sollte trotzdem ankommen

### Performance-Tests

```python
import time
from app.utils.notifications import send_push_notification

# Test mit vielen Subscriptions
start_time = time.time()
success = send_push_notification(
    user_id=1,
    title="Performance Test",
    body="Test mit vielen Subscriptions"
)
end_time = time.time()

print(f"Push gesendet in {end_time - start_time:.2f} Sekunden")
```

## Support

Bei Problemen:

1. **Prüfe VAPID Keys**: `python scripts/check_vapid_keys.py`
2. **Prüfe Browser-Konsole**: F12 → Console
3. **Prüfe Server-Logs**: Flask Debug-Modus
4. **Teste Push-Subscription**: Einstellungen → Benachrichtigungen

