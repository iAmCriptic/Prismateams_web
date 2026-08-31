// Team Portal JavaScript
const disablePublicPrompts = !!window.PRISMATEAMS_DISABLE_PUBLIC_PROMPTS;

/**
 * Apply user layout preference (auto | mobile | desktop) from <html data-preferred-layout>.
 * Must run early so chrome matches preference before first paint settles.
 */
function applyPreferredLayout() {
    const body = document.body;
    if (!body) return;
    const pref = (
        document.documentElement.getAttribute('data-preferred-layout') ||
        'auto'
    ).trim().toLowerCase();

    body.classList.remove('force-desktop-layout', 'force-mobile-layout');
    if (pref === 'desktop') {
        body.classList.add('force-desktop-layout');
    } else if (pref === 'mobile') {
        body.classList.add('force-mobile-layout');
    }
}

if (document.body) {
    applyPreferredLayout();
} else {
    document.addEventListener('DOMContentLoaded', applyPreferredLayout);
}
window.applyPreferredLayout = applyPreferredLayout;

function ptI18nCommon(key, fallback) {
    const common = (window.PRISMATEAMS_I18N && window.PRISMATEAMS_I18N.common) || {};
    return common[key] || fallback;
}

/**
 * App-styled confirm dialog (Promise). Prefer over window.confirm().
 * @param {string} message
 * @param {{ title?: string, confirmLabel?: string, cancelLabel?: string, danger?: boolean }} [options]
 * @returns {Promise<boolean>}
 */
window.ptConfirm = function ptConfirm(message, options) {
    const opts = options || {};
    const modalEl = document.getElementById('ptConfirmModal');
    if (!modalEl || typeof bootstrap === 'undefined' || !bootstrap.Modal) {
        return Promise.resolve(window.confirm(String(message || '')));
    }

    // Offene Dropdowns / Kontextmenüs schließen, sonst liegen sie über dem Modal
    try {
        if (window.PrismateamsContextMenu && typeof window.PrismateamsContextMenu.close === 'function') {
            window.PrismateamsContextMenu.close();
        }
        document.querySelectorAll('.dropdown-menu.show, .dropdown.show .dropdown-menu').forEach((menu) => {
            menu.classList.remove('show');
            menu.style.display = 'none';
        });
        document.querySelectorAll('.dropdown.show').forEach((dd) => dd.classList.remove('show'));
        document.querySelectorAll('.dropdown-menu').forEach((menu) => {
            if (menu.style && menu.style.display === 'block') {
                menu.style.display = 'none';
            }
        });
        if (bootstrap.Dropdown) {
            document.querySelectorAll('[data-bs-toggle="dropdown"]').forEach((toggle) => {
                const inst = bootstrap.Dropdown.getInstance(toggle);
                if (inst) inst.hide();
            });
        }
    } catch (_) {
        /* ignore */
    }

    const titleEl = document.getElementById('ptConfirmTitleText');
    const msgEl = document.getElementById('ptConfirmMessage');
    const okBtn = document.getElementById('ptConfirmOkBtn');
    const cancelBtn = document.getElementById('ptConfirmCancelBtn');
    const iconEl = document.getElementById('ptConfirmIcon');
    const i18nCommon = (window.PRISMATEAMS_I18N && window.PRISMATEAMS_I18N.common) || {};
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl, { backdrop: 'static', keyboard: true });
    const isDanger = opts.danger !== false;

    const applyCopy = () => {
        if (titleEl) {
            titleEl.textContent =
                opts.title ||
                (isDanger
                    ? (modalEl.getAttribute('data-i18n-title') || i18nCommon.confirm_delete_title || 'Löschen bestätigen')
                    : (i18nCommon.confirm || 'Bestätigen'));
        }
        if (msgEl) {
            msgEl.textContent = String(
                message ||
                modalEl.getAttribute('data-i18n-message') ||
                i18nCommon.confirm_delete_default ||
                'Möchten Sie dieses Element wirklich löschen?'
            );
        }
        if (iconEl) {
            iconEl.className = isDanger
                ? 'bi bi-exclamation-triangle-fill text-danger flex-shrink-0'
                : 'bi bi-question-circle-fill text-primary flex-shrink-0';
        }
        if (okBtn) {
            okBtn.textContent =
                opts.confirmLabel ||
                (isDanger
                    ? (modalEl.getAttribute('data-i18n-ok') || i18nCommon.delete || 'Löschen')
                    : (i18nCommon.confirm || 'Bestätigen'));
            okBtn.className = isDanger ? 'btn btn-danger' : 'btn btn-outline-primary';
        }
        if (cancelBtn) {
            cancelBtn.textContent =
                opts.cancelLabel ||
                modalEl.getAttribute('data-i18n-cancel') ||
                i18nCommon.cancel ||
                'Abbrechen';
        }
    };

    const openConfirm = () => {
        applyCopy();
        return new Promise((resolve) => {
            let settled = false;
            let accepted = false;
            const finish = (value) => {
                if (settled) return;
                settled = true;
                okBtn?.removeEventListener('click', onOk);
                modalEl.removeEventListener('hidden.bs.modal', onHidden);
                resolve(value);
            };
            // Resolve erst nach fully-hidden, sonst bricht ein zweites ptConfirm
            // (z.B. Doppel-Bestätigung) durch das hide-Event des ersten Modals ab.
            const onOk = () => {
                accepted = true;
                modal.hide();
            };
            const onHidden = () => finish(accepted);
            const onShown = () => {
                modalEl.style.zIndex = '20000';
                const backdrops = document.querySelectorAll('.modal-backdrop');
                const bd = backdrops[backdrops.length - 1];
                if (bd) {
                    bd.style.zIndex = '19990';
                    bd.classList.add('pt-confirm-backdrop');
                }
            };

            okBtn?.addEventListener('click', onOk);
            modalEl.addEventListener('hidden.bs.modal', onHidden, { once: true });
            modalEl.addEventListener('shown.bs.modal', onShown, { once: true });
            modal.show();
        });
    };

    // Warte, bis ein noch offenes/schließendes Modal fertig ist
    if (modalEl.classList.contains('show') || modalEl.classList.contains('showing')) {
        return new Promise((resolve) => {
            modalEl.addEventListener('hidden.bs.modal', () => {
                openConfirm().then(resolve);
            }, { once: true });
        });
    }

    return openConfirm();
};

/**
 * App-styled prompt dialog (Promise). Prefer over window.prompt().
 * @param {string} message
 * @param {{ title?: string, defaultValue?: string, confirmLabel?: string, cancelLabel?: string, placeholder?: string }} [options]
 * @returns {Promise<string|null>} entered value, or null if cancelled
 */
