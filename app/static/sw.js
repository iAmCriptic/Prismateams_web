// Service Worker für Team Portal PWA - REPARIERT
const CACHE_NAME = 'team-portal-v2';
const urlsToCache = [
  '/',
  '/static/css/style.css',
  '/static/js/app.js',
  '/static/img/logo.png',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js'
];

// Globale Variablen für Benachrichtigungen
let notificationCheckInterval = null;
let shownNotificationIds = new Set();
let isOnline = navigator.onLine;

// Install Event - Cache wichtige Ressourcen
self.addEventListener('install', function(event) {
  console.log('Service Worker: Install Event');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(function(cache) {
        console.log('Service Worker: Caching wichtige Dateien');
        return cache.addAll(urlsToCache);
      })
      .catch(function(error) {
        console.log('Service Worker: Fehler beim Caching:', error);
      })
  );
  // Sofort aktivieren
  self.skipWaiting();
});

// Activate Event - Alte Caches löschen
self.addEventListener('activate', function(event) {
  console.log('Service Worker: Activate Event');
  event.waitUntil(
    caches.keys().then(function(cacheNames) {
      return Promise.all(
        cacheNames.map(function(cacheName) {
          if (cacheName !== CACHE_NAME) {
            console.log('Service Worker: Lösche alten Cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    }).then(() => {
      // Starte Benachrichtigungen nach Cache-Bereinigung
      startNotificationCheck();
    })
  );
  
  // Übernehme sofort die Kontrolle
  return self.clients.claim();
});

// Fetch Event - Cache-First Strategie mit Offline-Fallback
self.addEventListener('fetch', function(event) {
  // Nur GET-Requests cachen
  if (event.request.method !== 'GET') {
    return;
  }

  // API-Requests nicht cachen (immer online)
  if (event.request.url.includes('/api/')) {
    return;
  }

  event.respondWith(
    caches.match(event.request)
      .then(function(response) {
        // Cache hit - return cached version
        if (response) {
          console.log('Service Worker: Cache hit für:', event.request.url);
          return response;
        }

        // Cache miss - fetch from network
        console.log('Service Worker: Cache miss für:', event.request.url);
        return fetch(event.request).then(function(response) {
          // Prüfe ob die Antwort gültig ist
          if (!response || response.status !== 200 || response.type !== 'basic') {
            return response;
          }

          // Cache die Antwort für zukünftige Requests
          const responseToCache = response.clone();
          caches.open(CACHE_NAME)
            .then(function(cache) {
              cache.put(event.request, responseToCache);
            });

          return response;
        }).catch(function(error) {
          console.log('Service Worker: Fetch fehlgeschlagen:', error);
          
          // Für HTML-Seiten, zeige Offline-Seite mit freundlicher Nachricht
          if (event.request.destination === 'document') {
            return caches.match('/').then(function(cachedResponse) {
              if (cachedResponse) {
                // Modifiziere die gecachte Seite um Offline-Banner hinzuzufügen
                return cachedResponse.text().then(function(html) {
                  const modifiedHtml = html.replace(
                    '<body>',
                    '<body><div class="alert alert-warning alert-dismissible fade show" role="alert" style="margin: 0; border-radius: 0; position: fixed; top: 0; left: 0; right: 0; z-index: 9999;"><i class="bi bi-wifi-off me-2"></i><strong>Offline-Modus:</strong> Sie sind derzeit offline. Einige Funktionen sind möglicherweise eingeschränkt.<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button></div><div style="margin-top: 60px;">'
                  ).replace('</body>', '</div></body>');
                  
                  return new Response(modifiedHtml, {
                    headers: { 'Content-Type': 'text/html' }
                  });
                });
              } else {
                // Fallback Offline-Seite
                return new Response(
                  `<!DOCTYPE html>
                  <html lang="de">
                  <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Offline - Team Portal</title>
                    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
                    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css" rel="stylesheet">
                  </head>
                  <body class="bg-light">
                    <div class="container mt-5">
                      <div class="row justify-content-center">
                        <div class="col-md-6">
                          <div class="card shadow">
                            <div class="card-body text-center">
                              <i class="bi bi-wifi-off text-warning" style="font-size: 4rem;"></i>
                              <h2 class="mt-3">Offline-Modus</h2>
                              <p class="text-muted">Sie sind derzeit offline. Bitte überprüfen Sie Ihre Internetverbindung.</p>
                              <button class="btn btn-primary" onclick="window.location.reload()">
                                <i class="bi bi-arrow-clockwise me-2"></i>Erneut versuchen
                              </button>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </body>
                  </html>`,
                  { headers: { 'Content-Type': 'text/html' } }
                );
              }
            });
          }
          
          // Für andere Ressourcen, gib eine leere Antwort zurück
          return new Response('', { status: 404, statusText: 'Not Found' });
        });
      })
  );
});

// Push Notifications - Echte Push-Benachrichtigungen
self.addEventListener('push', function(event) {
  console.log('Service Worker: Push Event empfangen');
  
  let notificationData = {
    title: 'Team Portal',
    body: 'Neue Benachrichtigung',
    icon: '/static/img/logo.png',
    badge: '/static/img/logo.png',
    url: '/',
    data: {}
  };
  
  // Parse Push-Daten falls vorhanden
  if (event.data) {
    try {
      const pushData = event.data.json();
      console.log('Push-Daten empfangen:', pushData);
      notificationData = {
        title: pushData.title || 'Team Portal',
        body: pushData.body || 'Neue Benachrichtigung',
        icon: pushData.icon || '/static/img/logo.png',
        badge: pushData.badge || '/static/img/logo.png',
        url: pushData.url || '/',
        data: pushData.data || {}
      };
    } catch (e) {
      console.log('Fehler beim Parsen der Push-Daten:', e);
      notificationData.body = event.data.text() || 'Neue Benachrichtigung';
    }
  }
  
  const options = {
    body: notificationData.body,
    icon: notificationData.icon,
    badge: notificationData.badge,
    vibrate: [100, 50, 100],
    data: {
      url: notificationData.url,
      ...notificationData.data,
      dateOfArrival: Date.now()
    },
    actions: [
      {
        action: 'open',
        title: 'Öffnen',
        icon: '/static/img/logo.png'
      },
      {
        action: 'close',
        title: 'Schließen',
        icon: '/static/img/logo.png'
      }
    ],
    requireInteraction: false,
    silent: false,
    tag: `notification-${Date.now()}` // Eindeutige Tags für jede Benachrichtigung
  };

  console.log('Zeige Push-Benachrichtigung:', notificationData.title, notificationData.body);

  event.waitUntil(
    self.registration.showNotification(notificationData.title, options)
  );
});

// Notification Click Handler
self.addEventListener('notificationclick', function(event) {
  console.log('Service Worker: Notification Click', event.action);
  
  event.notification.close();

  if (event.action === 'open' || !event.action) {
    // Öffne die App oder spezifische URL
    const url = event.notification.data?.url || '/';
    
    event.waitUntil(
      clients.matchAll({ type: 'window' }).then(function(clientList) {
        // Prüfe ob bereits ein Fenster/Tab offen ist
        for (let i = 0; i < clientList.length; i++) {
          const client = clientList[i];
          if (client.url.includes(self.location.origin) && 'focus' in client) {
            // Fokussiere bestehenden Tab
            client.focus();
            client.navigate(url);
            return;
          }
        }
        
        // Öffne neuen Tab
        if (clients.openWindow) {
          return clients.openWindow(url);
        }
      })
    );
  }
});

// Background Sync für Offline-Funktionalität
self.addEventListener('sync', function(event) {
  console.log('Service Worker: Background Sync Event:', event.tag);
  
  if (event.tag === 'background-sync') {
    event.waitUntil(
      // Hier könnten Offline-Aktionen synchronisiert werden
      console.log('Background Sync: Synchronisiere Offline-Daten')
    );
  }
});

// Starte Benachrichtigungs-Check nach Aktivierung
self.addEventListener('message', function(event) {
  if (event.data && event.data.type === 'START_NOTIFICATIONS') {
    startNotificationCheck();
  }
  
  if (event.data && event.data.type === 'STOP_NOTIFICATIONS') {
    stopNotificationCheck();
  }
});

// Vereinfachte Benachrichtigungs-Überprüfung
function startNotificationCheck() {
  console.log('Service Worker: Starte Benachrichtigungs-Überprüfung');
  
  // Stoppe vorherige Intervalle
  if (notificationCheckInterval) {
    clearInterval(notificationCheckInterval);
  }
  
  // Prüfe alle 15 Sekunden auf neue Benachrichtigungen
  notificationCheckInterval = setInterval(() => {
    checkForNotifications();
  }, 15000);
  
  // Erste Prüfung nach 5 Sekunden
  setTimeout(() => {
    checkForNotifications();
  }, 5000);
}

function stopNotificationCheck() {
  console.log('Service Worker: Stoppe Benachrichtigungs-Überprüfung');
  if (notificationCheckInterval) {
    clearInterval(notificationCheckInterval);
    notificationCheckInterval = null;
  }
}

// Prüfe auf neue Benachrichtigungen
async function checkForNotifications() {
  try {
    console.log('Service Worker: Prüfe auf neue Benachrichtigungen');
    
    const response = await fetch('/api/notifications/pending', { 
      credentials: 'include',
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    });
    
    if (response.ok) {
      const data = await response.json();
      if (data.notifications && data.notifications.length > 0) {
        console.log(`Service Worker: ${data.notifications.length} neue Benachrichtigungen gefunden`);
        
        // Zeige jede neue Benachrichtigung nur einmal
        data.notifications.forEach(notif => {
          if (!shownNotificationIds.has(notif.id)) {
            shownNotificationIds.add(notif.id);
            showNotification(notif);
          }
        });
      }
    }
    
  } catch (error) {
    console.log('Service Worker: Fehler beim Prüfen der Benachrichtigungen:', error);
  }
}

// Periodic Background Sync (falls unterstützt)
if ('serviceWorker' in self && 'periodicSync' in self.registration) {
  self.addEventListener('periodicsync', function(event) {
    if (event.tag === 'notification-check') {
      event.waitUntil(checkForNotifications());
    }
  });
}

// Zeige Benachrichtigung an
function showNotification(notification) {
  const options = {
    body: notification.body,
    icon: notification.icon || '/static/img/logo.png',
    badge: '/static/img/logo.png',
    vibrate: [100, 50, 100],
    data: {
      url: notification.url || '/',
      id: notification.id,
      dateOfArrival: Date.now()
    },
    actions: [
      {
        action: 'open',
        title: 'Öffnen',
        icon: '/static/img/logo.png'
      },
      {
        action: 'close',
        title: 'Schließen',
        icon: '/static/img/logo.png'
      }
    ],
    requireInteraction: false,
    silent: false,
    tag: `notification-${notification.id}`
  };

  self.registration.showNotification(notification.title, options);
  
  // Markiere Benachrichtigung als gelesen nach 5 Sekunden
  setTimeout(() => {
    markNotificationAsRead(notification.id);
  }, 5000);
}

// Markiere Benachrichtigung als gelesen
async function markNotificationAsRead(notificationId) {
  try {
    await fetch(`/api/notifications/mark-read/${notificationId}`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    });
    console.log(`Service Worker: Benachrichtigung ${notificationId} als gelesen markiert`);
  } catch (error) {
    console.log('Service Worker: Fehler beim Markieren als gelesen:', error);
  }
}

// Bereinige alte Benachrichtigungs-IDs (alle 10 Minuten)
setInterval(() => {
  // Begrenze die Anzahl der gespeicherten IDs
  if (shownNotificationIds.size > 100) {
    shownNotificationIds.clear();
  }
}, 10 * 60 * 1000); // Alle 10 Minuten

// Service Worker ist bereit für Push-Benachrichtigungen
console.log('Service Worker: Bereit für Push-Benachrichtigungen');

// Starte lokale Benachrichtigungsprüfung als Fallback
startNotificationCheck();