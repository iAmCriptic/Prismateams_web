// Service Worker für Team Portal PWA - Serverbasiertes Push-System
const CACHE_NAME = 'team-portal-v5';
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

  // Für HTML-Dokumente: Network-First, damit dynamische Seiten (z. B. Termine)
  // nach Aktionen wie Zusagen/Absagen sofort aktualisiert werden.
  if (event.request.destination === 'document') {
    event.respondWith(
      fetch(event.request)
        .then(function(networkResponse) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(event.request, responseToCache);
          });
          return networkResponse;
        })
        .catch(function() {
          return caches.match(event.request);
        })
    );
    return;
  }

  // Für andere GET-Requests: Cache-First Strategie
  event.respondWith(
    caches.match(event.request)
      .then(function(response) {
        if (response) {
          console.log('Service Worker: Cache hit für:', event.request.url);
          return response;
        }
        console.log('Service Worker: Cache miss für:', event.request.url);
        return fetch(event.request).then(function(networkResponse) {
          if (!networkResponse || networkResponse.status !== 200 || networkResponse.type !== 'basic') {
            return networkResponse;
          }
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(event.request, responseToCache);
          });
          return networkResponse;
        });
      })
  );
});

// Push Notifications - Serverbasiertes Push-System
self.addEventListener('push', function(event) {
  console.log('Service Worker: Push Event empfangen');
  
  let notificationData = {
    title: 'Prismateams',
    body: 'Neue Benachrichtigung',
    icon: '/static/img/logo.png',
    badge: '/static/img/logo.png',
    url: '/',
    data: {}
  };
  
  // Parse Push-Daten vom Server
  if (event.data) {
    try {
      const pushData = event.data.json();
      console.log('Server Push-Daten empfangen:', pushData);
      notificationData = {
        title: pushData.title || 'Prismateams',
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
    tag: `notification-${Date.now()}`
  };

  console.log('Zeige Server-Push-Benachrichtigung:', notificationData.title, notificationData.body);

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

// Service Worker ist bereit für Server-Push-Benachrichtigungen
console.log('Service Worker: Bereit für Server-Push-Benachrichtigungen');
console.log('Service Worker: Polling-System entfernt - nur noch Server-Push');