window.ptPrompt = function ptPrompt(message, options) {
    const opts = options || {};
    const modalEl = document.getElementById('ptPromptModal');
    if (!modalEl || typeof bootstrap === 'undefined' || !bootstrap.Modal) {
        const fallback = window.prompt(String(message || ''), opts.defaultValue != null ? String(opts.defaultValue) : '');
        return Promise.resolve(fallback);
    }

    try {
        if (window.PrismateamsContextMenu && typeof window.PrismateamsContextMenu.close === 'function') {
            window.PrismateamsContextMenu.close();
        }
    } catch (_) {
        /* ignore */
    }

    const titleEl = document.getElementById('ptPromptTitleText');
    const msgEl = document.getElementById('ptPromptMessage');
    const inputEl = document.getElementById('ptPromptInput');
    const okBtn = document.getElementById('ptPromptOkBtn');
    const cancelBtn = document.getElementById('ptPromptCancelBtn');
    const i18nCommon = (window.PRISMATEAMS_I18N && window.PRISMATEAMS_I18N.common) || {};
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl, { backdrop: 'static', keyboard: true });

    const applyCopy = () => {
        if (titleEl) {
            titleEl.textContent = opts.title || i18nCommon.confirm || 'Eingabe';
        }
        if (msgEl) {
            msgEl.textContent = String(message || '');
            msgEl.hidden = !message;
        }
        if (inputEl) {
            inputEl.value = opts.defaultValue != null ? String(opts.defaultValue) : '';
            inputEl.placeholder = opts.placeholder || '';
        }
        if (okBtn) {
            okBtn.textContent =
                opts.confirmLabel ||
                modalEl.getAttribute('data-i18n-ok') ||
                i18nCommon.confirm ||
                'OK';
        }
        if (cancelBtn) {
            cancelBtn.textContent =
                opts.cancelLabel ||
                modalEl.getAttribute('data-i18n-cancel') ||
                i18nCommon.cancel ||
                'Abbrechen';
        }
    };

    const openPrompt = () => {
        applyCopy();
        return new Promise((resolve) => {
            let settled = false;
            let accepted = false;
            const finish = (value) => {
                if (settled) return;
                settled = true;
                okBtn?.removeEventListener('click', onOk);
                inputEl?.removeEventListener('keydown', onKey);
                modalEl.removeEventListener('hidden.bs.modal', onHidden);
                resolve(value);
            };
            const onOk = () => {
                accepted = true;
                modal.hide();
            };
            const onKey = (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    onOk();
                }
            };
            const onHidden = () => finish(accepted ? (inputEl ? inputEl.value : '') : null);
            const onShown = () => {
                modalEl.style.zIndex = '20000';
                const backdrops = document.querySelectorAll('.modal-backdrop');
                const bd = backdrops[backdrops.length - 1];
                if (bd) {
                    bd.style.zIndex = '19990';
                    bd.classList.add('pt-confirm-backdrop');
                }
                if (inputEl) {
                    inputEl.focus();
                    inputEl.select();
                }
            };

            okBtn?.addEventListener('click', onOk);
            inputEl?.addEventListener('keydown', onKey);
            modalEl.addEventListener('hidden.bs.modal', onHidden, { once: true });
            modalEl.addEventListener('shown.bs.modal', onShown, { once: true });
            modal.show();
        });
    };

    if (modalEl.classList.contains('show') || modalEl.classList.contains('showing')) {
        return new Promise((resolve) => {
            modalEl.addEventListener('hidden.bs.modal', () => {
                openPrompt().then(resolve);
            }, { once: true });
        });
    }

    return openPrompt();
};

/**
 * In-page info/error banner (centered pill). Prefer this over window.alert().
 * @param {string} message
 * @param {string} [category='info'] - success|info|warning|danger|error
 * @param {{ timeout?: number|null, clear?: boolean, title?: string }} [options]
 */
window.showAppBanner = function showAppBanner(message, category, options) {
    const opts = options || {};
    const timeout = opts.timeout === undefined ? 6500 : opts.timeout;
    const clear = opts.clear !== false;
    let host = document.getElementById('appFlashBanner');
    if (!host) {
        const mainInner = document.querySelector('main .container-fluid, main .container, main');
        host = document.createElement('div');
        host.id = 'appFlashBanner';
        host.className = 'app-flash-banner';
        host.setAttribute('aria-live', 'polite');
        if (mainInner) {
            mainInner.insertBefore(host, mainInner.firstChild);
        } else {
            document.body.prepend(host);
        }
    }
    if (clear) {
        // Only remove previous JS banners; keep portal_alerts / server flashes
        host.querySelectorAll('[data-app-banner]').forEach((node) => node.remove());
    }

    const raw = String(category || 'info').toLowerCase();
    const cat = raw === 'error' ? 'danger' : (raw === 'message' ? 'info' : raw);
    const iconMap = {
        success: 'bi-check-circle-fill',
        info: 'bi-info-circle-fill',
        warning: 'bi-exclamation-triangle-fill',
        danger: 'bi-exclamation-circle-fill'
    };
    const iconClass = iconMap[cat] || iconMap.info;
    const closeLabel = (window.ptI18n && window.ptI18n.common && window.ptI18n.common.close) || 'Schließen';

    const el = document.createElement('div');
    el.className = `alert portal-msg portal-msg--${cat} fade show`;
    el.setAttribute('role', 'alert');
    el.setAttribute('data-app-banner', '1');

    const body = document.createElement('div');
    body.className = 'portal-msg__body';

    const icon = document.createElement('div');
    icon.className = 'portal-msg__icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.innerHTML = `<i class="bi ${iconClass}"></i>`;

    const content = document.createElement('div');
    content.className = 'portal-msg__content';
    if (opts.title) {
        const title = document.createElement('h6');
        title.className = 'portal-msg__title';
        title.textContent = String(opts.title);
        content.appendChild(title);
    }
    const text = document.createElement('p');
    text.className = 'portal-msg__text';
    text.textContent = String(message || '');
    content.appendChild(text);

    const actions = document.createElement('div');
    actions.className = 'portal-msg__actions';
    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'btn btn-sm portal-msg__btn portal-msg__close';
    closeBtn.textContent = closeLabel;
    closeBtn.addEventListener('click', function() {
        try {
            const inst = window.bootstrap && bootstrap.Alert.getOrCreateInstance(el);
            if (inst) inst.close();
            else el.remove();
        } catch (e) {
            el.remove();
        }
    });
    actions.appendChild(closeBtn);
    content.appendChild(actions);

    body.appendChild(icon);
    body.appendChild(content);
    el.appendChild(body);
    host.appendChild(el);

    if (timeout && timeout > 0) {
        setTimeout(() => {
            try {
                const inst = window.bootstrap && bootstrap.Alert.getOrCreateInstance(el);
                if (inst) inst.close();
                else el.remove();
            } catch (e) {
                el.remove();
            }
        }, timeout);
    }
    return el;
};

// Alias for older call sites
window.showPageBanner = window.showAppBanner;

/**
 * App-styled notice (banner). Prefer over window.alert().
 * @param {string} message
 * @param {string} [category='info'] - success|info|warning|danger|error
 * @param {{ timeout?: number|null, clear?: boolean, title?: string }} [options]
 */
window.ptAlert = function ptAlert(message, category, options) {
    if (typeof window.showAppBanner === 'function') {
        return window.showAppBanner(String(message || ''), category || 'info', options);
    }
    window.alert(String(message || ''));
};

