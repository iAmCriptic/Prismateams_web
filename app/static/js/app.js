// Team Portal JavaScript

// PWA Service Worker Registration
if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        navigator.serviceWorker.register('/static/sw.js')
            .then(function(registration) {
                console.log('Service Worker registriert:', registration.scope);
                
                // Starte Benachrichtigungen im Service Worker
                if (registration.active) {
                    registration.active.postMessage({ type: 'START_NOTIFICATIONS' });
                }
                
                // Prüfe auf Updates
                registration.addEventListener('updatefound', function() {
                    const newWorker = registration.installing;
                    newWorker.addEventListener('statechange', function() {
                        if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                            // Neuer Service Worker verfügbar
                            if (confirm('Eine neue Version der App ist verfügbar. Möchten Sie die Seite neu laden?')) {
                                window.location.reload();
                            }
                        }
                    });
                });
            })
            .catch(function(error) {
                console.log('Service Worker Registrierung fehlgeschlagen:', error);
            });
    });
}

// PWA Install Prompt
let deferredPrompt;
window.addEventListener('beforeinstallprompt', function(e) {
    console.log('PWA Install Prompt verfügbar');
    e.preventDefault();
    deferredPrompt = e;
    
    // Zeige Install-Button (optional)
    showInstallButton();
});

function showInstallButton() {
    // Erstelle Install-Button falls noch nicht vorhanden
    if (!document.getElementById('pwa-install-btn')) {
        const installBtn = document.createElement('button');
        installBtn.id = 'pwa-install-btn';
        installBtn.className = 'btn btn-primary position-fixed';
        installBtn.style.cssText = 'bottom: 80px; right: 20px; z-index: 1050; display: none;';
        installBtn.innerHTML = '<i class="bi bi-download me-2"></i>App installieren';
        installBtn.onclick = installPWA;
        document.body.appendChild(installBtn);
        
        // Zeige Button nach kurzer Verzögerung
        setTimeout(() => {
            installBtn.style.display = 'block';
        }, 3000);
    }
}

function installPWA() {
    if (deferredPrompt) {
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then(function(choiceResult) {
            if (choiceResult.outcome === 'accepted') {
                console.log('PWA Installation akzeptiert');
            } else {
                console.log('PWA Installation abgelehnt');
            }
            deferredPrompt = null;
            
            // Verstecke Install-Button
            const installBtn = document.getElementById('pwa-install-btn');
            if (installBtn) {
                installBtn.style.display = 'none';
            }
        });
    }
}

// PWA Install Event
window.addEventListener('appinstalled', function(evt) {
    console.log('PWA wurde installiert');
    
    // Verstecke Install-Button
    const installBtn = document.getElementById('pwa-install-btn');
    if (installBtn) {
        installBtn.style.display = 'none';
    }
});

// Push Notifications
let pushSubscription = null;

// Prüfe ob Push-Benachrichtigungen unterstützt werden
if ('serviceWorker' in navigator && 'PushManager' in window) {
    console.log('Push-Benachrichtigungen werden unterstützt');
    
    // Prüfe ob wir in einem sicheren Kontext sind
    if (location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1') {
        console.log('Sicherer Kontext erkannt, registriere Push-Subscription');
        console.log('Aktuelle URL:', location.href);
        console.log('Protokoll:', location.protocol);
        console.log('Hostname:', location.hostname);
        
        // Warte bis Service Worker bereit ist, dann registriere Push-Subscription
        navigator.serviceWorker.ready.then(function(registration) {
            console.log('Service Worker bereit, registriere Push-Subscription');
            console.log('Service Worker Registration:', registration);
            
            // Starte Push-Notification Registrierung sofort
            console.log('Starte Push-Notification Registrierung sofort...');
            console.log('DEBUG: Rufe registerPushNotifications() auf...');
            registerPushNotifications();
        }).catch(function(error) {
            console.error('Fehler beim Warten auf Service Worker:', error);
        });
        
        // Zusätzlicher Fallback: Versuche es auch nach 2 Sekunden
        setTimeout(() => {
            console.log('FALLBACK: Versuche Push-Notification Registrierung nach 2 Sekunden...');
            registerPushNotifications();
        }, 2000);
    } else {
        console.log('UNSICHERER KONTEXT: Push-Benachrichtigungen funktionieren nur mit HTTPS!');
        console.log('Aktuelle URL:', location.href);
        console.log('Protokoll:', location.protocol);
    }
} else {
    console.log('Push-Benachrichtigungen werden NICHT unterstützt');
    console.log('ServiceWorker unterstützt:', 'serviceWorker' in navigator);
    console.log('PushManager unterstützt:', 'PushManager' in window);
}

