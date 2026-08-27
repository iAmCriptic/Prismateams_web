(function initAccountPopup() {
    const root = document.getElementById('accountMenu');
    const toggles = Array.from(document.querySelectorAll('[data-account-toggle]'));
    if (!root || !toggles.length) return;

    const closeBtn = root.querySelector('[data-account-close]');
    let lastFocus = null;

    function closeLauncher() {
        const launcher = document.getElementById('moduleLauncher');
        if (launcher) launcher.classList.remove('is-open', 'is-editing');
        document.querySelectorAll('[data-launcher-toggle]').forEach((btn) => {
            btn.classList.remove('is-open');
            btn.setAttribute('aria-expanded', 'false');
        });
    }

    function setOpen(open) {
        root.classList.toggle('is-open', open);
        toggles.forEach((toggle) => {
            toggle.classList.toggle('is-open', open);
            toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
        if (open) closeLauncher();
    }

    toggles.forEach((toggle) => {
        toggle.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            lastFocus = toggle;
            setOpen(!root.classList.contains('is-open'));
        });
    });

    if (closeBtn) {
        closeBtn.addEventListener('click', function (event) {
            event.preventDefault();
            setOpen(false);
            if (lastFocus) lastFocus.focus();
        });
    }

    document.addEventListener('click', function (event) {
        if (!root.classList.contains('is-open')) return;
        if (root.contains(event.target)) return;
        setOpen(false);
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && root.classList.contains('is-open')) {
            setOpen(false);
            if (lastFocus) lastFocus.focus();
        }
    });
})();