// Status-Meldung beim Laden der Seite
function showStatusInfo() {
    // Status-Info wird still geprüft, keine Console-Ausgabe
}

// PWA Service Worker Registration + Update-Handling
// Update-Hinweis: In-App-Banner (wie Install/Push), kein window.confirm()
if ('serviceWorker' in navigator) {
    var _swRefreshing = false;
    var _swUpdateAccepted = false;
    var _swPromptedThisPage = false;
    var _swPendingWorker = null;
    var _swPendingRegistration = null;
    var SW_UPDATE_DISMISS_KEY = 'swUpdateDismissed';
    var SW_UPDATE_PENDING_KEY = 'swUpdatePending';
    var PWA_UPDATE_PROMPT_ID = 'pwa-update-prompt';

    function wasUpdateDismissed() {
        try {
            return sessionStorage.getItem(SW_UPDATE_DISMISS_KEY) === '1';
        } catch (e) {
            return false;
        }
    }

    function markUpdateDismissed() {
        try {
            sessionStorage.setItem(SW_UPDATE_DISMISS_KEY, '1');
        } catch (e) { /* ignore */ }
    }

    function clearUpdateDismissed() {
        try {
            sessionStorage.removeItem(SW_UPDATE_DISMISS_KEY);
        } catch (e) { /* ignore */ }
    }

    function markUpdatePending() {
        try {
            sessionStorage.setItem(SW_UPDATE_PENDING_KEY, '1');
        } catch (e) { /* ignore */ }
    }

    function clearUpdatePending() {
        try {
            sessionStorage.removeItem(SW_UPDATE_PENDING_KEY);
        } catch (e) { /* ignore */ }
    }

    function isUpdatePending() {
        try {
            return sessionStorage.getItem(SW_UPDATE_PENDING_KEY) === '1';
        } catch (e) {
            return false;
        }
    }

    function ptI18nPwaUpdate(key, fallback) {
        var pack = (window.PRISMATEAMS_I18N && window.PRISMATEAMS_I18N.pwa_update) || {};
        return pack[key] || fallback;
    }

    function hidePwaUpdatePrompt() {
        var prompt = document.getElementById(PWA_UPDATE_PROMPT_ID);
        if (prompt) {
            prompt.remove();
        }
        if (typeof layoutPortalPrompts === 'function') {
            layoutPortalPrompts();
        }
    }

    function activateWaitingWorker(worker, registration) {
        var target = (registration && registration.waiting) || worker || _swPendingWorker;
        var reg = registration || _swPendingRegistration;
        if (!target && reg && reg.waiting) {
            target = reg.waiting;
        }
        if (!target) {
            return;
        }
        _swUpdateAccepted = true;
        markUpdatePending();
        clearUpdateDismissed();
        target.postMessage({ type: 'SKIP_WAITING' });
    }

    function acceptPwaUpdate() {
        hidePwaUpdatePrompt();
        activateWaitingWorker(_swPendingWorker, _swPendingRegistration);
        setTimeout(function() {
            if (!_swRefreshing) {
                _swRefreshing = true;
                clearUpdatePending();
                window.location.reload();
            }
        }, 800);
    }

    function dismissPwaUpdate() {
        hidePwaUpdatePrompt();
        markUpdateDismissed();
        _swPendingWorker = null;
        _swPendingRegistration = null;
    }

    // Reload nur nach expliziter Update-Bestätigung
    navigator.serviceWorker.addEventListener('controllerchange', function() {
        if (!_swUpdateAccepted && !isUpdatePending()) {
            return;
        }
        if (_swRefreshing) {
            return;
        }
        _swRefreshing = true;
        clearUpdatePending();
        window.location.reload();
    });

    function showPwaUpdatePrompt(worker, registration) {
        if (document.getElementById(PWA_UPDATE_PROMPT_ID)) {
            _swPendingWorker = worker;
            _swPendingRegistration = registration;
            return;
        }

        _swPendingWorker = worker;
        _swPendingRegistration = registration;

        var prompt = document.createElement('div');
        prompt.id = PWA_UPDATE_PROMPT_ID;
        prompt.className = 'pwa-update-prompt';
        prompt.setAttribute('role', 'dialog');
        prompt.setAttribute('aria-modal', 'false');
        prompt.setAttribute('aria-labelledby', 'pwaUpdateTitle');
        prompt.setAttribute('aria-describedby', 'pwaUpdateDesc');
        prompt.innerHTML =
            '<div class="pwa-update-prompt__body">' +
                '<div class="pwa-update-prompt__icon" aria-hidden="true">' +
                    '<i class="bi bi-arrow-clockwise"></i>' +
                '</div>' +
                '<div class="pwa-update-prompt__content">' +
                    '<h6 class="pwa-update-prompt__title" id="pwaUpdateTitle">' +
                        ptI18nPwaUpdate('title', 'Neue Version verfügbar') +
                    '</h6>' +
                    '<p class="pwa-update-prompt__text" id="pwaUpdateDesc">' +
                        ptI18nPwaUpdate('description', 'Eine neue Version der App ist bereit. Bitte aktualisieren, um die neuesten Verbesserungen zu nutzen.') +
                    '</p>' +
                    '<div class="pwa-update-prompt__actions">' +
                        '<button type="button" class="btn btn-sm pwa-update-prompt__btn pwa-update-prompt__btn--reload" data-pwa-update="reload">' +
                            ptI18nPwaUpdate('reload', 'Aktualisieren') +
                        '</button>' +
                        '<button type="button" class="btn btn-sm pwa-update-prompt__btn pwa-update-prompt__btn--later" data-pwa-update="later">' +
                            ptI18nPwaUpdate('later', 'Später') +
                        '</button>' +
                    '</div>' +
                '</div>' +
            '</div>';

        document.body.appendChild(prompt);
        if (typeof layoutPortalPrompts === 'function') {
            layoutPortalPrompts();
        }

        prompt.addEventListener('click', function(e) {
            var btn = e.target.closest('[data-pwa-update]');
            if (!btn) {
                return;
            }
            var action = btn.getAttribute('data-pwa-update');
            if (action === 'reload') {
                acceptPwaUpdate();
            } else if (action === 'later') {
                dismissPwaUpdate();
            }
        });
    }

    function promptAndActivateWaitingWorker(worker, registration) {
        if (!worker || _swPromptedThisPage || _swUpdateAccepted || wasUpdateDismissed()) {
            return;
        }

        // Nach vorherigem OK: ohne erneuten Dialog aktivieren (Race-Fix)
        if (isUpdatePending()) {
            _swPromptedThisPage = true;
            activateWaitingWorker(worker, registration);
            setTimeout(function() {
                if (!_swRefreshing) {
                    _swRefreshing = true;
                    clearUpdatePending();
                    window.location.reload();
                }
            }, 500);
            return;
        }

        _swPromptedThisPage = true;
        showPwaUpdatePrompt(worker, registration);
    }

    function checkForWaitingWorker(registration) {
        if (registration.waiting && navigator.serviceWorker.controller) {
            promptAndActivateWaitingWorker(registration.waiting, registration);
        }
    }

    window.addEventListener('load', function() {
        navigator.serviceWorker.register('/sw.js')
            .then(function(registration) {
                checkForWaitingWorker(registration);

                registration.addEventListener('updatefound', function() {
                    const newWorker = registration.installing;
                    if (!newWorker) {
                        return;
                    }
                    newWorker.addEventListener('statechange', function() {
                        if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                            promptAndActivateWaitingWorker(newWorker, registration);
                        }
                    });
                });

                function requestSwUpdate() {
                    registration.update().catch(function() {});
                }
                document.addEventListener('visibilitychange', function() {
                    if (document.visibilityState === 'visible') {
                        requestSwUpdate();
                    }
                });
                window.addEventListener('focus', function() {
                    requestSwUpdate();
                });
            })
            .catch(function(error) {
                console.error('Service Worker Registrierung fehlgeschlagen:', error);
            });
    });
}