// Berechtigungs-Manager
class PermissionManager {
    constructor() {
        this.permissions = {
            notifications: 'default',
            microphone: 'default'
        };
        this.init();
    }
    
    async init() {
        // Prüfe aktuelle Berechtigungen
        await this.checkPermissions();
        
        // Zeige Berechtigungsanfragen nach kurzer Verzögerung
        setTimeout(() => {
            this.requestPermissions();
        }, 2000);
    }
    
    async checkPermissions() {
        // Prüfe Benachrichtigungsberechtigung
        if ('Notification' in window) {
            this.permissions.notifications = Notification.permission;
        }
        
        // Prüfe Mikrofon-Berechtigung
        if ('permissions' in navigator) {
            try {
                const micPermission = await navigator.permissions.query({ name: 'microphone' });
                this.permissions.microphone = micPermission.state;
            } catch (e) {
                console.log('Mikrofon-Berechtigung kann nicht geprüft werden:', e);
            }
        }
        
        console.log('Aktuelle Berechtigungen:', this.permissions);
    }
    
    async requestPermissions() {
        // Zeige Berechtigungsanfragen nur wenn nötig
        if (this.permissions.notifications === 'default') {
            await this.requestNotificationPermission();
        }
        
        // Mikrofon-Berechtigung wird erst bei Bedarf angefragt
        this.setupMicrophonePermissionRequest();
    }
    
    async requestNotificationPermission() {
        if ('Notification' in window && Notification.permission === 'default') {
            try {
                const permission = await Notification.requestPermission();
                this.permissions.notifications = permission;
                
                if (permission === 'granted') {
                    console.log('Benachrichtigungsberechtigung erteilt');
                    this.showPermissionSuccess('Benachrichtigungen', 'Sie erhalten jetzt Push-Benachrichtigungen für neue Nachrichten.');
                    
                    // Registriere Push-Subscription nach erfolgreicher Berechtigung
                    if ('serviceWorker' in navigator && 'PushManager' in window) {
                        await registerPushNotifications();
                    }
                } else {
                    console.log('Benachrichtigungsberechtigung verweigert');
                    this.showPermissionInfo('Benachrichtigungen', 'Sie können Benachrichtigungen in den Browser-Einstellungen aktivieren.');
                }
            } catch (error) {
                console.error('Fehler bei Benachrichtigungsberechtigung:', error);
            }
        }
    }
    
