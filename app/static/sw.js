// Service Worker für Team Portal PWA - Serverbasiertes Push-System
// Network-First Strategie: Cache nur als Backup bei Offline-Verbindung
// __SW_CACHE_NAME__ / __SW_ASSET_VERSION__ werden von /sw.js-Route ersetzt
const CACHE_NAME = '__SW_CACHE_NAME__';
const ASSET_VERSION = '__SW_ASSET_VERSION__';
const PORTAL_INFO_CACHE_KEY = 'portal-info';
const urlsToCache = [
  '/assets/core.css',
  '/static/js/app.js',
  '/static/js/cookie-consent.js',
  '/static/img/logo.png',
  '/static/vendor/bootstrap/bootstrap.min.css',
  '/static/vendor/bootstrap-icons/bootstrap-icons.min.css',
  '/static/vendor/bootstrap/bootstrap.bundle.min.js'
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

// Offline-/Netzwerkfehler: Cache → kein Blind-Retry bei Abort, kein Caching für Streams/no-store
function networkFirstWithCache(request, fetchOptions) {
  const doFetch = fetchOptions ? fetch(request, fetchOptions) : fetch(request);
  return doFetch
    .then(function(networkResponse) {
      if (networkResponse && networkResponse.status === 200 && networkResponse.type === 'basic') {
        const contentType = (networkResponse.headers.get('Content-Type') || '').toLowerCase();
        const cacheControl = (networkResponse.headers.get('Cache-Control') || '').toLowerCase();
        if (!contentType.includes('text/event-stream') && !cacheControl.includes('no-store')) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(request, responseToCache);
          });
        }
      }
      return networkResponse;
    })
    .catch(function(err) {
      if (err && err.name === 'AbortError') {
        return Response.error();
      }
      return caches.match(request).then(function(cachedResponse) {
        if (cachedResponse) {
          return cachedResponse;
        }
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
}

// Cache-First für versionierte statische Assets (?v=...) — vermeidet SW-Overhead bei jeder Navigation
function cacheFirstWithNetwork(request) {
  return caches.match(request).then(function(cachedResponse) {
    if (cachedResponse) {
      return cachedResponse;
    }
    return fetch(request).then(function(networkResponse) {
      if (networkResponse && networkResponse.status === 200 && networkResponse.type === 'basic') {
        const responseToCache = networkResponse.clone();
        caches.open(CACHE_NAME).then(function(cache) {
          cache.put(request, responseToCache);
        });
      }
      return networkResponse;
    }).catch(function() {
      return Response.error();
    });
  });
}

const SHARE_TARGET_DB_NAME = 'prismateams-share-target';
const SHARE_TARGET_STORE = 'shares';
const SHARE_TARGET_MAX_AGE_MS = 60 * 60 * 1000;

function openShareTargetDb() {
  return new Promise(function(resolve, reject) {
    const req = indexedDB.open(SHARE_TARGET_DB_NAME, 1);
    req.onupgradeneeded = function() {
      const db = req.result;
      if (!db.objectStoreNames.contains(SHARE_TARGET_STORE)) {
        db.createObjectStore(SHARE_TARGET_STORE, { keyPath: 'id' });
      }
    };
    req.onsuccess = function() { resolve(req.result); };
    req.onerror = function() { reject(req.error); };
  });
}

async function saveShareTargetPayload(payload) {
  const db = await openShareTargetDb();
  return new Promise(function(resolve, reject) {
    const tx = db.transaction(SHARE_TARGET_STORE, 'readwrite');
    const store = tx.objectStore(SHARE_TARGET_STORE);
    const now = Date.now();
    // Alte Einträge bereinigen
    const cursorReq = store.openCursor();
    cursorReq.onsuccess = function() {
      const cursor = cursorReq.result;
      if (cursor) {
        if (!cursor.value || !cursor.value.createdAt || (now - cursor.value.createdAt) > SHARE_TARGET_MAX_AGE_MS) {
          cursor.delete();
        }
        cursor.continue();
      }
    };
    store.put(payload);
    tx.oncomplete = function() { db.close(); resolve(); };
    tx.onerror = function() { db.close(); reject(tx.error); };
  });
}

async function handleShareTargetPost(request) {
  try {
    const formData = await request.formData();
    const title = (formData.get('title') || '').toString();
    const text = (formData.get('text') || '').toString();
    const url = (formData.get('url') || '').toString();
    const rawFiles = formData.getAll('files') || [];
    const files = [];
    for (let i = 0; i < rawFiles.length; i++) {
      const item = rawFiles[i];
      if (item && typeof item === 'object' && typeof item.arrayBuffer === 'function' && (item.size > 0 || item.name)) {
        files.push({
          name: item.name || ('shared-file-' + (i + 1)),
          type: item.type || 'application/octet-stream',
          size: item.size || 0,
          lastModified: item.lastModified || Date.now(),
          blob: item
        });
      }
    }
    const shareId = Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
    await saveShareTargetPayload({
      id: shareId,
      title: title,
      text: text,
      url: url,
      files: files,
      createdAt: Date.now()
    });
    return Response.redirect('/share-target?id=' + encodeURIComponent(shareId), 303);
  } catch (err) {
    console.error('Service Worker: Fehler beim Verarbeiten von Share Target:', err);
    return Response.redirect('/share-target?error=1', 303);
  }
}

// Fetch Event - Network-First Strategie: Cache nur als Backup bei Offline
self.addEventListener('fetch', function(event) {
  const requestUrl = new URL(event.request.url);

  // Web Share Target POST abfangen und in IndexedDB zwischenspeichern
  if (
    event.request.method === 'POST' &&
    requestUrl.origin === self.location.origin &&
    requestUrl.pathname === '/share-target'
  ) {
    event.respondWith(handleShareTargetPost(event.request));
    return;
  }

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

  // API-, Streaming- (SSE/Socket.IO) und Proxy-Pfade: IMMER direkt zum Netzwerk (nie im SW abfangen/cachen)
  const acceptHeader = (event.request.headers.get('Accept') || '').toLowerCase();
  if (
    acceptHeader.includes('text/event-stream') ||
    requestUrl.pathname.startsWith('/api/') ||
    requestUrl.pathname.startsWith('/sse/') ||
    requestUrl.pathname.startsWith('/socket.io/') ||
    requestUrl.pathname.startsWith('/webdav') ||
    requestUrl.pathname === '/onlyoffice' ||
    requestUrl.pathname.startsWith('/onlyoffice/') ||
    requestUrl.pathname === '/eurooffice' ||
    requestUrl.pathname.startsWith('/eurooffice/') ||
    requestUrl.pathname.startsWith('/web-apps/') ||
    requestUrl.pathname.startsWith('/sdkjs/') ||
    requestUrl.pathname.startsWith('/sdkjs-plugins/') ||
    requestUrl.pathname.startsWith('/fonts/') ||
    requestUrl.pathname.startsWith('/cache/') ||
    requestUrl.pathname.startsWith('/doc/') ||
    requestUrl.pathname.startsWith('/excalidraw-room/') ||
    requestUrl.pathname === '/sw.js'
  ) {
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

  // Versionierte statische Assets (?v=...): Cache-First für schnelle Seitenwechsel
  if (
    (requestUrl.pathname.startsWith('/static/') || requestUrl.pathname.startsWith('/assets/')) &&
    requestUrl.searchParams.has('v')
  ) {
    event.respondWith(
      cacheFirstWithNetwork(event.request)
    );
    return;
  }

  // Für übrige statische Ressourcen (CSS, JS, Bilder): Network-First mit Cache-Backup
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
