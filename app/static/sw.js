// Service Worker für Team Portal PWA - Serverbasiertes Push-System
// Network-First Strategie: Cache nur als Backup bei Offline-Verbindung
// __SW_CACHE_NAME__ / __SW_ASSET_VERSION__ werden von /sw.js-Route ersetzt
const CACHE_NAME = '__SW_CACHE_NAME__';
const ASSET_VERSION = '__SW_ASSET_VERSION__';
const PORTAL_INFO_CACHE_KEY = 'portal-info';
const urlsToCache = [
  '/static/css/base.css',
  '/static/css/cookie-consent.css',
  '/static/js/app.js',
  '/static/js/cookie-consent.js',
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

// Client kann Skip-Waiting anfordern (Update-Prompt)
self.addEventListener('message', function(event) {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

// Install Event - Cache wichtige Ressourcen (einzeln, CDN-Fehler blockieren nicht alles)
// skipWaiting bewusst nicht hier: Client sendet SKIP_WAITING nach User-Confirm
self.addEventListener('install', function(event) {
  event.waitUntil(
    Promise.all([
      caches.open(CACHE_NAME)
        .then(function(cache) {
          return Promise.allSettled(
            urlsToCache.map(function(url) {
              return cache.add(url).catch(function(err) {
                console.warn('Service Worker: Cache übersprungen für', url, err);
              });
            })
          );
        })
        .catch(function(error) {
          console.error('Service Worker: Fehler beim Caching:', error);
        }),
      fetchAndCachePortalInfo()
    ])
  );
});

// Activate Event - Alle alten Caches verwerfen und Clients übernehmen
self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys()
      .then(function(cacheNames) {
        return Promise.all(
          cacheNames.map(function(cacheName) {
            if (cacheName !== CACHE_NAME) {
              return caches.delete(cacheName);
            }
          })
        );
      })
      .then(function() {
        return caches.open(CACHE_NAME).then(function(cache) {
          return cache.keys().then(function(keys) {
            return Promise.all(
              keys.map(function(request) {
                const url = new URL(request.url);
                if (ALWAYS_NETWORK_ROUTES.some(route => url.pathname === route || url.pathname.startsWith(route + '/'))) {
                  return cache.delete(request);
                }
              })
            );
          });
        });
      })
      .then(function() {
        return fetchAndCachePortalInfo();
      })
      .then(function() {
        return self.clients.claim();
      })
  );
});

// Offline-/Netzwerkfehler: Cache → erneuter Fetch — kein Fake-503 für Scripts/CSS
function networkFirstWithCache(request, fetchOptions) {
  const doFetch = fetchOptions ? fetch(request, fetchOptions) : fetch(request);
  return doFetch
    .then(function(networkResponse) {
      if (networkResponse && networkResponse.status === 200 && networkResponse.type === 'basic') {
        const responseToCache = networkResponse.clone();
        caches.open(CACHE_NAME).then(function(cache) {
          cache.put(request, responseToCache);
        });
      }
      return networkResponse;
    })
    .catch(function() {
      return caches.match(request).then(function(cachedResponse) {
        if (cachedResponse) {
          return cachedResponse;
        }
        // Server oft noch erreichbar (z.B. nach Abort) — normaler Retry
        return fetch(request).catch(function() {
          if (request.mode === 'navigate' || request.destination === 'document') {
            return new Response('Offline', {
              status: 503,
              statusText: 'Service Unavailable',
              headers: { 'Content-Type': 'text/plain; charset=utf-8' }
            });
          }
          // Kein Fake-HTTP-Status für Assets (vermeidet ERR_ABORTED 503)
          return Response.error();
        });
      });
    });
}

// Fetch Event - Network-First Strategie: Cache nur als Backup bei Offline
self.addEventListener('fetch', function(event) {
  const requestUrl = new URL(event.request.url);
  
  // Nur GET-Requests behandeln
  if (event.request.method !== 'GET') {
    return;
  }

  // Nur http(s), same-origin oder bekannte CDN-URLs — rest dem Browser lassen
  const isSameOrigin = requestUrl.origin === self.location.origin;
  const isCachedCdn = urlsToCache.some(function(u) { return u === event.request.url || event.request.url.startsWith(u.split('?')[0]); });
  if (!requestUrl.protocol.startsWith('http') || (!isSameOrigin && !isCachedCdn)) {
    return;
  }

  // Spezieller Handler für Portal-Info API: Immer vom Netzwerk holen und aktualisieren
  if (requestUrl.pathname === '/api/portal-info') {
    event.respondWith(networkFirstWithCache(event.request));
    return;
  }

  // API-Requests: IMMER direkt zum Netzwerk, nie cachen
  if (event.request.url.includes('/api/')) {
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
      networkFirstWithCache(event.request, { cache: 'no-store' })
    );
    return;
  }

  // Für statische Ressourcen (CSS, JS, Bilder): Network-First mit Cache-Backup
  event.respondWith(
    networkFirstWithCache(event.request)
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

// Background Sync (Cache/Netz — keine Offline-Ausleihen)
self.addEventListener('sync', function(event) {
  if (event.tag === 'background-sync') {
    event.waitUntil(Promise.resolve());
  }
});