    async requestMicrophonePermission() {
        if ('mediaDevices' in navigator && 'getUserMedia' in navigator.mediaDevices) {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                // Stoppe den Stream sofort - wir wollten nur die Berechtigung
                stream.getTracks().forEach(track => track.stop());
                
                console.log('Mikrofon-Berechtigung erteilt');
                this.showPermissionSuccess('Mikrofon', 'Sie können jetzt Sprachnachrichten aufnehmen.');
                return true;
            } catch (error) {
                console.log('Mikrofon-Berechtigung verweigert:', error);
                this.showPermissionInfo('Mikrofon', 'Mikrofon-Zugriff ist für Sprachnachrichten erforderlich.');
                return false;
            }
        }
        return false;
    }
    
    setupMicrophonePermissionRequest() {
        // Füge Event-Listener für Mikrofon-Buttons hinzu
        document.addEventListener('click', async (event) => {
            if (event.target.matches('[data-request-microphone]') || 
                event.target.closest('[data-request-microphone]')) {
                event.preventDefault();
                await this.requestMicrophonePermission();
            }
        });
    }
    
    showPermissionSuccess(type, message) {
        this.showPermissionToast(type, message, 'success');
    }
    
    showPermissionInfo(type, message) {
        this.showPermissionToast(type, message, 'info');
    }
    
    showPermissionToast(type, message, level) {
        // Erstelle Toast-Benachrichtigung
        const toast = document.createElement('div');
        toast.className = `toast align-items-center text-white bg-${level === 'success' ? 'success' : 'info'} border-0`;
        toast.setAttribute('role', 'alert');
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">
                    <strong>${type}:</strong> ${message}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        `;
        
        // Füge Toast-Container hinzu falls nicht vorhanden
        let toastContainer = document.getElementById('toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'toast-container';
            toastContainer.className = 'toast-container position-fixed top-0 end-0 p-3';
            toastContainer.style.zIndex = '1060';
            document.body.appendChild(toastContainer);
        }
        
        toastContainer.appendChild(toast);
        
        // Zeige Toast
        const bsToast = new bootstrap.Toast(toast);
        bsToast.show();
        
        // Entferne Toast nach dem Ausblenden
        toast.addEventListener('hidden.bs.toast', () => {
            toast.remove();
        });
    }
    
    getPermissionStatus() {
        return this.permissions;
    }
}

// Initialisiere Berechtigungs-Manager
const permissionManager = new PermissionManager();

// Benachrichtigungs-Manager für lokale Benachrichtigungen
class NotificationManager {
    constructor() {
        this.checkInterval = null;
        this.lastCheck = null;
        this.init();
    }
    
    init() {
        // Prüfe alle 30 Sekunden nach neuen Benachrichtigungen
        this.startPolling();
        
        // Prüfe auch beim Fokus der Seite
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                this.checkForNotifications();
            }
        });
    }
    
    startPolling() {
        if (this.checkInterval) {
            clearInterval(this.checkInterval);
        }
        
        this.checkInterval = setInterval(() => {
            this.checkForNotifications();
        }, 30000); // Alle 30 Sekunden
        
        // Erste Prüfung nach 5 Sekunden
        setTimeout(() => {
            this.checkForNotifications();
        }, 5000);
    }
    
    async checkForNotifications() {
        try {
            const response = await fetch('/api/notifications/pending');
            if (response.ok) {
                const data = await response.json();
                this.handleNotifications(data.notifications);
            }
        } catch (error) {
            console.log('Fehler beim Prüfen der Benachrichtigungen:', error);
        }
    }
    
    handleNotifications(notifications) {
        // Filtere nur neue Benachrichtigungen
        const newNotifications = notifications.filter(notif => {
            if (!this.lastCheck) return true;
            return new Date(notif.sent_at) > this.lastCheck;
        });
        
        if (newNotifications.length > 0) {
            this.lastCheck = new Date();
            
            // Zeige lokale Browser-Benachrichtigungen
            newNotifications.forEach(notif => {
                this.showLocalNotification(notif);
            });
            
            // Aktualisiere Badge im Dashboard
            this.updateNotificationBadge(notifications.length);
        }
    }
    
    showLocalNotification(notification) {
        // Prüfe ob Browser-Benachrichtigungen erlaubt sind
        if (Notification.permission === 'granted') {
            const notif = new Notification(notification.title, {
                body: notification.body,
                icon: notification.icon || '/static/img/logo.png',
                tag: `notification-${notification.id}`,
                requireInteraction: false,
                silent: false
            });
            
            // Bei Klick zur entsprechenden Seite navigieren
            notif.onclick = () => {
                window.focus();
                if (notification.url) {
                    window.location.href = notification.url;
                }
                notif.close();
            };
            
            // Automatisch nach 5 Sekunden schließen
            setTimeout(() => {
                notif.close();
            }, 5000);
        } else {
            // Fallback: Toast-Benachrichtigung
            this.showToastNotification(notification);
        }
    }
    
    showToastNotification(notification) {
        const toast = document.createElement('div');
        toast.className = 'toast align-items-center text-white bg-primary border-0';
        toast.setAttribute('role', 'alert');
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">
                    <strong>${notification.title}</strong><br>
                    ${notification.body}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        `;
        
        // Füge Toast-Container hinzu falls nicht vorhanden
        let toastContainer = document.getElementById('toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'toast-container';
            toastContainer.className = 'toast-container position-fixed top-0 end-0 p-3';
            toastContainer.style.zIndex = '1060';
            document.body.appendChild(toastContainer);
        }
        
        toastContainer.appendChild(toast);
        
        // Zeige Toast
        const bsToast = new bootstrap.Toast(toast);
        bsToast.show();
        
        // Bei Klick zur entsprechenden Seite navigieren
        toast.addEventListener('click', () => {
            if (notification.url) {
                window.location.href = notification.url;
            }
        });
        
        // Entferne Toast nach dem Ausblenden
        toast.addEventListener('hidden.bs.toast', () => {
            toast.remove();
        });
    }
    
    updateNotificationBadge(count) {
        // Aktualisiere Badge im Dashboard
        const badge = document.querySelector('.notification-badge');
        if (badge) {
            badge.textContent = count;
            badge.style.display = count > 0 ? 'inline' : 'none';
        }
        
        // Aktualisiere auch den Chat-Badge
        const chatBadge = document.querySelector('.chat-notification-badge');
        if (chatBadge) {
            chatBadge.textContent = count;
            chatBadge.style.display = count > 0 ? 'inline' : 'none';
        }
    }
    
    stopPolling() {
        if (this.checkInterval) {
            clearInterval(this.checkInterval);
            this.checkInterval = null;
        }
    }
}

