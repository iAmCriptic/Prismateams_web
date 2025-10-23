// Team Portal JavaScript

// Status-Meldung beim Laden der Seite
function showStatusInfo() {
    const pushSupported = 'serviceWorker' in navigator && 'PushManager' in window;
    const pushActive = pushSupported && Notification.permission === 'granted';
    const connectionStatus = navigator.onLine ? 'Vorhanden' : 'Getrennt';
    
    console.log('--- Infos ---');
    console.log(`Push Benachrichtigungen: ${pushSupported ? (pushActive ? 'Aktiv' : 'Verfügbar') : 'Nicht Unterstützt'}`);
    console.log(`Verbindung: ${connectionStatus}`);
    console.log('--- Infos ---');
}

// PWA Service Worker Registration
if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        navigator.serviceWorker.register('/static/sw.js')
            .then(function(registration) {
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
                // Nur bei echten Fehlern loggen
                console.error('Service Worker Registrierung fehlgeschlagen:', error);
            });
    });
}

// PWA Install Prompt
let deferredPrompt;
window.addEventListener('beforeinstallprompt', function(e) {
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
    // Prüfe ob wir in einem sicheren Kontext sind
    if (location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1') {
        // Warte bis Service Worker bereit ist, dann registriere Push-Subscription
        navigator.serviceWorker.ready.then(function(registration) {
            registerPushNotifications();
        }).catch(function(error) {
            console.error('Fehler beim Warten auf Service Worker:', error);
        });
        
        // Zusätzlicher Fallback: Versuche es auch nach 2 Sekunden
        setTimeout(() => {
            registerPushNotifications();
        }, 2000);
    }
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
        
        // Berechtigungen werden still geprüft
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
                    this.showPermissionSuccess('Benachrichtigungen', 'Sie erhalten jetzt Push-Benachrichtigungen für neue Nachrichten.');
                    
                    // Registriere Push-Subscription nach erfolgreicher Berechtigung
                    if ('serviceWorker' in navigator && 'PushManager' in window) {
                        await registerPushNotifications();
                    }
                } else {
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
                
                this.showPermissionSuccess('Mikrofon', 'Sie können jetzt Sprachnachrichten aufnehmen.');
                return true;
            } catch (error) {
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

// Serverbasiertes Push-Benachrichtigungssystem
class ServerPushManager {
    constructor() {
        this.pushStatus = null;
        this.init();
    }
    
    init() {
        // Prüfe Push-Status beim Laden
        this.checkPushStatus();
        
        // Setup Event Listeners für Push-Buttons
        this.setupPushEventListeners();
    }
    
    async checkPushStatus() {
        if (!this.isPushSupported()) {
            this.updatePushStatusUI({ supported: false, subscribed: false, permission: 'denied' });
            return;
        }
        
        const permission = Notification.permission;
        let subscribed = false;
        
        if (permission === 'granted') {
            try {
                const registration = await navigator.serviceWorker.ready;
                const subscription = await registration.pushManager.getSubscription();
                subscribed = !!subscription;
            } catch (error) {
                console.error('Fehler beim Prüfen des Push-Status:', error);
            }
        }
        
        const status = {
            supported: true,
            subscribed: subscribed,
            permission: permission
        };
        
        this.pushStatus = status;
        this.updatePushStatusUI(status);
        return status;
    }
    
    isPushSupported() {
        return 'serviceWorker' in navigator && 'PushManager' in window;
    }
    
    async registerPushNotifications() {
        if (!this.isPushSupported()) {
            console.log('Push-Benachrichtigungen werden nicht unterstützt');
            this.updatePushStatusUI({ supported: false, subscribed: false, permission: 'denied' });
            return false;
        }
        
        try {
            // Prüfe aktuelle Berechtigung
            let permission = await Notification.requestPermission();
            if (permission !== 'granted') {
                console.log('Push-Benachrichtigungen nicht erlaubt');
                this.updatePushStatusUI({ supported: true, subscribed: false, permission: permission });
                return false;
            }
            
            // Registriere Service Worker
            const registration = await navigator.serviceWorker.ready;
            
            // Hole VAPID Public Key vom Server
            const vapidResponse = await fetch('/api/push/vapid-key', {
                credentials: 'include'
            });
            
            if (!vapidResponse.ok) {
                throw new Error('VAPID Key konnte nicht geladen werden');
            }
            
            const vapidData = await vapidResponse.json();
            const applicationServerKey = this.urlBase64ToUint8Array(vapidData.public_key);
            
            // Subscribe zu Push Manager
            const subscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: applicationServerKey
            });
            
            // Sende Subscription an Server
            const response = await fetch('/api/push/subscribe', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'include',
                body: JSON.stringify({
                    ...subscription,
                    user_agent: navigator.userAgent
                })
            });
            
            if (response.ok) {
                console.log('Push-Benachrichtigungen erfolgreich registriert');
                this.updatePushStatusUI({ supported: true, subscribed: true, permission: permission });
                return true;
            } else {
                const errorData = await response.json();
                console.error('Fehler beim Registrieren der Push-Benachrichtigungen:', errorData);
                this.updatePushStatusUI({ supported: true, subscribed: false, permission: permission, error: errorData.message });
                return false;
            }
            
        } catch (error) {
            console.error('Fehler bei Push-Benachrichtigungen:', error);
            this.updatePushStatusUI({ supported: true, subscribed: false, permission: 'denied', error: error.message });
            return false;
        }
    }
    
    urlBase64ToUint8Array(base64String) {
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
    
    updatePushStatusUI(status) {
        // Update Status-Anzeige in den Einstellungen
        const statusElement = document.getElementById('push-status');
        if (statusElement) {
            if (!status.supported) {
                statusElement.innerHTML = '<span class="badge bg-warning">Nicht unterstützt</span>';
            } else if (status.permission === 'denied') {
                statusElement.innerHTML = '<span class="badge bg-danger">Verweigert</span>';
            } else if (status.subscribed) {
                statusElement.innerHTML = '<span class="badge bg-success">Aktiv</span>';
            } else {
                statusElement.innerHTML = '<span class="badge bg-secondary">Nicht registriert</span>';
            }
        }
        
        // Update Button-Status
        const subscribeBtn = document.getElementById('subscribe-push-btn');
        if (subscribeBtn) {
            if (!status.supported) {
                subscribeBtn.disabled = true;
                subscribeBtn.textContent = 'Nicht unterstützt';
            } else if (status.permission === 'denied') {
                subscribeBtn.disabled = true;
                subscribeBtn.textContent = 'Berechtigung verweigert';
            } else if (status.subscribed) {
                subscribeBtn.disabled = false;
                subscribeBtn.textContent = 'Registrierung erneuern';
            } else {
                subscribeBtn.disabled = false;
                subscribeBtn.textContent = 'Push-Benachrichtigungen aktivieren';
            }
        }
    }
    
    setupPushEventListeners() {
        // Event Listener für Push-Subscribe Button
        document.addEventListener('click', async (event) => {
            if (event.target.matches('#subscribe-push-btn') || 
                event.target.closest('#subscribe-push-btn')) {
                event.preventDefault();
                await this.registerPushNotifications();
            }
            
            // Test-Push Button
            if (event.target.matches('#test-push-btn') || 
                event.target.closest('#test-push-btn')) {
                event.preventDefault();
                await this.testPushNotification();
            }
        });
    }
    
    async testPushNotification() {
        try {
            const response = await fetch('/api/push/test', {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            
            if (response.ok) {
                alert('Test-Benachrichtigung gesendet!');
            } else {
                const error = await response.json();
                alert('Fehler beim Senden der Test-Benachrichtigung: ' + error.message);
            }
        } catch (error) {
            alert('Fehler beim Senden der Test-Benachrichtigung: ' + error.message);
        }
    }
}

// Initialisiere Server-Push-Manager
const serverPushManager = new ServerPushManager();

// Service Worker ist bereit für Server-Push-Benachrichtigungen
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.ready.then(function(registration) {
        console.log('Service Worker bereit für Server-Push-Benachrichtigungen');
    });
}

async function registerPushNotifications() {
    try {
        const registration = await navigator.serviceWorker.ready;
        
        // Prüfe ob bereits eine Subscription existiert
        pushSubscription = await registration.pushManager.getSubscription();
        
        if (!pushSubscription) {
            // Prüfe ob Benachrichtigungen erlaubt sind
            if (Notification.permission === 'default') {
                const permission = await Notification.requestPermission();
                if (permission !== 'granted') {
                    return;
                }
            } else if (Notification.permission !== 'granted') {
                return;
            }
            
            // Erstelle neue Subscription
            const applicationServerKey = urlBase64ToUint8Array('MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEG4ECv1S2TNUvpqoXcq4hbpVrFKruYoRRc1A8NMDhmU_a597YCT1e3_61_ujJLDDEwSnkauzSkjXh_QgeMb6Nsg');
            
            pushSubscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: applicationServerKey
            });
        }
        
        // Sende Subscription an Server
        await sendSubscriptionToServer(pushSubscription);
        
    } catch (error) {
        // Versuche es erneut nach 5 Sekunden
        setTimeout(() => {
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
        
        return response.ok;
    } catch (error) {
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
            // Verstecke Button
            const notificationBtn = document.getElementById('notification-btn');
            if (notificationBtn) {
                notificationBtn.style.display = 'none';
            }
            
            // Zeige Erfolgsmeldung
            showNotification('Benachrichtigungen aktiviert', 'Sie erhalten jetzt Push-Benachrichtigungen für neue Chat-Nachrichten.');
        } else {
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
    // Zeige Status-Info beim Laden der Seite
    showStatusInfo();
    
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