// PWA Install Prompt
// Verwende window.deferredPrompt für globale Verfügbarkeit (auch in settings/notifications.html)
window.deferredPrompt = null;
let promptShown = false;

const PWA_INSTALL_DISMISS_KEY = 'pwaInstallNeverShow';
const PWA_INSTALL_LATER_KEY = 'pwaInstallLater';
const PWA_INSTALL_PROMPT_ID = 'pwa-install-prompt';

function ptI18nPwa(key, fallback) {
    const pwa = (window.PRISMATEAMS_I18N && window.PRISMATEAMS_I18N.pwa_install) || {};
    return pwa[key] || fallback;
}

function isPwaInstallDismissed() {
    try {
        return localStorage.getItem(PWA_INSTALL_DISMISS_KEY) === '1';
    } catch (e) {
        return false;
    }
}

function isPwaInstallLaterThisSession() {
    try {
        return sessionStorage.getItem(PWA_INSTALL_LATER_KEY) === '1';
    } catch (e) {
        return false;
    }
}

function isRunningAsInstalledPwa() {
    return window.matchMedia('(display-mode: standalone)').matches
        || window.navigator.standalone === true;
}

function hidePwaInstallPrompt() {
    const prompt = document.getElementById(PWA_INSTALL_PROMPT_ID);
    if (prompt) {
        prompt.remove();
    }
    layoutPortalPrompts();
}

/** Stack Update + Push + PWA prompts top→bottom; after dismiss, remaining slides up. */
function layoutPortalPrompts() {
    const gap = 12;
    let nextTop = null;
    ['pwa-update-prompt', 'push-activation-prompt', PWA_INSTALL_PROMPT_ID].forEach(function (id) {
        const el = document.getElementById(id);
        if (!el) return;
        if (nextTop === null) {
            const fromTop = el.getBoundingClientRect().top;
            el.style.top = '';
            const toTop = el.getBoundingClientRect().top;
            if (Math.abs(fromTop - toTop) > 1) {
                el.style.top = fromTop + 'px';
                requestAnimationFrame(function () {
                    requestAnimationFrame(function () {
                        if (!document.getElementById(id)) return;
                        el.style.top = Math.round(toTop) + 'px';
                    });
                });
            }
            nextTop = toTop + el.offsetHeight + gap;
        } else {
            el.style.top = Math.round(nextTop) + 'px';
            nextTop = el.getBoundingClientRect().bottom + gap;
        }
    });
}

window.addEventListener('beforeinstallprompt', function(e) {
    if (disablePublicPrompts || isRunningAsInstalledPwa()) {
        e.preventDefault();
        return;
    }
    e.preventDefault();
    window.deferredPrompt = e;

    if (!isPwaInstallDismissed() && !isPwaInstallLaterThisSession()) {
        setTimeout(showInstallPrompt, 2800);
    }

    window.addEventListener('pagehide', function() {
        if (window.deferredPrompt && !promptShown) {
            window.deferredPrompt = null;
        }
    }, { once: true });
});

function showInstallPrompt() {
    if (disablePublicPrompts || isPwaInstallDismissed() || isPwaInstallLaterThisSession()) {
        return;
    }
    if (!window.deferredPrompt) {
        return;
    }
    if (document.getElementById(PWA_INSTALL_PROMPT_ID)) {
        return;
    }

    const prompt = document.createElement('div');
    prompt.id = PWA_INSTALL_PROMPT_ID;
    prompt.className = 'pwa-install-prompt';
    prompt.setAttribute('role', 'dialog');
    prompt.setAttribute('aria-modal', 'false');
    prompt.setAttribute('aria-labelledby', 'pwaInstallTitle');
    prompt.setAttribute('aria-describedby', 'pwaInstallDesc');
    prompt.innerHTML = `
        <div class="pwa-install-prompt__body">
            <div class="pwa-install-prompt__icon" aria-hidden="true">
                <i class="bi bi-download"></i>
            </div>
            <div class="pwa-install-prompt__content">
                <h6 class="pwa-install-prompt__title" id="pwaInstallTitle">${ptI18nPwa('title', 'App installieren')}</h6>
                <p class="pwa-install-prompt__text" id="pwaInstallDesc">${ptI18nPwa('description', 'Installiere das Portal als App für schnelleren Zugriff und Offline-Nutzung.')}</p>
                <div class="pwa-install-prompt__actions">
                    <button type="button" class="btn btn-sm pwa-install-prompt__btn pwa-install-prompt__btn--install" data-pwa-action="install">
                        ${ptI18nPwa('install', 'Installieren')}
                    </button>
                    <button type="button" class="btn btn-sm pwa-install-prompt__btn pwa-install-prompt__btn--later" data-pwa-action="later">
                        ${ptI18nPwa('later', 'Später')}
                    </button>
                    <button type="button" class="btn btn-sm pwa-install-prompt__btn pwa-install-prompt__btn--never" data-pwa-action="never">
                        ${ptI18nPwa('never', 'Nicht mehr anzeigen')}
                    </button>
                </div>
            </div>
        </div>
    `;

    document.body.appendChild(prompt);
    layoutPortalPrompts();

    prompt.querySelector('[data-pwa-action="install"]')?.addEventListener('click', function() {
        installPWA();
    });
    prompt.querySelector('[data-pwa-action="later"]')?.addEventListener('click', function() {
        try {
            sessionStorage.setItem(PWA_INSTALL_LATER_KEY, '1');
        } catch (e) { /* ignore */ }
        hidePwaInstallPrompt();
    });
    prompt.querySelector('[data-pwa-action="never"]')?.addEventListener('click', function() {
        try {
            localStorage.setItem(PWA_INSTALL_DISMISS_KEY, '1');
            localStorage.removeItem('pwaInstallLaterUntil');
        } catch (e) { /* ignore */ }
        hidePwaInstallPrompt();
    });
}

/** @deprecated Alias für ältere Aufrufe / Settings-Seite */
function showInstallButton() {
    showInstallPrompt();
}

