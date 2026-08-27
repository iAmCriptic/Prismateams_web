(function initModuleLauncher() {
    const root = document.getElementById('moduleLauncher');
    const toggles = Array.from(document.querySelectorAll('[data-launcher-toggle]'));
    if (!root || !toggles.length) return;

    const panel = root.querySelector('.module-launcher-panel');
    const editBtn = root.querySelector('[data-launcher-edit-open]');
    const cancelBtn = root.querySelector('[data-launcher-cancel]');
    const doneBtn = root.querySelector('[data-launcher-done]');
    const favView = root.querySelector('[data-launcher-fav-view]');
    const allView = root.querySelector('[data-launcher-all-view]');
    const favEdit = root.querySelector('[data-launcher-fav-edit]');
    const allEdit = root.querySelector('[data-launcher-all-edit]');
    const catalog = root.querySelector('[data-launcher-catalog]');
    const rail = document.querySelector('[data-favorites-rail]');
    const railAdd = document.querySelector('[data-favorites-rail-add]');
    const saveUrl = root.getAttribute('data-save-url') || '/api/nav/favorites';
    const currentKey = (document.getElementById('desktopFavoritesRail') || root).getAttribute('data-current-nav') || '';

    let sortables = [];
    let lastFocus = null;
    let dragging = false;

    function isOpen() {
        return root.classList.contains('is-open');
    }

    function closeAccountMenu() {
        const menu = document.getElementById('accountMenu');
        if (menu) menu.classList.remove('is-open');
        document.querySelectorAll('[data-account-toggle]').forEach((btn) => {
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
        if (open) {
            closeAccountMenu();
        } else {
            exitEdit();
        }
    }

    function cloneTile(source) {
        const node = source.cloneNode(true);
        node.classList.remove('sortable-ghost', 'sortable-chosen', 'sortable-drag', 'module-launcher-ghost', 'module-launcher-drag');
        return node;
    }

    function tileMarkup(source) {
        const item = cloneTile(source);
        item.removeAttribute('href');
        item.setAttribute('role', 'listitem');
        item.setAttribute('tabindex', '0');
        item.setAttribute('draggable', 'false');
        return item;
    }

    function collectKeys(container) {
        return Array.from(container.querySelectorAll('[data-nav-id]'))
            .map((el) => el.getAttribute('data-nav-id'))
            .filter(Boolean);
    }

    function destroySortables() {
        while (sortables.length) {
            try { sortables.pop().destroy(); } catch (_) { /* ignore */ }
        }
    }

    function catalogTiles() {
        const source = catalog || allView;
        return Array.from(source.querySelectorAll('.module-launcher-item[data-nav-id]'));
    }

    function catalogByKey() {
        const byKey = {};
        catalogTiles().forEach((el) => {
            byKey[el.getAttribute('data-nav-id')] = el;
        });
        return byKey;
    }

    function fillEditFromView() {
        if (!favEdit || !allEdit || !favView) return;
        favEdit.innerHTML = '';
        allEdit.innerHTML = '';
        const favKeys = [];
        favView.querySelectorAll('.module-launcher-item').forEach((el) => {
            favEdit.appendChild(tileMarkup(el));
            const key = el.getAttribute('data-nav-id');
            if (key) favKeys.push(key);
        });
        catalogTiles().forEach((el) => {
            const key = el.getAttribute('data-nav-id');
            if (favKeys.includes(key)) return;
            allEdit.appendChild(tileMarkup(el));
        });
    }

    function sortableOptions(extra) {
        return Object.assign({
            animation: 150,
            draggable: '.module-launcher-item',
            forceFallback: true,
            fallbackOnBody: true,
            fallbackTolerance: 4,
            emptyInsertThreshold: 48,
            ghostClass: 'module-launcher-ghost',
            chosenClass: 'module-launcher-chosen',
            dragClass: 'module-launcher-drag',
            onStart: function () { dragging = true; },
            onEnd: function () { dragging = false; },
        }, extra);
    }

    function bindSortables() {
        destroySortables();
        if (!window.Sortable || !favEdit || !allEdit) return;

        sortables.push(window.Sortable.create(favEdit, sortableOptions({
            group: { name: 'nav-favs', pull: true, put: true },
            onAdd: function (evt) {
                const key = evt.item.getAttribute('data-nav-id');
                const same = Array.from(favEdit.querySelectorAll('[data-nav-id]'))
                    .filter((el) => el !== evt.item && el.getAttribute('data-nav-id') === key);
                if (same.length) {
                    if (evt.from) {
                        evt.from.appendChild(evt.item);
                    } else {
                        evt.item.remove();
                    }
                }
            },
        })));

        sortables.push(window.Sortable.create(allEdit, sortableOptions({
            group: { name: 'nav-favs', pull: true, put: true },
            sort: false,
        })));
    }

    function enterEdit() {
        fillEditFromView();
        root.classList.add('is-editing');
        requestAnimationFrame(function () {
            bindSortables();
        });
    }

    function exitEdit() {
        root.classList.remove('is-editing');
        dragging = false;
        destroySortables();
    }

    function syncFavoritesRail(keys) {
        if (!rail) return;
        const byKey = catalogByKey();
        rail.innerHTML = '';
        keys.forEach((key) => {
            const src = byKey[key];
            if (!src) return;
            const link = document.createElement('a');
            link.className = 'favorites-rail-item' + (key === currentKey ? ' is-current' : '');
            link.href = src.getAttribute('data-nav-url') || src.getAttribute('href') || '#';
            link.setAttribute('data-nav-id', key);
            link.setAttribute('data-label', src.getAttribute('data-nav-label') || '');
            link.setAttribute('aria-label', src.getAttribute('data-nav-label') || key);
            const iconName = src.getAttribute('data-nav-icon') || 'bi-app';
            link.innerHTML = '<i class="bi ' + iconName + '" aria-hidden="true"></i>';
            rail.appendChild(link);
        });
        const wrap = document.getElementById('desktopFavoritesRail');
        if (wrap) wrap.classList.toggle('is-empty', keys.length === 0);
    }

    function syncMobileFavorites(keys) {
        const mobileFavorites = document.getElementById('mobileNavFavorites');
        if (!mobileFavorites) return;
        const byKey = catalogByKey();
        const activeKeys = keys.length ? keys : Object.keys(byKey);
        const limited = activeKeys.slice(0, 5);

        mobileFavorites.innerHTML = '';
        limited.forEach((key) => {
            const src = byKey[key];
            if (!src) return;
            const link = document.createElement('a');
            link.className = 'mobile-nav-favorite-link' + (key === currentKey ? ' active' : '');
            link.href = src.getAttribute('data-nav-url') || src.getAttribute('href') || '#';
            link.setAttribute('data-nav-id', key);
            link.setAttribute('aria-label', src.getAttribute('data-nav-label') || key);
            const iconName = src.getAttribute('data-nav-icon') || 'bi-app';
            link.innerHTML = '<i class="bi ' + iconName + '" aria-hidden="true"></i>';
            mobileFavorites.appendChild(link);
        });
    }

    function applyFavoritesToView(keys) {
        const byKey = catalogByKey();

        favView.innerHTML = '';
        keys.forEach((key) => {
            const src = byKey[key];
            if (!src) return;
            const tile = cloneTile(src);
            tile.setAttribute('href', src.getAttribute('data-nav-url') || src.getAttribute('href') || '#');
            favView.appendChild(tile);
        });
        if (favView.parentElement) {
            favView.parentElement.classList.toggle('is-empty', keys.length === 0);
        }

        allView.innerHTML = '';
        catalogTiles().forEach((src) => {
            const key = src.getAttribute('data-nav-id');
            if (keys.includes(key)) return;
            const tile = cloneTile(src);
            tile.setAttribute('href', src.getAttribute('data-nav-url') || src.getAttribute('href') || '#');
            allView.appendChild(tile);
        });

        syncFavoritesRail(keys);
        syncMobileFavorites(keys);
    }

    async function saveFavorites() {
        const keys = collectKeys(favEdit);
        doneBtn.disabled = true;
        try {
            const response = await fetch(saveUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ favorites: keys }),
            });
            if (!response.ok) throw new Error('save failed');
            applyFavoritesToView(keys);
            exitEdit();
        } catch (err) {
            console.error(err);
        } finally {
            doneBtn.disabled = false;
        }
    }

    toggles.forEach((toggle) => {
        toggle.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            lastFocus = toggle;
            setOpen(!isOpen());
        });
    });

    if (editBtn) {
        editBtn.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            enterEdit();
        });
    }
    if (cancelBtn) {
        cancelBtn.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            exitEdit();
        });
    }
    if (doneBtn) {
        doneBtn.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            saveFavorites();
        });
    }
    if (railAdd) {
        railAdd.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            lastFocus = railAdd;
            setOpen(true);
            enterEdit();
        });
    }

    document.addEventListener('click', function (event) {
        if (!isOpen() || dragging) return;
        if (root.contains(event.target)) return;
        if (toggles.some((toggle) => toggle.contains(event.target))) return;
        if (railAdd && (event.target === railAdd || railAdd.contains(event.target))) return;
        setOpen(false);
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && isOpen()) {
            setOpen(false);
            if (lastFocus) lastFocus.focus();
        }
    });

    if (panel) {
        panel.addEventListener('click', function (event) {
            event.stopPropagation();
        });
    }
})();
