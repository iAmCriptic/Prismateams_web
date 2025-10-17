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
let chatCheckInterval = null;
let lastNotificationCheck = null;
let lastChatCheck = null;
let shownNotificationIds = new Set(); // Tracke bereits angezeigte Benachrichtigungen

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

// Hintergrund-Überprüfung für Benachrichtigungen - REPARIERT
function startBackgroundNotificationCheck() {
  console.log('Service Worker: Starte reparierte Hintergrund-Überprüfung');
  
  // Chat-Nachrichten alle 10 Sekunden - aber NUR für Dashboard-Updates
  chatCheckInterval = setInterval(() => {
    checkForChatUpdates();
  }, 10000);
  
  // Erste Prüfung nach 5 Sekunden
  setTimeout(() => {
    checkForChatUpdates();
  }, 5000);
}

// Chat-Updates für Dashboard UND Benachrichtigungen
async function checkForChatUpdates() {
  try {
    console.log('Service Worker: Prüfe Chat-Updates und Benachrichtigungen');
    
    // Prüfe Chat-Count UND Benachrichtigungen
    const [chatResponse, notificationsResponse] = await Promise.all([
      fetch('/api/chat/unread-count', { credentials: 'include' }),
      fetch('/api/notifications/pending', { credentials: 'include' })
    ]);
    
    if (chatResponse.ok) {
      const data = await chatResponse.json();
      console.log(`Service Worker: ${data.count} neue Chat-Nachrichten für Dashboard`);
      
      // Sende Message an alle offenen Tabs für Dashboard-Update
      const clients = await self.clients.matchAll();
      clients.forEach(client => {
        client.postMessage({
          type: 'CHAT_UPDATE',
          count: data.count
        });
      });
    }
    
    // Prüfe auf neue Benachrichtigungen
    if (notificationsResponse.ok) {
      const data = await notificationsResponse.json();
      if (data.notifications && data.notifications.length > 0) {
        console.log(`Service Worker: ${data.notifications.length} neue Benachrichtigungen gefunden`);
        
        // Zeige jede neue Benachrichtigung
        data.notifications.forEach(notif => {
          if (!shownNotificationIds.has(notif.id)) {
            shownNotificationIds.add(notif.id);
            showNotification(notif);
          }
        });
      }
    }
    
  } catch (error) {
    console.log('Service Worker: Fehler beim Prüfen der Chat-Updates:', error);
  }
}

// Andere Benachrichtigungen alle 30 Sekunden
async function checkForOtherNotifications() {
  try {
    console.log('Service Worker: Prüfe auf andere Benachrichtigungen');
    
    const [emailResponse, calendarResponse] = await Promise.all([
      fetch('/api/email/unread-count', { credentials: 'include' }),
      fetch('/api/calendar/upcoming-count', { credentials: 'include' })
    ]);
    
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
    console.log('Service Worker: Fehler beim Prüfen der anderen Benachrichtigungen:', error);
  }
}

// Verarbeite Chat-Benachrichtigungen
function handleNewChatNotifications(notifications) {
  // Filtere nur neue Chat-Benachrichtigungen, die noch nicht angezeigt wurden
  const newNotifications = notifications.filter(notif => {
    // Prüfe ob bereits angezeigt
    if (shownNotificationIds.has(notif.id)) {
      return false;
    }
    
    // Prüfe Zeitstempel
    if (!lastChatCheck) return true;
    return new Date(notif.sent_at) > lastChatCheck;
  });
  
  if (newNotifications.length > 0) {
    console.log(`Service Worker: ${newNotifications.length} neue Chat-Benachrichtigungen gefunden`);
    lastChatCheck = new Date();
    
    // Zeige jede neue Chat-Benachrichtigung und markiere als angezeigt
    newNotifications.forEach(notif => {
      shownNotificationIds.add(notif.id);
      showNotification(notif);
    });
  }
}

// Verarbeite andere Benachrichtigungen
function handleNewNotifications(notifications) {
  // Filtere nur neue Benachrichtigungen, die noch nicht angezeigt wurden
  const newNotifications = notifications.filter(notif => {
    // Prüfe ob bereits angezeigt
    if (shownNotificationIds.has(notif.id)) {
      return false;
    }
    
    // Prüfe Zeitstempel
    if (!lastNotificationCheck) return true;
    return new Date(notif.sent_at) > lastNotificationCheck;
  });
  
  if (newNotifications.length > 0) {
    console.log(`Service Worker: ${newNotifications.length} neue Benachrichtigungen gefunden`);
    lastNotificationCheck = new Date();
    
    // Zeige jede neue Benachrichtigung und markiere als angezeigt
    newNotifications.forEach(notif => {
      shownNotificationIds.add(notif.id);
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
      credentials: 'include'
    });
    console.log(`Service Worker: Benachrichtigung ${notificationId} als gelesen markiert`);
  } catch (error) {
    console.log('Service Worker: Fehler beim Markieren als gelesen:', error);
  }
}

// Bereinige alte Benachrichtigungs-IDs (alle 5 Minuten)
setInterval(() => {
  // Entferne IDs älter als 1 Stunde
  const oneHourAgo = Date.now() - (60 * 60 * 1000);
  shownNotificationIds.forEach(id => {
    // Hier könnten wir die Zeit aus der ID extrahieren, aber für jetzt
    // begrenzen wir einfach die Anzahl der gespeicherten IDs
    if (shownNotificationIds.size > 100) {
      shownNotificationIds.clear();
    }
  });
}, 5 * 60 * 1000); // Alle 5 Minuten

// Höre auf Nachrichten vom Frontend
self.addEventListener('message', function(event) {
  if (event.data && event.data.type === 'STOP_BACKGROUND_CHECK') {
    if (notificationCheckInterval) {
      clearInterval(notificationCheckInterval);
      notificationCheckInterval = null;
    }
    if (chatCheckInterval) {
      clearInterval(chatCheckInterval);
      chatCheckInterval = null;
    }
  }
  
  // Behandle Chat-Updates vom Frontend
  if (event.data && event.data.type === 'CHAT_UPDATE') {
    console.log('Service Worker: Chat-Update erhalten:', event.data.count);
  }
});
