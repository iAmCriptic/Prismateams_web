(function () {
    'use strict';

    const TRANSITION_MS = 280;

    function prefersReducedMotion() {
        return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }

    function updateToggleUi(toggleEl, listBtn, gridBtn, mode) {
        if (toggleEl) {
            toggleEl.dataset.view = mode;
        }
        listBtn.classList.toggle('active', mode === 'list');
        listBtn.classList.toggle('is-active', mode === 'list');
        gridBtn.classList.toggle('active', mode === 'grid');
        gridBtn.classList.toggle('is-active', mode === 'grid');
    }

    window.initFilesViewToggle = function initFilesViewToggle(options) {
        const {
            toggleEl = null,
            listBtn,
            gridBtn,
            listPane,
            gridPane,
            stageEl = null,
            storageKey = null,
            defaultMode = 'grid',
            onSwitch = null,
        } = options || {};

        if (!listBtn || !gridBtn || !listPane || !gridPane) {
            return null;
        }

        let currentMode = defaultMode;
        let animating = false;

        function applyInstant(mode) {
            const isList = mode === 'list';
            updateToggleUi(toggleEl, listBtn, gridBtn, mode);
            if (stageEl) {
                stageEl.dataset.view = mode;
            }

            gridPane.classList.remove('files-view-pane--leave');
            listPane.classList.remove('files-view-pane--leave');

            if (isList) {
                gridPane.style.display = 'none';
                gridPane.classList.remove('files-view-pane--active');
                listPane.style.display = 'block';
                listPane.classList.add('files-view-pane--active');
                listPane.classList.remove('d-none');
                gridPane.classList.add('d-none');
            } else {
                listPane.style.display = 'none';
                listPane.classList.remove('files-view-pane--active');
                gridPane.style.display = 'block';
                gridPane.classList.add('files-view-pane--active');
                gridPane.classList.remove('d-none');
                listPane.classList.add('d-none');
            }

            currentMode = mode;
            if (storageKey) {
                window.localStorage.setItem(storageKey, mode);
            }
            if (typeof onSwitch === 'function') {
                onSwitch(mode);
            }
        }

        function setView(mode, opts) {
            const animate = !(opts && opts.animate === false);
            if (mode !== 'list' && mode !== 'grid') {
                return;
            }
            if (mode === currentMode && !animating) {
                return;
            }

            if (!animate || prefersReducedMotion()) {
                applyInstant(mode);
                return;
            }

            if (animating) {
                applyInstant(mode);
                return;
            }

            const fromPane = currentMode === 'grid' ? gridPane : listPane;
            const toPane = mode === 'grid' ? gridPane : listPane;
            const stage = stageEl || fromPane.parentElement;

            animating = true;
            updateToggleUi(toggleEl, listBtn, gridBtn, mode);
            if (stage) {
                stage.dataset.view = mode;
            }

            const fromHeight = fromPane.offsetHeight;
            if (stage && fromHeight > 0) {
                stage.style.minHeight = `${fromHeight}px`;
            }

            toPane.style.display = 'block';
            toPane.classList.remove('d-none', 'files-view-pane--active');
            fromPane.classList.add('files-view-pane--leave');

            window.requestAnimationFrame(function () {
                window.requestAnimationFrame(function () {
                    fromPane.classList.remove('files-view-pane--active');
                    toPane.classList.add('files-view-pane--active');
                });
            });

            window.setTimeout(function () {
                fromPane.style.display = 'none';
                fromPane.classList.remove('files-view-pane--leave', 'files-view-pane--active');
                fromPane.classList.add('d-none');
                toPane.classList.remove('d-none');
                if (stage) {
                    stage.style.minHeight = '';
                }
                animating = false;
                currentMode = mode;
                if (storageKey) {
                    window.localStorage.setItem(storageKey, mode);
                }
                if (typeof onSwitch === 'function') {
                    onSwitch(mode);
                }
            }, TRANSITION_MS);
        }

        listBtn.addEventListener('click', function () {
            setView('list');
        });
        gridBtn.addEventListener('click', function () {
            setView('grid');
        });

        const saved = storageKey ? window.localStorage.getItem(storageKey) : null;
        const initial = saved === 'list' || saved === 'grid' ? saved : defaultMode;
        applyInstant(initial);

        return {
            setView: setView,
            getMode: function () {
                return currentMode;
            },
        };
    };
})();
