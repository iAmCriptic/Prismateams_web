/**
 * Portal onboarding: 3-step spotlight tour on the dashboard.
 */
(function () {
    'use strict';

    const boot = window.PORTAL_ONBOARDING_BOOT || {};
    const root = document.getElementById('portalOnboarding');
    if (!root) return;

    const steps = Array.isArray(boot.steps) ? boot.steps : [];
    if (!steps.length) return;

    const spotlight = root.querySelector('.portal-onboarding-spotlight');
    const completeUrl = root.dataset.portalOnboardingCompleteUrl || boot.completeUrl || '';
    const shouldPersistCompletion = boot.alreadyCompleted !== true;

    let currentStep = 0;
    let completionSent = false;
    let activeTarget = null;

    function isMobile() {
        return window.matchMedia('(max-width: 991.98px)').matches;
    }

    function resolveTarget(step) {
        const mobileSel = step.targetMobile || step.target;
        const desktopSel = step.target;
        const selector = isMobile() ? mobileSel : desktopSel;
        if (!selector) return null;
        return document.querySelector(selector);
    }

    function clearActiveTarget() {
        if (activeTarget) {
            activeTarget.classList.remove('portal-onboarding-target');
            activeTarget = null;
        }
    }

    function markComplete() {
        if (!shouldPersistCompletion || completionSent || !completeUrl) return;
        completionSent = true;
        const payload = JSON.stringify({});
        try {
            if (navigator.sendBeacon) {
                const blob = new Blob([payload], { type: 'application/json' });
                if (navigator.sendBeacon(completeUrl, blob)) return;
            }
        } catch (_) { /* fallback */ }
        fetch(completeUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
            credentials: 'same-origin',
            keepalive: true,
            body: payload,
        }).catch(() => { completionSent = false; });
    }

    function closeTour() {
        clearActiveTarget();
        root.classList.add('d-none');
        root.classList.remove('is-open');
        document.body.classList.remove('portal-onboarding-active');
        if (spotlight) spotlight.style.display = 'none';
        markComplete();
    }

    function spotlightShape(target) {
        if (!target) {
            return { padding: 12, radius: '1.1rem', compact: false };
        }
        if (target.matches('.top-navbar-icon-btn, .top-navbar-avatar-btn, .mobile-nav-action-btn[data-launcher-toggle]')) {
            return { padding: 10, radius: '999px', compact: true };
        }
        if (target.matches('.dashboard-module-chip')) {
            return { padding: 8, radius: '1rem', compact: true };
        }
        if (target.matches('.dashboard-edit-pill-btn')) {
            return { padding: 10, radius: '999px', compact: false };
        }
        if (target.matches('#dashboardModuleBar, .dashboard-module-bar')) {
            return { padding: 12, radius: '1.25rem', compact: false };
        }
        if (target.matches('.dashboard-edit-bar')) {
            return { padding: 14, radius: '1.35rem', compact: false };
        }
        return { padding: 12, radius: '1.1rem', compact: false };
    }

    function positionSpotlight(target) {
        const card = root.querySelector('.portal-onboarding-card');
        if (!spotlight) return;

        clearActiveTarget();

        if (!target) {
            spotlight.style.display = 'none';
            card?.classList.add('portal-onboarding-card--centered');
            return;
        }

        card?.classList.remove('portal-onboarding-card--centered');
        spotlight.style.display = 'block';

        const shape = spotlightShape(target);
        const rect = target.getBoundingClientRect();
        const top = Math.max(8, rect.top - shape.padding);
        const left = Math.max(8, rect.left - shape.padding);
        const width = Math.min(window.innerWidth - left - 8, rect.width + shape.padding * 2);
        const height = Math.min(window.innerHeight - top - 8, rect.height + shape.padding * 2);

        spotlight.style.top = `${top}px`;
        spotlight.style.left = `${left}px`;
        spotlight.style.width = `${width}px`;
        spotlight.style.height = `${height}px`;
        spotlight.style.borderRadius = shape.radius;
        spotlight.dataset.compact = shape.compact ? '1' : '0';

        target.classList.add('portal-onboarding-target');
        activeTarget = target;

        positionCard(top, left, width, height, card);
    }

    function positionCard(top, left, width, height, card) {
        if (!card || card.classList.contains('portal-onboarding-card--centered')) return;
        const margin = 16;
        const cardRect = card.getBoundingClientRect();
        const cardW = cardRect.width || 320;
        const cardH = cardRect.height || 180;
        let cardTop = top + height + margin;
        let cardLeft = left;

        if (cardTop + cardH > window.innerHeight - margin) {
            cardTop = top - cardH - margin;
        }
        if (cardTop < margin) {
            cardTop = Math.min(window.innerHeight - cardH - margin, top + height + margin);
        }
        if (cardLeft + cardW > window.innerWidth - margin) {
            cardLeft = window.innerWidth - cardW - margin;
        }
        if (cardLeft < margin) cardLeft = margin;

        card.style.top = `${Math.max(margin, cardTop)}px`;
        card.style.left = `${Math.max(margin, cardLeft)}px`;
    }

    function renderStep(index) {
        const step = steps[index];
        if (!step) return;
        currentStep = index;

        const titleEl = document.getElementById('portalOnboardingTitle');
        const textEl = document.getElementById('portalOnboardingText');
        const progressEl = document.getElementById('portalOnboardingProgress');
        const backBtn = document.getElementById('portalOnboardingBack');
        const nextBtn = document.getElementById('portalOnboardingNext');
        const finishBtn = document.getElementById('portalOnboardingFinish');

        if (titleEl) titleEl.textContent = step.title || '';
        if (textEl) textEl.textContent = step.text || '';
        if (progressEl) {
            const template = boot.progressTemplate || '{current}/{total}';
            progressEl.textContent = template
                .replace('{current}', String(index + 1))
                .replace('{total}', String(steps.length));
        }

        const isFirst = index === 0;
        const isLast = index >= steps.length - 1;
        backBtn?.classList.toggle('d-none', isFirst);
        nextBtn?.classList.toggle('d-none', isLast);
        finishBtn?.classList.toggle('d-none', !isLast);

        const target = resolveTarget(step);
        if (target) {
            target.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
        }

        window.requestAnimationFrame(() => {
            positionSpotlight(target);
            window.requestAnimationFrame(() => positionSpotlight(target));
        });
    }

    function openTour() {
        root.classList.remove('d-none');
        root.classList.add('is-open');
        document.body.classList.add('portal-onboarding-active');
        renderStep(0);
    }

    function goNext() {
        if (currentStep >= steps.length - 1) {
            closeTour();
            return;
        }
        renderStep(currentStep + 1);
    }

    function goBack() {
        if (currentStep <= 0) return;
        renderStep(currentStep - 1);
    }

    document.getElementById('portalOnboardingNext')?.addEventListener('click', goNext);
    document.getElementById('portalOnboardingFinish')?.addEventListener('click', closeTour);
    document.getElementById('portalOnboardingBack')?.addEventListener('click', goBack);
    document.getElementById('portalOnboardingSkip')?.addEventListener('click', closeTour);
    document.getElementById('portalOnboardingBtn')?.addEventListener('click', openTour);
    root.querySelector('[data-portal-onboarding-dismiss]')?.addEventListener('click', closeTour);

    document.addEventListener('keydown', (e) => {
        if (!root.classList.contains('is-open')) return;
        if (e.key === 'Escape') {
            e.preventDefault();
            closeTour();
        } else if (e.key === 'ArrowRight') {
            e.preventDefault();
            goNext();
        } else if (e.key === 'ArrowLeft') {
            e.preventDefault();
            goBack();
        }
    });

    window.addEventListener('resize', () => {
        if (root.classList.contains('is-open')) renderStep(currentStep);
    });
    window.addEventListener('scroll', () => {
        if (root.classList.contains('is-open')) {
            const step = steps[currentStep];
            positionSpotlight(resolveTarget(step));
        }
    }, true);

    window.openPortalOnboardingTour = openTour;

    if (boot.autoOpen === true) {
        window.setTimeout(openTour, 450);
    }
})();