// Initialisiere Benachrichtigungs-Manager
const notificationManager = new NotificationManager();

// Service Worker ist bereit für Push-Benachrichtigungen
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.ready.then(function(registration) {
        console.log('Service Worker bereit für Push-Benachrichtigungen');
        // Starte lokale Benachrichtigungen für offene App
        registration.active.postMessage({ type: 'START_NOTIFICATIONS' });
    });
}

async function registerPushNotifications() {
    try {
        console.log('=== STARTE PUSH-NOTIFICATION REGISTRIERUNG ===');
        console.log('Starte Push-Notification Registrierung...');
        console.log('Aktuelle URL:', location.href);
        console.log('Protokoll:', location.protocol);
        console.log('Hostname:', location.hostname);
        console.log('DEBUG: registerPushNotifications() wurde aufgerufen!');
        
        console.log('DEBUG: Warte auf Service Worker ready...');
        const registration = await navigator.serviceWorker.ready;
        console.log('DEBUG: Service Worker ready erhalten!');
        console.log('Service Worker Registration:', registration);
        
        // Prüfe ob bereits eine Subscription existiert
        console.log('DEBUG: Prüfe bestehende Push-Subscription...');
        pushSubscription = await registration.pushManager.getSubscription();
        console.log('DEBUG: Push-Subscription Prüfung abgeschlossen!');
        console.log('Bestehende Push-Subscription:', pushSubscription);
        
        if (!pushSubscription) {
            console.log('DEBUG: Keine bestehende Push-Subscription gefunden, erstelle neue...');
            
            // Prüfe ob Benachrichtigungen erlaubt sind
            console.log('DEBUG: Prüfe Notification Permission...');
            console.log('Aktuelle Notification Permission:', Notification.permission);
            if (Notification.permission === 'default') {
                console.log('DEBUG: Frage nach Benachrichtigungsberechtigung...');
                const permission = await Notification.requestPermission();
                console.log('DEBUG: Benachrichtigungsberechtigung erhalten:', permission);
                if (permission !== 'granted') {
                    console.log('DEBUG: Push-Benachrichtigungen nicht erlaubt');
                    return;
                }
            } else if (Notification.permission !== 'granted') {
                console.log('DEBUG: Push-Benachrichtigungen nicht erlaubt');
                return;
            }
            
            // Erstelle neue Subscription
            console.log('DEBUG: Erstelle neue Push-Subscription...');
            const applicationServerKey = urlBase64ToUint8Array('MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEG4ECv1S2TNUvpqoXcq4hbpVrFKruYoRRc1A8NMDhmU_a597YCT1e3_61_ujJLDDEwSnkauzSkjXh_QgeMb6Nsg');
            
            console.log('DEBUG: Rufe pushManager.subscribe() auf...');
            pushSubscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: applicationServerKey
            });
            
            console.log('DEBUG: Push-Subscription erfolgreich erstellt!');
            console.log('Push-Subscription erstellt:', pushSubscription);
        } else {
            console.log('Bestehende Push-Subscription gefunden');
        }
        
        // Sende Subscription an Server
        console.log('Sende Push-Subscription an Server...');
        const serverResult = await sendSubscriptionToServer(pushSubscription);
        
        if (serverResult) {
            console.log('=== PUSH-BENACHRICHTIGUNGEN ERFOLGREICH REGISTRIERT ===');
        } else {
            console.log('=== PUSH-BENACHRICHTIGUNGEN REGISTRIERUNG FEHLGESCHLAGEN ===');
        }
        
    } catch (error) {
        console.error('=== FEHLER BEI PUSH-NOTIFICATION REGISTRIERUNG ===');
        console.error('Fehler bei Push-Notification Registrierung:', error);
        console.error('Fehler-Details:', error.message);
        console.error('Fehler-Stack:', error.stack);
        
        // Versuche es erneut nach 5 Sekunden
        setTimeout(() => {
            console.log('Versuche Push-Notification Registrierung erneut...');
            registerPushNotifications();
        }, 5000);
    }
}

