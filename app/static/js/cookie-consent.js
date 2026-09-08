(function () {
    'use strict';

    const STORAGE_KEY = 'prismateams_cookie_consent';
    const CONSENT_VERSION = 1;

    const banner = document.getElementById('cookieConsentBanner');
    const fab = document.getElementById('cookieConsentFab');
    if (!banner) return;

    const syncUrl = banner.getAttribute('data-consent-sync-url') || '';
    const details = document.getElementById('cookieConsentDetails');
    const functionalToggle = document.getElementById('cookieConsentFunctional');
    const analyticsToggle = document.getElementById('cookieConsentAnalytics');

    let hideTimer = null;

    function csrfHeaders() {
        const token = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
        const headers = { 'Content-Type': 'application/json', 'Accept': 'application/json' };
        if (token) headers['X-CSRFToken'] = token;
        return headers;
    }

    function syncConsentToServer(data) {
        if (!syncUrl || !data) return;
        try {
            fetch(syncUrl, {
                method: 'POST',
                credentials: 'same-origin',
                headers: csrfHeaders(),
                body: JSON.stringify({
                    version: data.version || CONSENT_VERSION,
                    functional: !!(data.categories && data.categories.functional),
                    analytics: !!(data.categories && data.categories.analytics)
                })
            }).catch(function () { /* Nachweis best-effort; localStorage bleibt Quelle für UI */ });
        } catch (e) { /* ignore */ }
    }

    function readConsent() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return null;
            const data = JSON.parse(raw);
            if (!data || data.version !== CONSENT_VERSION) return null;
            return data;
        } catch (e) {
            return null;
        }
    }

    function writeConsent(categories) {
        const data = {
            version: CONSENT_VERSION,
            timestamp: Date.now(),
            categories: {
                necessary: true,
                functional: !!categories.functional,
                analytics: !!categories.analytics
            }
        };
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
        applyConsent(data);
        hideBanner();
        showFab();
        syncConsentToServer(data);
        window.dispatchEvent(new CustomEvent('cookieconsentchange', { detail: data }));
        return data;
    }

    function applyConsent(data) {
        window.PRISMATEAMS_COOKIE_CONSENT = data;
        // Derzeit werden keine optionalen Drittanbieter-Skripte geladen.
        // hasCookieConsent('analytics'|'functional') ist für künftige Hooks vorgesehen.
    }

    function showBanner() {
        if (hideTimer) {
            clearTimeout(hideTimer);
            hideTimer = null;
        }
        banner.classList.remove('d-none');
        // Reflow, damit die CSS-Transition greift
        void banner.offsetWidth;
        requestAnimationFrame(function () {
            banner.classList.add('is-visible');
        });
        if (fab) fab.classList.add('d-none');
    }

    function hideBanner() {
        banner.classList.remove('is-visible');
        if (hideTimer) clearTimeout(hideTimer);
        hideTimer = setTimeout(function () {
            banner.classList.add('d-none');
            hideTimer = null;
        }, 350);
    }

    function showFab() {
        if (fab) fab.classList.remove('d-none');
    }

    function hideFab() {
        if (fab) fab.classList.add('d-none');
    }

    function toggleDetails(show) {
        if (!details) return;
        const settingsBtn = document.getElementById('cookieConsentSettingsToggle');
        if (show) {
            details.classList.remove('d-none');
            if (settingsBtn) settingsBtn.setAttribute('aria-expanded', 'true');
        } else {
            details.classList.add('d-none');
            if (settingsBtn) settingsBtn.setAttribute('aria-expanded', 'false');
        }
    }

    function loadTogglesFromConsent(consent) {
        if (functionalToggle) {
            functionalToggle.checked = consent ? consent.categories.functional : false;
        }
        if (analyticsToggle) {
            analyticsToggle.checked = consent ? consent.categories.analytics : false;
        }
    }

    document.getElementById('cookieConsentAcceptAll')?.addEventListener('click', function () {
        writeConsent({ functional: true, analytics: true });
    });

    document.getElementById('cookieConsentEssential')?.addEventListener('click', function () {
        writeConsent({ functional: false, analytics: false });
    });

    document.getElementById('cookieConsentSave')?.addEventListener('click', function () {
        writeConsent({
            functional: functionalToggle?.checked ?? false,
            analytics: analyticsToggle?.checked ?? false
        });
    });

    document.getElementById('cookieConsentSettingsToggle')?.addEventListener('click', function () {
        const isHidden = details?.classList.contains('d-none');
        toggleDetails(isHidden);
    });

    function openConsentSettings() {
        const existing = readConsent();
        loadTogglesFromConsent(existing);
        // Details nur nach Klick auf „Einstellungen“
        toggleDetails(false);
        showBanner();
        hideFab();
    }

    // Event-Delegation: funktioniert auch wenn Buttons später im DOM sind
    document.addEventListener('click', function (event) {
        const btn = event.target.closest('[data-cookie-consent-open]');
        if (!btn) return;

        event.preventDefault();
        event.stopPropagation();

        const offcanvasEl = btn.closest('.offcanvas');
        if (offcanvasEl && window.bootstrap?.Offcanvas) {
            const instance = window.bootstrap.Offcanvas.getOrCreateInstance(offcanvasEl);
            instance.hide();
        }
        openConsentSettings();
    });

    window.getCookieConsent = function () {
        return readConsent();
    };

    window.hasCookieConsent = function (category) {
        const consent = readConsent();
        if (!consent) return false;
        if (category === 'necessary') return true;
        return !!consent.categories[category];
    };

    const existing = readConsent();
    if (existing) {
        applyConsent(existing);
        showFab();
    } else {
        showBanner();
    }
})();
