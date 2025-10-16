// Service Worker für Team Portal PWA
const CACHE_NAME = 'team-portal-v1';
const urlsToCache = [
  '/',
  '/static/css/style.css',
  '/static/js/app.js',
  '/static/img/logo.png',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js'
];

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
    })
  );
});

// Fetch Event - Cache-First Strategie
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
          
          // Für HTML-Seiten, zeige Offline-Seite
          if (event.request.destination === 'document') {
            return caches.match('/') || new Response(
              '<!DOCTYPE html><html><head><title>Offline - Team Portal</title></head><body><h1>Sie sind offline</h1><p>Bitte überprüfen Sie Ihre Internetverbindung.</p></body></html>',
              { headers: { 'Content-Type': 'text/html' } }
            );
          }
          
          // Für andere Ressourcen, gib eine leere Antwort zurück
          return new Response('', { status: 404, statusText: 'Not Found' });
        });
      })
  );
});

// Background Sync für Offline-Funktionalität
self.addEventListener('sync', function(event) {
  console.log('Service Worker: Background Sync Event:', event.tag);
  
  if (event.tag === 'background-sync') {
    event.waitUntil(
      // Hier könnten Offline-Aktionen synchronisiert werden
      // z.B. gespeicherte Chat-Nachrichten senden
      console.log('Background Sync: Synchronisiere Offline-Daten')
    );
  }
});

// Push Notifications (für zukünftige Erweiterungen)
self.addEventListener('push', function(event) {
  console.log('Service Worker: Push Event');
  
  const options = {
    body: event.data ? event.data.text() : 'Neue Benachrichtigung',
    icon: '/static/img/logo.png',
    badge: '/static/img/logo.png',
    vibrate: [100, 50, 100],
    data: {
      dateOfArrival: Date.now(),
      primaryKey: 1
    },
    actions: [
      {
        action: 'explore',
        title: 'Öffnen',
        icon: '/static/img/logo.png'
      },
      {
        action: 'close',
        title: 'Schließen',
        icon: '/static/img/logo.png'
      }
    ]
  };

  event.waitUntil(
    self.registration.showNotification('Team Portal', options)
  );
});

// Notification Click Handler
self.addEventListener('notificationclick', function(event) {
  console.log('Service Worker: Notification Click');
  
  event.notification.close();

  if (event.action === 'explore') {
    // Öffne die App
    event.waitUntil(
      clients.openWindow('/')
    );
  }
});
