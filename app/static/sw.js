// Service Worker für Team Portal PWA - Serverbasiertes Push-System
// Network-First Strategie: Cache nur als Backup bei Offline-Verbindung
const CACHE_NAME = 'team-portal-v7';
const PORTAL_INFO_CACHE_KEY = 'portal-info';
const urlsToCache = [
  '/static/css/style.css',
  '/static/js/app.js',
  '/static/img/logo.png',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js'
];

// Routen, die IMMER frisch geladen werden sollen (nie aus Cache)
const ALWAYS_NETWORK_ROUTES = [
  '/inventory/',
  '/inventory/borrow-scanner',
  '/inventory/statistics',
  '/inventory/stock',
  '/inventory/dashboard'
];

// Portal-Informationen abrufen und cachen
async function fetchAndCachePortalInfo() {
  try {
    const response = await fetch('/api/portal-info');
    if (response.ok) {
      const portalInfo = await response.json();
      // Portal-Infos im Cache speichern
      const cache = await caches.open(CACHE_NAME);
      await cache.put(
        new Request('/api/portal-info'),
        new Response(JSON.stringify(portalInfo), {
          headers: { 'Content-Type': 'application/json' }
        })
      );
      return portalInfo;
    }
  } catch (error) {
    console.error('Service Worker: Fehler beim Abrufen der Portal-Infos:', error);
  }
  return null;
}

// Gecachte Portal-Informationen abrufen
async function getPortalInfo() {
  try {
    const cache = await caches.open(CACHE_NAME);
    const cachedResponse = await cache.match('/api/portal-info');
    if (cachedResponse) {
      return await cachedResponse.json();
    }
  } catch (error) {
    console.error('Service Worker: Fehler beim Abrufen der gecachten Portal-Infos:', error);
  }
  // Fallback zu Standard-Werten
  return {
    name: 'Prismateams',
    logo: '/static/img/logo.png'
  };
}

// Install Event - Cache wichtige Ressourcen
self.addEventListener('install', function(event) {
  event.waitUntil(
    Promise.all([
      caches.open(CACHE_NAME)
        .then(function(cache) {
          return cache.addAll(urlsToCache);
        })
        .catch(function(error) {
          console.error('Service Worker: Fehler beim Caching:', error);
        }),
      fetchAndCachePortalInfo()  // Portal-Infos beim Install abrufen
    ])
  );
  // Sofort aktivieren
  self.skipWaiting();
});

// Activate Event - Alte Caches löschen
self.addEventListener('activate', function(event) {
  event.waitUntil(
    Promise.all([
      caches.keys().then(function(cacheNames) {
        return Promise.all(
          cacheNames.map(function(cacheName) {
            if (cacheName !== CACHE_NAME) {
              console.log('Lösche alten Cache:', cacheName);
              return caches.delete(cacheName);
            }
          })
        );
      }).then(function() {
        // Entferne auch alte HTML-Caches für Inventory-Routen, die Probleme verursachen könnten
        return caches.open(CACHE_NAME).then(function(cache) {
          return cache.keys().then(function(keys) {
            return Promise.all(
              keys.map(function(request) {
                const url = new URL(request.url);
                // Entferne gecachte HTML-Seiten für Inventory-Routen
                if (ALWAYS_NETWORK_ROUTES.some(route => url.pathname === route || url.pathname.startsWith(route + '/'))) {
                  console.log('Entferne gecachte Route:', url.pathname);
                  return cache.delete(request);
                }
              })
            );
          });
        });
      }),
      // Portal-Infos beim Aktivieren aktualisieren
      fetchAndCachePortalInfo()
    ])
  );
  
  // Übernehme sofort die Kontrolle
  return self.clients.claim();
});