function installPWA() {
    if (window.deferredPrompt && !promptShown) {
        promptShown = true;

        try {
            window.deferredPrompt.prompt().then(function() {
                return window.deferredPrompt.userChoice;
            }).then(function(choiceResult) {
                if (choiceResult.outcome === 'accepted') {
                    console.debug('Benutzer hat PWA-Installation akzeptiert');
                } else {
                    console.debug('Benutzer hat PWA-Installation abgelehnt');
                }

                window.deferredPrompt = null;
                promptShown = false;
                hidePwaInstallPrompt();
            }).catch(function(error) {
                console.debug('Fehler beim Anzeigen des PWA-Install-Prompts:', error);
                window.deferredPrompt = null;
                promptShown = false;
            });
        } catch (error) {
            console.debug('prompt() konnte nicht aufgerufen werden:', error);
            window.deferredPrompt = null;
            promptShown = false;
        }
    }
}

window.addEventListener('appinstalled', function() {
    hidePwaInstallPrompt();
    window.deferredPrompt = null;
});

// Push Notifications
let pushSubscription = null;

// Prüfe ob Push-Benachrichtigungen unterstützt werden
// Sicheren Kontext zuverlässig über window.isSecureContext prüfen
const isPushEnvironmentReady = () => (
    window.isSecureContext && 'serviceWorker' in navigator && 'PushManager' in window
);

