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

// Hintergrund-Überprüfung für Benachrichtigungen
let notificationCheckInterval = null;
let lastNotificationCheck = null;

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
  
  // Starte Hintergrund-Überprüfung
  startBackgroundNotificationCheck();
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

// Push Notifications
self.addEventListener('push', function(event) {
  console.log('Service Worker: Push Event');
  
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
      notificationData = {
        title: pushData.title || 'Team Portal',
        body: pushData.body || 'Neue Benachrichtigung',
        icon: pushData.icon || '/static/img/logo.png',
        badge: pushData.icon || '/static/img/logo.png',
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
    silent: false
  };

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

// Hintergrund-Überprüfung für Benachrichtigungen
function startBackgroundNotificationCheck() {
  console.log('Service Worker: Starte Hintergrund-Überprüfung');
  
  // Prüfe alle 30 Sekunden
  notificationCheckInterval = setInterval(() => {
    checkForNotifications();
  }, 30000);
  
  // Erste Prüfung nach 5 Sekunden
  setTimeout(() => {
    checkForNotifications();
  }, 5000);
}

async function checkForNotifications() {
  try {
    console.log('Service Worker: Prüfe auf neue Benachrichtigungen');
    
    // Prüfe alle Benachrichtigungstypen parallel
    const [notificationsResponse, chatResponse, emailResponse, calendarResponse] = await Promise.all([
      fetch('/api/notifications/pending', { credentials: 'include' }),
      fetch('/api/chat/unread-count', { credentials: 'include' }),
      fetch('/api/email/unread-count', { credentials: 'include' }),
      fetch('/api/calendar/upcoming-count', { credentials: 'include' })
    ]);
    
    // Verarbeite Benachrichtigungen
    if (notificationsResponse.ok) {
      const data = await notificationsResponse.json();
      handleNewNotifications(data.notifications);
    }
    
    // Verarbeite Chat-Updates
    if (chatResponse.ok) {
      const data = await chatResponse.json();
      if (data.count > 0) {
        console.log(`Service Worker: ${data.count} neue Chat-Nachrichten`);
      }
    }
    
    // Verarbeite E-Mail-Updates
    if (emailResponse.ok) {
      const data = await emailResponse.json();
      if (data.count > 0) {
        console.log(`Service Worker: ${data.count} neue E-Mails`);
      }
    }
    
    // Verarbeite Kalender-Updates
    if (calendarResponse.ok) {
      const data = await calendarResponse.json();
      if (data.count > 0) {
        console.log(`Service Worker: ${data.count} anstehende Termine`);
      }
    }
    
  } catch (error) {
    console.log('Service Worker: Fehler beim Prüfen der Benachrichtigungen:', error);
  }
}

function handleNewNotifications(notifications) {
  // Filtere nur neue Benachrichtigungen
  const newNotifications = notifications.filter(notif => {
    if (!lastNotificationCheck) return true;
    return new Date(notif.sent_at) > lastNotificationCheck;
  });
  
  if (newNotifications.length > 0) {
    console.log(`Service Worker: ${newNotifications.length} neue Benachrichtigungen gefunden`);
    lastNotificationCheck = new Date();
    
    // Zeige jede neue Benachrichtigung
    newNotifications.forEach(notif => {
      showNotification(notif);
    });
  }
}

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
}

// Stoppe Hintergrund-Überprüfung wenn Service Worker beendet wird
self.addEventListener('message', function(event) {
  if (event.data && event.data.type === 'STOP_BACKGROUND_CHECK') {
    if (notificationCheckInterval) {
      clearInterval(notificationCheckInterval);
      notificationCheckInterval = null;
    }
  }
});