// Fetch Event - Network-First Strategie: Cache nur als Backup bei Offline
self.addEventListener('fetch', function(event) {
  const requestUrl = new URL(event.request.url);
  
  // Nur GET-Requests behandeln
  if (event.request.method !== 'GET') {
    return;
  }

  // Spezieller Handler für Portal-Info API: Immer vom Netzwerk holen und aktualisieren
  if (requestUrl.pathname === '/api/portal-info') {
    event.respondWith(
      fetch(event.request)
        .then(function(response) {
          if (response && response.status === 200) {
            // Cache aktualisieren
            const responseToCache = response.clone();
            caches.open(CACHE_NAME).then(function(cache) {
              cache.put(event.request, responseToCache);
            });
          }
          return response;
        })
        .catch(function(error) {
          // Bei Netzwerkfehler: Fallback auf Cache
          return caches.match(event.request).then(function(cachedResponse) {
            if (cachedResponse) {
              return cachedResponse;
            }
            throw error;
          });
        })
    );
    return;
  }

  // API-Requests und POST/PUT/DELETE: IMMER direkt zum Netzwerk, nie cachen
  if (event.request.url.includes('/api/') || 
      event.request.method !== 'GET') {
    return;
  }
  
  // Ignoriere ungültige URLs (mit undefined, null, etc.)
  if (requestUrl.pathname.includes('undefined') || 
      requestUrl.pathname.includes('null') ||
      requestUrl.pathname.includes('NaN')) {
    return; // Lass Browser den Fehler selbst behandeln
  }

  // Prüfe ob Route immer frisch geladen werden soll
  const shouldAlwaysUseNetwork = ALWAYS_NETWORK_ROUTES.some(route => {
    return requestUrl.pathname === route || requestUrl.pathname.startsWith(route + '/');
  });

  // Für HTML-Dokumente und dynamische Routen: Network-First (immer frisch)
  if (event.request.destination === 'document' || shouldAlwaysUseNetwork) {
    event.respondWith(
      fetch(event.request, {
        cache: 'no-store' // Browser-Cache ignorieren, immer frisch laden
      })
        .then(function(networkResponse) {
          // Nur bei erfolgreicher Antwort cachen (als Backup für Offline)
          if (networkResponse && networkResponse.status === 200 && networkResponse.type === 'basic') {
            const responseToCache = networkResponse.clone();
            caches.open(CACHE_NAME).then(function(cache) {
              cache.put(event.request, responseToCache);
            });
          }
          return networkResponse;
        })
        .catch(function(error) {
          // Nur bei Netzwerkfehler: Fallback auf Cache (Offline-Modus)
          console.log('Network-Fehler, verwende Cache:', requestUrl.pathname);
          return caches.match(event.request).then(function(cachedResponse) {
            if (cachedResponse) {
              return cachedResponse;
            }
            // Kein Cache verfügbar - zeige Offline-Seite oder Fehler
            throw error;
          });
        })
    );
    return;
  }

  // Für statische Ressourcen (CSS, JS, Bilder): Network-First mit Cache-Backup
  event.respondWith(
    fetch(event.request, {
      cache: 'reload' // Browser-Cache neu validieren
    })
      .then(function(networkResponse) {
        // Nur bei erfolgreicher Antwort cachen
        if (networkResponse && networkResponse.status === 200 && networkResponse.type === 'basic') {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(event.request, responseToCache);
          });
        }
        return networkResponse;
      })
      .catch(function(error) {
        // Bei Netzwerkfehler: Fallback auf Cache
        return caches.match(event.request).then(function(cachedResponse) {
          if (cachedResponse) {
            return cachedResponse;
          }
          throw error;
        });
      })
  );
});

// Push Notifications - Serverbasiertes Push-System
self.addEventListener('push', function(event) {
  event.waitUntil(
    (async function() {
      // Portal-Infos abrufen (zuerst aus Cache, dann aktualisieren)
      const portalInfo = await getPortalInfo();
      
      // Portal-Infos im Hintergrund aktualisieren
      fetchAndCachePortalInfo().catch(() => {
        // Fehler ignorieren, verwende gecachte Infos
      });
      
      let notificationData = {
        title: portalInfo.name || 'Prismateams',
        body: 'Neue Benachrichtigung',
        icon: portalInfo.logo || '/static/img/logo.png',
        badge: portalInfo.logo || '/static/img/logo.png',
        url: '/',
        data: {}
      };
      
      // Parse Push-Daten vom Server
      if (event.data) {
        try {
          const pushData = event.data.json();
          notificationData = {
            title: pushData.title || portalInfo.name || 'Prismateams',
            body: pushData.body || 'Neue Benachrichtigung',
            icon: pushData.icon || portalInfo.logo || '/static/img/logo.png',
            badge: pushData.badge || portalInfo.logo || '/static/img/logo.png',
            url: pushData.url || '/',
            data: pushData.data || {}
          };
        } catch (e) {
          console.error('Fehler beim Parsen der Push-Daten:', e);
          notificationData.body = event.data.text() || 'Neue Benachrichtigung';
        }
      }
      
      const defaultIcon = portalInfo.logo || '/static/img/logo.png';
      
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
            icon: defaultIcon
          },
          {
            action: 'close',
            title: 'Schließen',
            icon: defaultIcon
          }
        ],
        requireInteraction: false,
        silent: false,
        tag: `notification-${Date.now()}`
      };

      await self.registration.showNotification(notificationData.title, options);
    })()
  );
});

// Notification Click Handler
self.addEventListener('notificationclick', function(event) {
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
  if (event.tag === 'background-sync') {
    event.waitUntil(
      // Hier könnten Offline-Aktionen synchronisiert werden
      Promise.resolve()
    );
  }
  
  // Background Sync für Inventory-Ausleihen
  if (event.tag === 'sync-inventory-borrow') {
    event.waitUntil(
      syncInventoryBorrows()
    );
  }
});

// Inventory-spezifische Offline-Funktionalität
async function syncInventoryBorrows() {
  // Synchronisiere ausstehende Ausleihen aus IndexedDB
  // Diese Funktion kann erweitert werden, um Offline-Ausleihen zu synchronisieren
  try {
    // TODO: Implementierung für Offline-Ausleihen
    console.log('Synchronisiere Inventory-Ausleihen...');
  } catch (error) {
    console.error('Fehler bei Inventory-Synchronisation:', error);
  }
}