function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding)
        .replace(/-/g, '+')
        .replace(/_/g, '/');
    
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    
    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}

async function sendSubscriptionToServer(subscription) {
    try {
        console.log('=== SENDE PUSH-SUBSCRIPTION AN SERVER ===');
        console.log('Sende Push-Subscription an Server:', subscription);
        console.log('Subscription Endpoint:', subscription.endpoint);
        console.log('Subscription Keys:', subscription.getKey ? {
            p256dh: subscription.getKey('p256dh') ? 'vorhanden' : 'fehlt',
            auth: subscription.getKey('auth') ? 'vorhanden' : 'fehlt'
        } : 'Keine Keys');
        
        const response = await fetch('/api/push/subscribe', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
                subscription: subscription,
                user_agent: navigator.userAgent
            })
        });
        
        console.log('Server-Response Status:', response.status);
        console.log('Server-Response Headers:', response.headers);
        
        if (response.ok) {
            console.log('Push-Subscription erfolgreich an Server gesendet');
            const result = await response.json();
            console.log('Server-Antwort:', result);
            return true;
        } else {
            console.error('Fehler beim Senden der Push-Subscription');
            const error = await response.text();
            console.error('Server-Fehler:', error);
            return false;
        }
    } catch (error) {
        console.error('=== FEHLER BEIM SENDEN DER PUSH-SUBSCRIPTION ===');
        console.error('Fehler beim Senden der Push-Subscription:', error);
        console.error('Fehler-Details:', error.message);
        return false;
    }
}

function showNotificationButton() {
    // Erstelle Benachrichtigungs-Button falls noch nicht vorhanden
    if (!document.getElementById('notification-btn')) {
        const notificationBtn = document.createElement('button');
        notificationBtn.id = 'notification-btn';
        notificationBtn.className = 'btn btn-outline-primary position-fixed';
        notificationBtn.style.cssText = 'bottom: 80px; left: 20px; z-index: 1050; display: none;';
        notificationBtn.innerHTML = '<i class="bi bi-bell me-2"></i>Benachrichtigungen';
        notificationBtn.onclick = requestNotificationPermission;
        document.body.appendChild(notificationBtn);
        
        // Zeige Button nach kurzer Verzögerung
        setTimeout(() => {
            notificationBtn.style.display = 'block';
        }, 5000);
    }
}

