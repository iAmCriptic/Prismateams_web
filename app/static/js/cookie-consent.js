(function () {
    'use strict';

    const STORAGE_KEY = 'prismateams_cookie_consent';
    const CONSENT_VERSION = 1;

    const banner = document.getElementById('cookieConsentBanner');
    const fab = document.getElementById('cookieConsentFab');
    if (!banner) return;

    const details = document.getElementById('cookieConsentDetails');
    const functionalToggle = document.getElementById('cookieConsentFunctional');
    const analyticsToggle = document.getElementById('cookieConsentAnalytics');

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
        window.dispatchEvent(new CustomEvent('cookieconsentchange', { detail: data }));
        return data;
    }

    function applyConsent(data) {
        window.PRISMATEAMS_COOKIE_CONSENT = data;
    }

    function showBanner() {
        banner.classList.remove('d-none');
        requestAnimationFrame(function () {
            banner.classList.add('is-visible');
        });
        if (fab) fab.classList.add('d-none');
    }

    function hideBanner() {
        banner.classList.remove('is-visible');
        setTimeout(function () {
            banner.classList.add('d-none');
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

    fab?.addEventListener('click', function () {
        const existing = readConsent();
        loadTogglesFromConsent(existing);
        toggleDetails(true);
        showBanner();
        hideFab();
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