if (isPushEnvironmentReady()) {
    // Kein unmittelbarer Doppelaufruf – die eigentliche Auto-Registrierung
    // erfolgt in ServerPushManager.init(), sobald Berechtigungen erteilt sind
    navigator.serviceWorker.ready.catch(function(error) {
        console.error('Fehler beim Warten auf Service Worker:', error);
    });
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

        // Mikrofon-Berechtigung wird nur bei expliziter Benutzeraktion angefragt
        this.setupMicrophonePermissionRequest();
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
                // Mikrofon-Berechtigung kann nicht geprüft werden - stillschweigend ignorieren
            }
        }
        
        // Berechtigungen werden still geprüft
    }
    
    async requestPermissions() {
        // Berechtigungen nur bei Bedarf anfragen (manuell ausgelöst)
        if (this.permissions.notifications === 'default') {
            await this.requestNotificationPermission();
        }
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
                        await serverPushManager.registerPushNotifications();
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
        this.isRegistering = false;
        this.registerDebounceTimer = null;
        this.pushActivationPromptId = 'push-activation-prompt';
        this.pushActivationPromptSessionKey = 'pushActivationPromptHandled';
        this.pushActivationPromptDismissKey = 'pushActivationPromptDismissed';
        this.pushPromptAllowedPrefixes = ['/chat', '/files', '/calendar', '/email'];
        this.init();
    }
    
    init() {
        if (disablePublicPrompts) {
            this.hidePushActivationPrompt();
            return;
        }
        // Prüfe Push-Status beim Laden
        this.checkPushStatus().then((status) => {
            if (!status) {
                return;
            }

            // Berechtigung bereits erteilt -> registrieren (nur wenn technisch möglich)
            if (!status.subscribed && status.permission === 'granted' && isPushEnvironmentReady()) {
                this.debouncedRegister();
            }

            // Berechtigung noch offen -> Prompt nur auf Push-relevanten Modulen
            if (status.permission === 'default') {
                this.schedulePushActivationPrompt();
            }
        });
        
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

    isPortalLayoutVisible() {
        return !!(document.getElementById('desktopTopNav') || document.getElementById('desktopSidebar') || document.getElementById('mobileNav'));
    }

    isPushPromptContextPage() {
        const path = window.location.pathname || '';
        return this.pushPromptAllowedPrefixes.some((prefix) => (
            path === prefix || path.startsWith(`${prefix}/`)
        ));
    }

    isPushPromptDismissedForever() {
        try {
            return localStorage.getItem(this.pushActivationPromptDismissKey) === '1';
        } catch (error) {
            return false;
        }
    }

    dismissPushPromptForever() {
        try {
            localStorage.setItem(this.pushActivationPromptDismissKey, '1');
        } catch (error) {
            // localStorage kann blockiert sein – Session reicht als Fallback
        }
        sessionStorage.setItem(this.pushActivationPromptSessionKey, '1');
        this.hidePushActivationPrompt();
    }

    showPushActivationPrompt() {
        if (!document.body) {
            return;
        }
        if (!this.isPushPromptContextPage()) {
            return;
        }
        if (!('Notification' in window) || Notification.permission !== 'default') {
            return;
        }
        if (this.isPushPromptDismissedForever()) {
            return;
        }
        if (sessionStorage.getItem(this.pushActivationPromptSessionKey) === '1') {
            return;
        }
        if (document.getElementById(this.pushActivationPromptId)) {
            return;
        }

        const prompt = document.createElement('div');
        prompt.id = this.pushActivationPromptId;
        prompt.className = 'push-activation-prompt';
        prompt.setAttribute('role', 'dialog');
        prompt.setAttribute('aria-labelledby', 'push-activation-prompt-title');
        prompt.innerHTML = `
            <div class="push-activation-prompt__body">
                <div class="push-activation-prompt__icon" aria-hidden="true">
                    <i class="bi bi-bell"></i>
                </div>
                <div class="push-activation-prompt__content">
                    <h6 id="push-activation-prompt-title" class="push-activation-prompt__title">Push-Benachrichtigungen auf dem Gerät aktivieren?</h6>
                    <p class="push-activation-prompt__text">Sie erhalten dann neue Nachrichten direkt als Benachrichtigung.</p>
                    <div class="push-activation-prompt__actions">
                        <button type="button" class="btn btn-sm push-activation-prompt__btn push-activation-prompt__btn--yes" data-push-activate="yes">Ja</button>
                        <button type="button" class="btn btn-sm push-activation-prompt__btn push-activation-prompt__btn--later" data-push-activate="later">Später</button>
                        <button type="button" class="btn btn-sm push-activation-prompt__btn push-activation-prompt__btn--never" data-push-activate="never">Nicht mehr anzeigen</button>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(prompt);
        layoutPortalPrompts();

        const yesButton = prompt.querySelector('[data-push-activate="yes"]');
        const laterButton = prompt.querySelector('[data-push-activate="later"]');
        const neverButton = prompt.querySelector('[data-push-activate="never"]');

        yesButton?.addEventListener('click', async () => {
            sessionStorage.setItem(this.pushActivationPromptSessionKey, '1');
            this.hidePushActivationPrompt();
            await this.registerPushNotifications();
        });

        laterButton?.addEventListener('click', () => {
            sessionStorage.setItem(this.pushActivationPromptSessionKey, '1');
            this.hidePushActivationPrompt();
        });

        neverButton?.addEventListener('click', () => {
            this.dismissPushPromptForever();
        });
    }

    schedulePushActivationPrompt() {
        if (!this.isPushPromptContextPage() || this.isPushPromptDismissedForever()) {
            return;
        }

        // Kurz verzögert anzeigen, damit Layout/DOM sicher da sind
        setTimeout(() => {
            this.showPushActivationPrompt();
        }, 600);

        // Fallback: falls direkt nach Login noch etwas nachlädt
        setTimeout(() => {
            this.showPushActivationPrompt();
        }, 1800);
    }

    hidePushActivationPrompt() {
        const prompt = document.getElementById(this.pushActivationPromptId);
        if (prompt) {
            prompt.remove();
        }
        layoutPortalPrompts();
    }
    
    debouncedRegister() {
        if (this.registerDebounceTimer) {
            clearTimeout(this.registerDebounceTimer);
        }
        this.registerDebounceTimer = setTimeout(() => {
            this.registerPushNotifications();
        }, 300);
    }

    async registerPushNotifications() {
        if (!this.isPushSupported()) {
            this.updatePushStatusUI({ supported: false, subscribed: false, permission: 'denied' });
            return false;
        }
        
        try {
            if (this.isRegistering) {
                return false;
            }
            this.isRegistering = true;
            
            // Prüfe aktuelle Berechtigung und frage bei Bedarf an
            let permission = Notification.permission;
            if (permission === 'default') {
                permission = await Notification.requestPermission();
            }
            
            if (permission !== 'granted') {
                this.hidePushActivationPrompt();
                this.updatePushStatusUI({ supported: true, subscribed: false, permission: permission });
                this.showTestResult('warning', 'Push-Benachrichtigungen wurden verweigert. Bitte erlauben Sie Benachrichtigungen in den Browser-Einstellungen.');
                return false;
            }

            this.hidePushActivationPrompt();
            
            // Registriere Service Worker
            const registration = await navigator.serviceWorker.ready;
            
            // Prüfe, ob bereits eine Subscription existiert
            let subscription = await registration.pushManager.getSubscription();
            if (subscription) {
                // Sende bestehende Subscription an den Server
                const sendOk = await this.sendSubscriptionToServer(subscription, permission);
                if (sendOk) {
                    this.updatePushStatusUI({ supported: true, subscribed: true, permission: permission });
                    this.showTestResult('success', 'Push-Benachrichtigungen erfolgreich aktiviert!');
                    return true;
                }
                // Falls das Senden fehlschlug, versuche Neu-Subscribe
            }
            
            // Hole VAPID Public Key vom Server
            const vapidResponse = await fetch('/api/push/vapid-key', {
                credentials: 'include'
            });
            
            if (!vapidResponse.ok) {
                const errorData = await vapidResponse.json();
                console.error('VAPID Key Fehler:', errorData);
                throw new Error(errorData.message || 'VAPID Key konnte nicht geladen werden');
            }
            
            const vapidData = await vapidResponse.json();
            const applicationServerKey = this.urlBase64ToUint8Array(vapidData.public_key);
            
            // Subscribe zu Push Manager
            subscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: applicationServerKey
            });
            
            // Sende Subscription an Server
            const response = await this.postSubscription(subscription);
            
            if (response.ok) {
                const result = await response.json();
                this.updatePushStatusUI({ supported: true, subscribed: true, permission: permission });
                this.showTestResult('success', 'Push-Benachrichtigungen erfolgreich aktiviert!');
                return true;
            } else {
                const errorData = await response.json();
                console.error('Server-Fehler beim Registrieren:', response.status, errorData);
                this.updatePushStatusUI({ supported: true, subscribed: false, permission: permission, error: errorData.message });
                this.showTestResult('error', 'Server-Fehler: ' + (errorData.message || 'Unbekannter Fehler'));
                return false;
            }
            
        } catch (error) {
            console.error('Fehler bei Push-Benachrichtigungen:', error);
            this.updatePushStatusUI({ supported: true, subscribed: false, permission: 'denied', error: error.message });
            return false;
        } finally {
            this.isRegistering = false;
        }
    }

    subscriptionToPayload(subscription) {
        const keyToBase64 = (key) => {
            if (!key) return null;
            const buffer = new Uint8Array(key);
            let binary = '';
            for (let i = 0; i < buffer.byteLength; i++) {
                binary += String.fromCharCode(buffer[i]);
            }
            return btoa(binary);
        };
        return {
            endpoint: subscription.endpoint,
            keys: subscription.getKey ? {
                p256dh: keyToBase64(subscription.getKey('p256dh')),
                auth: keyToBase64(subscription.getKey('auth'))
            } : subscription.keys,
            user_agent: navigator.userAgent
        };
    }

    async postSubscription(subscription) {
        const payload = this.subscriptionToPayload(subscription);
        
        return fetch('/api/push/subscribe', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'include',
            body: JSON.stringify(payload)
        });
    }

    async sendSubscriptionToServer(subscription, permission) {
        try {
            const response = await this.postSubscription(subscription);
            if (response.ok) {
                return true;
            }
            return false;
        } catch (e) {
            console.error('Senden bestehender Subscription fehlgeschlagen:', e);
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

        const supportStatus = document.getElementById('push-support-status');
        if (supportStatus) {
            const okText = supportStatus.dataset.ok || 'Dieser Browser unterstützt Push-Benachrichtigungen mit dieser Seite';
            const noText = supportStatus.dataset.no || 'Dieser Browser unterstützt Push-Benachrichtigungen nicht';
            if (status.supported) {
                supportStatus.textContent = okText;
                supportStatus.classList.add('is-ok');
                supportStatus.classList.remove('is-no');
            } else {
                supportStatus.textContent = noText;
                supportStatus.classList.add('is-no');
                supportStatus.classList.remove('is-ok');
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
        
        // Zeige/Verstecke Setup-Warnung
        const setupAlert = document.getElementById('push-setup-alert');
        if (setupAlert) {
            if (status.supported && !status.subscribed && status.permission !== 'denied') {
                setupAlert.style.display = 'block';
            } else {
                setupAlert.style.display = 'none';
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

            if (event.target.matches('#reset-push-btn') ||
                event.target.closest('#reset-push-btn')) {
                event.preventDefault();
                await this.resetPushRegistration();
            }
        });
    }

    async resetPushRegistration() {
        const resetMsg = 'Push-Benachrichtigungen wirklich zurücksetzen? Sie müssen sich danach erneut registrieren.';
        const ok = typeof window.ptConfirm === 'function'
            ? await window.ptConfirm(resetMsg, {
                title: 'Push zurücksetzen',
                confirmLabel: 'Zurücksetzen',
                danger: true,
            })
            : window.confirm(resetMsg);
        if (!ok) {
            return false;
        }
        try {
            const resetResponse = await fetch('/api/notifications/reset-push', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                credentials: 'include',
            });
            if (!resetResponse.ok) {
                throw new Error('Server-Reset fehlgeschlagen');
            }

            if (this.isPushSupported()) {
                try {
                    const registration = await navigator.serviceWorker.ready;
                    const subscription = await registration.pushManager.getSubscription();
                    if (subscription) {
                        await subscription.unsubscribe();
                    }
                } catch (e) {
                    console.warn('Browser-Unsubscribe fehlgeschlagen:', e);
                }
            }

            await this.checkPushStatus();
            this.showTestResult('success', 'Push-Benachrichtigungen wurden zurückgesetzt. Bitte aktivieren Sie Push erneut.');
            return true;
        } catch (error) {
            console.error('Reset fehlgeschlagen:', error);
            this.showTestResult('error', 'Zurücksetzen fehlgeschlagen: ' + error.message);
            return false;
        }
    }
    
    async testPushNotification() {
        const testBtn = document.getElementById('test-push-btn');
        const originalText = testBtn.innerHTML;
        
        // Button deaktivieren und Loading-State anzeigen
        testBtn.disabled = true;
        testBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Teste...';
        
        try {
            const response = await fetch('/api/push/test', {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                // Erfolgreich gesendet - starte 2-Minuten-Cooldown
                this.showTestResult('success', data.message);
                this.startCooldownTimer(testBtn, originalText, 120); // 2 Minuten
            } else {
                // Fehler beim Senden
                if (data && data.cooldown) {
                    // Cooldown-Fehler: Button für verbleibende Zeit deaktivieren
                    this.showTestResult('warning', data.message);
                    this.startCooldownTimer(testBtn, originalText, data.remaining_seconds);
                } else if (data && data.action_required === 'subscribe') {
                    this.showTestResult('warning', data.message || 'Keine aktive Subscription. Registrierung wird gestartet...');
                    const registered = await this.registerPushNotifications();
                    if (registered) {
                        // kurzer Retry nach Erfolg
                        setTimeout(() => {
                            this.testPushNotification();
                        }, 500);
                        return; // Verhindere Button-Reset
                    }
                } else {
                    this.showTestResult('error', (data && data.message) || 'Unbekannter Fehler beim Senden der Test-Benachrichtigung');
                }
                // Button nach Fehler sofort wieder aktivieren (außer bei Cooldown)
                if (!data || !data.cooldown) {
                    this.resetTestButton(testBtn, originalText);
                }
            }
        } catch (error) {
            this.showTestResult('error', 'Netzwerk-Fehler: ' + error.message);
            // Button nach Fehler sofort wieder aktivieren
            this.resetTestButton(testBtn, originalText);
        }
    }
    
    resetTestButton(button, originalText) {
        button.disabled = false;
        button.classList.remove('disabled');
        button.innerHTML = originalText;
    }
    
    // Cooldown-Management mit LocalStorage
    isCooldownActive() {
        const cooldownEnd = localStorage.getItem('pushTestCooldownEnd');
        if (!cooldownEnd) return false;
        
        const now = Date.now();
        const endTime = parseInt(cooldownEnd);
        return now < endTime;
    }
    
    getCooldownRemaining() {
        const cooldownEnd = localStorage.getItem('pushTestCooldownEnd');
        if (!cooldownEnd) return 0;
        
        const now = Date.now();
        const endTime = parseInt(cooldownEnd);
        const remaining = Math.max(0, Math.ceil((endTime - now) / 1000));
        return remaining;
    }
    
    setCooldown(durationSeconds) {
        const endTime = Date.now() + (durationSeconds * 1000);
        localStorage.setItem('pushTestCooldownEnd', endTime.toString());
    }
    
    clearCooldown() {
        localStorage.removeItem('pushTestCooldownEnd');
    }
    
    startCooldownTimer(button, originalText, remainingSeconds) {
        // Setze Cooldown in LocalStorage
        this.setCooldown(remainingSeconds);
        
        // Zeige Cooldown-Container
        const cooldownContainer = document.getElementById('cooldown-container');
        const cooldownProgress = document.getElementById('cooldown-progress');
        const cooldownTimer = document.getElementById('cooldown-timer');
        
        if (cooldownContainer) {
            cooldownContainer.style.display = 'block';
        }
        
        // Button definitiv deaktivieren
        button.disabled = true;
        button.classList.add('disabled');
        
        const updateTimer = () => {
            const remaining = this.getCooldownRemaining();
            
            if (remaining > 0) {
                // Update Timer Display
                const minutes = Math.floor(remaining / 60);
                const seconds = remaining % 60;
                const timeString = `${minutes}:${seconds.toString().padStart(2, '0')}`;
                
                if (cooldownTimer) {
                    cooldownTimer.textContent = timeString;
                }
                
                // Update Progress Bar
                const totalCooldown = 120; // 2 Minuten
                const progress = ((totalCooldown - remaining) / totalCooldown) * 100;
                
                if (cooldownProgress) {
                    cooldownProgress.style.width = `${progress}%`;
                }
                
                // Update Button - Button bleibt deaktiviert
                button.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Warten... (${timeString})`;
                button.disabled = true;
                
                setTimeout(updateTimer, 1000);
            } else {
                // Cooldown beendet
                this.clearCooldown();
                this.resetTestButton(button, originalText);
                
                if (cooldownContainer) {
                    cooldownContainer.style.display = 'none';
                }
            }
        };
        
        updateTimer();
    }
    
    showTestResult(type, message) {
        if (typeof window.ptAlert === 'function') {
            window.ptAlert(message, type, { title: 'Test-Push' });
            return;
        }
        if (typeof window.showAppBanner === 'function') {
            window.showAppBanner(message, type, { title: 'Test-Push' });
            return;
        }
        window.alert('Test-Push: ' + message);
    }
}