async function requestNotificationPermission() {
    if ('Notification' in window) {
        const permission = await Notification.requestPermission();
        
        if (permission === 'granted') {
            console.log('Benachrichtigungsberechtigung erteilt');
            
            // Verstecke Button
            const notificationBtn = document.getElementById('notification-btn');
            if (notificationBtn) {
                notificationBtn.style.display = 'none';
            }
            
            // Zeige Erfolgsmeldung
            showNotification('Benachrichtigungen aktiviert', 'Sie erhalten jetzt Push-Benachrichtigungen für neue Chat-Nachrichten.');
        } else {
            console.log('Benachrichtigungsberechtigung verweigert');
            showNotification('Benachrichtigungen deaktiviert', 'Sie können Benachrichtigungen in den Browser-Einstellungen aktivieren.');
        }
    }
}

function showNotification(title, body) {
    if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(title, {
            body: body,
            icon: '/static/img/logo.png',
            badge: '/static/img/logo.png'
        });
    }
}

document.addEventListener('DOMContentLoaded', function() {
    // Auto-dismiss alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });

    // Confirmation dialogs for delete actions
    const deleteButtons = document.querySelectorAll('[data-confirm-delete]');
    deleteButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            const message = this.getAttribute('data-confirm-delete') || 'Möchten Sie dieses Element wirklich löschen?';
            if (!confirm(message)) {
                e.preventDefault();
            }
        });
    });

    // Password visibility toggle
    const passwordToggles = document.querySelectorAll('.password-toggle');
    passwordToggles.forEach(toggle => {
        toggle.addEventListener('click', function() {
            const input = this.previousElementSibling;
            const icon = this.querySelector('i');
            
            if (input.type === 'password') {
                input.type = 'text';
                icon.classList.remove('bi-eye');
                icon.classList.add('bi-eye-slash');
            } else {
                input.type = 'password';
                icon.classList.remove('bi-eye-slash');
                icon.classList.add('bi-eye');
            }
        });
    });

    // Auto-resize textareas
    const textareas = document.querySelectorAll('textarea.auto-resize');
    textareas.forEach(textarea => {
        textarea.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
        });
    });

    // Initialize tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // File upload preview
    const fileInputs = document.querySelectorAll('input[type="file"].preview-enabled');
    fileInputs.forEach(input => {
        input.addEventListener('change', function(e) {
            const file = e.target.files[0];
            const preview = document.querySelector(this.getAttribute('data-preview-target'));
            
            if (file && preview) {
                const reader = new FileReader();
                reader.onload = function(e) {
                    if (file.type.startsWith('image/')) {
                        preview.innerHTML = `<img src="${e.target.result}" class="img-fluid rounded" alt="Preview">`;
                    } else {
                        preview.innerHTML = `<p class="text-muted"><i class="bi bi-file-earmark"></i> ${file.name}</p>`;
                    }
                };
                reader.readAsDataURL(file);
            }
        });
    });
});

// Helper function for AJAX requests
function sendAjaxRequest(url, method = 'GET', data = null) {
    return fetch(url, {
        method: method,
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        },
        body: data ? JSON.stringify(data) : null
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.json();
    });
}

// Show loading spinner
function showLoading() {
    const overlay = document.createElement('div');
    overlay.className = 'spinner-overlay';
    overlay.id = 'loading-overlay';
    overlay.innerHTML = '<div class="spinner-border text-light" role="status"><span class="visually-hidden">Loading...</span></div>';
    document.body.appendChild(overlay);
}

// Hide loading spinner
function hideLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
        overlay.remove();
    }
}

// Format date
function formatDate(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diff = now - date;
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));
    
    if (days === 0) {
        return 'Heute';
    } else if (days === 1) {
        return 'Gestern';
    } else if (days < 7) {
        return `Vor ${days} Tagen`;
    } else {
        return date.toLocaleDateString('de-DE');
    }
}

// Format file size
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}



