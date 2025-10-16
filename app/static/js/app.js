// Team Portal JavaScript

// PWA Service Worker Registration
if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        navigator.serviceWorker.register('/static/sw.js')
            .then(function(registration) {
                console.log('Service Worker registriert:', registration.scope);
                
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