// Initialisiere Server-Push-Manager
const serverPushManager = new ServerPushManager();

// Service Worker ist bereit für Server-Push-Benachrichtigungen
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.ready.then(function(registration) {
        // Service Worker bereit - keine Console-Ausgabe
    });
}

// Initialisiere Cooldown-Status beim Laden der Seite
document.addEventListener('DOMContentLoaded', function() {
    const testBtn = document.getElementById('test-push-btn');
    if (testBtn && serverPushManager.isCooldownActive()) {
        const remaining = serverPushManager.getCooldownRemaining();
        if (remaining > 0) {
            serverPushManager.startCooldownTimer(testBtn, 'Test senden', remaining);
        }
    }
});

// Legacy-Funktionen entfernt - verwende ServerPushManager

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

    // Confirmation dialogs for delete actions (custom modal, not native confirm)
    document.addEventListener('click', function (e) {
        const button = e.target.closest('[data-confirm-delete], [data-pt-confirm]');
        if (!button || button.disabled) return;
        if (button.dataset.ptConfirmOk === '1') {
            button.dataset.ptConfirmOk = '';
            return;
        }
        const form = button.form || button.closest('form');
        if (form && typeof form.checkValidity === 'function' && !form.checkValidity()) {
            return;
        }
        e.preventDefault();
        e.stopPropagation();
        const isDelete = button.hasAttribute('data-confirm-delete');
        const message =
            button.getAttribute('data-confirm-delete') ||
            button.getAttribute('data-pt-confirm') ||
            ptI18nCommon('confirm_delete_default', 'Möchten Sie dieses Element wirklich löschen?');
        const opts = {
            title: button.getAttribute('data-pt-confirm-title') || undefined,
            confirmLabel: button.getAttribute('data-pt-confirm-ok') || undefined,
            cancelLabel: button.getAttribute('data-pt-confirm-cancel') || undefined,
            danger: button.getAttribute('data-pt-confirm-danger') === 'false' ? false : (isDelete || button.getAttribute('data-pt-confirm-danger') !== '0'),
        };
        window.ptConfirm(message, opts).then((ok) => {
            if (!ok) return;
            button.dataset.ptConfirmOk = '1';
            button.click();
        });
    }, true);
    // Password visibility toggle
    const passwordToggles = document.querySelectorAll('.password-toggle');
    passwordToggles.forEach(toggle => {
        toggle.addEventListener('click', function () {
            const group = this.closest('.input-group');
            const input = (group && group.querySelector('input')) || this.previousElementSibling;
            const icon = this.querySelector('i');
            if (!input || !icon) return;

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

// Sidebar Navigation Management für Tablets/kleine PCs
// Verwaltet die Sidebar-Navigation mit Prioritäten und Scroll-Funktionalität
function manageSidebarNavigation() {
    const sidebarNav = document.getElementById('sidebarNavList');
    const sidebarNavItems = document.getElementById('sidebarNavItems');
    const sidebarMoreButton = document.getElementById('sidebarMoreButton');
    const desktopMoreMenuItems = document.getElementById('desktopMoreMenuItems');
    
    if (!sidebarNav || !sidebarNavItems) {
        return; // Sidebar nicht vorhanden (z.B. auf Mobile)
    }
    
    // Prüfe, ob wir auf einem Tablet/kleinen PC sind (768px - 991px)
    const isTablet = window.innerWidth >= 768 && window.innerWidth < 992;
    
    // Alle Navigation-Elemente sammeln
    const allNavItems = Array.from(sidebarNavItems.querySelectorAll('.sidebar-nav-item'));
    
    // Sortiere nach Priorität
    const sortedItems = allNavItems.sort((a, b) => {
        const priorityA = a.getAttribute('data-nav-priority');
        const priorityB = b.getAttribute('data-nav-priority');
        
        // "always-visible" hat höchste Priorität
        if (priorityA === 'always-visible') return -1;
        if (priorityB === 'always-visible') return 1;
        
        // Konvertiere zu Zahlen für Vergleich
        const numA = parseFloat(priorityA) || 999;
        const numB = parseFloat(priorityB) || 999;
        
        return numA - numB;
    });
    
    // Berechne verfügbaren Platz in der Sidebar
    const calculateAvailableSpace = () => {
        const sidebar = document.getElementById('desktopSidebar');
        if (!sidebar) return 0;
        
        const header = sidebar.querySelector('.sidebar-header');
        const footer = sidebar.querySelector('.sidebar-footer');
        
        const headerHeight = header ? header.offsetHeight : 0;
        const footerHeight = footer ? footer.offsetHeight : 0;
        const availableHeight = window.innerHeight - headerHeight - footerHeight;
        
        return availableHeight;
    };
    
    // Prüfe, ob alle Elemente in die Sidebar passen
    const checkIfAllItemsFit = () => {
        const availableHeight = calculateAvailableSpace();
        let totalHeight = 0;
        
        sortedItems.forEach(item => {
            totalHeight += item.offsetHeight;
        });
        
        return totalHeight <= availableHeight;
    };
    
    // Zeige/Verstecke "Mehr"-Button und verschiebe Elemente ins More-Menu
    const updateNavigation = () => {
        const allItemsFit = checkIfAllItemsFit();
        
        if (allItemsFit) {
            // Alle Elemente passen - verstecke "Mehr"-Button
            if (sidebarMoreButton) {
                sidebarMoreButton.classList.add('d-none');
            }
            
            // Alle Elemente in der Sidebar anzeigen
            sortedItems.forEach(item => {
                if (item.id !== 'sidebarMoreButton') {
                    item.style.display = '';
                }
            });
            
            // More-Menu leeren
            if (desktopMoreMenuItems) {
                desktopMoreMenuItems.innerHTML = '';
            }
        } else {
            // Nicht alle Elemente passen - zeige "Mehr"-Button
            if (sidebarMoreButton) {
                sidebarMoreButton.classList.remove('d-none');
            }
            
            // Berechne, welche Elemente in die Sidebar passen
            const availableHeight = calculateAvailableSpace();
            let currentHeight = 0;
            const visibleItems = [];
            const hiddenItems = [];
            
            // Füge "Mehr"-Button zur Höhe hinzu
            const moreButtonHeight = sidebarMoreButton ? sidebarMoreButton.offsetHeight : 0;
            
            sortedItems.forEach(item => {
                if (item.id === 'sidebarMoreButton') {
                    return; // Überspringe "Mehr"-Button selbst
                }
                
                const itemHeight = item.offsetHeight;
                
                if (currentHeight + itemHeight + moreButtonHeight <= availableHeight) {
                    visibleItems.push(item);
                    currentHeight += itemHeight;
                } else {
                    hiddenItems.push(item);
                }
            });
            
            // Zeige sichtbare Elemente
            visibleItems.forEach(item => {
                item.style.display = '';
            });
            
            // Verstecke versteckte Elemente
            hiddenItems.forEach(item => {
                item.style.display = 'none';
            });
            
            // Füge versteckte Elemente zum More-Menu hinzu
            if (desktopMoreMenuItems && hiddenItems.length > 0) {
                desktopMoreMenuItems.innerHTML = '';
                hiddenItems.forEach(item => {
                    const link = item.querySelector('a');
                    if (!link) return;

                    const menuItem = document.createElement('li');
                    menuItem.className = 'nav-item';

                    const cloned = link.cloneNode(true);
                    cloned.classList.add('more-menu-link');

                    const icon = cloned.querySelector(':scope > i.bi');
                    if (icon) {
                        icon.classList.remove('me-2');
                        const iconWrap = document.createElement('span');
                        iconWrap.className = 'more-menu-icon';
                        iconWrap.appendChild(icon);
                        cloned.insertBefore(iconWrap, cloned.firstChild);
                    }

                    const textParts = [];
                    [...cloned.childNodes].forEach(node => {
                        if (node.nodeType === Node.TEXT_NODE) {
                            const t = node.textContent.trim();
                            if (t) textParts.push(t);
                            node.remove();
                        }
                    });
                    if (textParts.length && !cloned.querySelector('.more-menu-label')) {
                        const label = document.createElement('span');
                        label.className = 'more-menu-label';
                        label.textContent = textParts.join(' ');
                        cloned.appendChild(label);
                    }

                    menuItem.appendChild(cloned);
                    desktopMoreMenuItems.appendChild(menuItem);
                });
            }
        }
    };
    
    // Initialisiere Navigation
    updateNavigation();
    
    // Aktualisiere bei Fenstergrößenänderung
    let resizeTimeout;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
            updateNavigation();
        }, 250);
    });
}

function initSidebarAndEmailBadge() {
    manageSidebarNavigation();
}

// Initialisiere Sidebar-Navigation beim Laden der Seite
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSidebarAndEmailBadge);
} else {
    initSidebarAndEmailBadge();
}

/**
 * Dashboard-Zahlenindikator für ungelesene E-Mails.
 */
window.updateEmailNavBadge = function updateEmailNavBadge(count) {
    const n = Math.max(0, parseInt(count, 10) || 0);
    const label = n > 99 ? '99+' : String(n);
    document.querySelectorAll('.email-badge').forEach((badge) => {
        badge.textContent = n > 0 ? label : '0';
        if (badge.style) {
            badge.style.display = n > 0 ? '' : 'none';
        }
    });
};




