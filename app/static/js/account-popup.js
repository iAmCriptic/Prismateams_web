(function initAccountPopup() {
    const root = document.getElementById('accountMenu');
    const toggle = document.getElementById('accountMenuBtn');
    if (!root || !toggle) return;

    const closeBtn = root.querySelector('[data-account-close]');

    function closeLauncher() {
        const launcher = document.getElementById('moduleLauncher');
        const launcherBtn = document.getElementById('moduleLauncherBtn');
        if (launcher) launcher.classList.remove('is-open', 'is-editing');
        if (launcherBtn) {
            launcherBtn.classList.remove('is-open');
            launcherBtn.setAttribute('aria-expanded', 'false');
        }
    }

    function setOpen(open) {
        root.classList.toggle('is-open', open);
        toggle.classList.toggle('is-open', open);
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        if (open) closeLauncher();
    }

    toggle.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        setOpen(!root.classList.contains('is-open'));
    });

    if (closeBtn) {
        closeBtn.addEventListener('click', function (event) {
            event.preventDefault();
            setOpen(false);
            toggle.focus();
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
            toggle.focus();
        }
    });
})();
