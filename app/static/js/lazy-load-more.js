/**
 * Infinite / lazy "load more" via full-page fragment fetch + DOM extract.
 * Containers: [data-lazy-more] with data-lazy-page / data-lazy-has-more / data-lazy-param
 *
 * Optional:
 *   data-lazy-silent="1"     — no visible "load more" chrome; status is screen-reader only
 *   data-lazy-autochain="1"   — keep fetching the next window in the background
 *   data-lazy-root-margin      — IntersectionObserver rootMargin (default 240px 0px)
 */
(function () {
    function csrfHeaders() {
        const token = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
        return token ? { 'X-CSRFToken': token } : {};
    }

    function isSilent(el) {
        return el.getAttribute('data-lazy-silent') === '1';
    }

    function nextUrl(el) {
        const param = el.getAttribute('data-lazy-param') || 'page';
        const mode = el.getAttribute('data-lazy-mode') || 'increment';
        const url = new URL(el.getAttribute('data-lazy-url') || window.location.href, window.location.origin);
        let next;
        if (mode === 'next-value') {
            next = parseInt(el.getAttribute('data-lazy-page') || '0', 10) || 0;
        } else {
            const page = parseInt(el.getAttribute('data-lazy-page') || '1', 10) || 1;
            const step = parseInt(el.getAttribute('data-lazy-step') || '1', 10) || 1;
            next = page + step;
        }
        url.searchParams.set(param, String(next));
        return { url: url.toString(), next };
    }

    function scheduleAutochain(root) {
        if (root.getAttribute('data-lazy-autochain') !== '1') return;
        if (root.getAttribute('data-lazy-has-more') !== '1') return;
        if (root._lazyAutochainStop) return;
        if (root._lazyAutochainTimer != null) return;
        const run = () => {
            root._lazyAutochainTimer = null;
            if (root.getAttribute('data-lazy-has-more') !== '1') return;
            if (root.getAttribute('data-lazy-loading') === '1') {
                scheduleAutochain(root);
                return;
            }
            const pending = loadMore(root);
            if (pending && typeof pending.then === 'function') {
                pending.then(() => scheduleAutochain(root));
            }
        };
        if (window.requestIdleCallback) {
            root._lazyAutochainTimer = requestIdleCallback(run, { timeout: 250 });
        } else {
            root._lazyAutochainTimer = setTimeout(run, 60);
        }
    }

    async function loadMore(root) {
        if (root.getAttribute('data-lazy-loading') === '1') return;
        if (root.getAttribute('data-lazy-has-more') !== '1') return;

        const btn = root.querySelector('[data-lazy-more-btn]');
        const status = root.querySelector('[data-lazy-more-status]');
        const silent = isSilent(root);
        root.setAttribute('data-lazy-loading', '1');
        root.setAttribute('aria-busy', 'true');
        if (btn) btn.disabled = true;
        if (status && !silent) status.hidden = false;

        const { url, next } = nextUrl(root);
        let failed = false;
        try {
            const res = await fetch(url, {
                headers: Object.assign({ 'X-Requested-With': 'XMLHttpRequest' }, csrfHeaders()),
                credentials: 'same-origin',
            });
            if (!res.ok) throw new Error('load failed');
            const html = await res.text();
            const doc = new DOMParser().parseFromString(html, 'text/html');
            const selector = root.getAttribute('data-lazy-items') || '[data-lazy-item]';
            const targets = root.getAttribute('data-lazy-targets');
            const targetList = targets
                ? targets.split(',').map((s) => s.trim()).filter(Boolean)
                : null;

            if (targetList && targetList.length) {
                targetList.forEach((sel) => {
                    const dest = document.querySelector(sel);
                    const src = doc.querySelector(sel);
                    if (!dest || !src) return;
                    src.querySelectorAll(selector).forEach((node) => {
                        dest.appendChild(node.cloneNode(true));
                    });
                });
            } else {
                const dest = root.querySelector('[data-lazy-append]') || root;
                const srcRoot = doc.querySelector('[data-lazy-more]') || doc;
                srcRoot.querySelectorAll(selector).forEach((node) => {
                    dest.appendChild(node.cloneNode(true));
                });
            }

            const srcMore = doc.querySelector('[data-lazy-more]');
            const stillMore = srcMore && srcMore.getAttribute('data-lazy-has-more') === '1';
            if (srcMore && srcMore.getAttribute('data-lazy-mode') === 'next-value') {
                root.setAttribute('data-lazy-page', srcMore.getAttribute('data-lazy-page') || String(next));
            } else {
                root.setAttribute('data-lazy-page', String(next));
            }
            root.setAttribute('data-lazy-has-more', stillMore ? '1' : '0');
            if (!stillMore) {
                const wrap = root.querySelector('[data-lazy-more-wrap]');
                if (wrap) wrap.hidden = true;
            }
            root.dispatchEvent(new CustomEvent('lazy-more:loaded', { bubbles: true }));
        } catch (err) {
            failed = true;
            root._lazyAutochainStop = true;
            console.warn('lazy-load-more', err);
            if (status) {
                status.textContent = status.getAttribute('data-error') || 'Fehler beim Laden';
                status.hidden = false;
            }
        } finally {
            root.setAttribute('data-lazy-loading', '0');
            root.setAttribute('aria-busy', 'false');
            if (btn) btn.disabled = false;
            if (status && !failed) status.hidden = true;
            // Silent lists: keep fetching while the sentinel is still on screen
            // (first page shorter than the viewport). Autochain handles files.
            if (
                !failed
                && silent
                && root.getAttribute('data-lazy-autochain') !== '1'
                && root.getAttribute('data-lazy-has-more') === '1'
            ) {
                const sentinel = root.querySelector('[data-lazy-more-sentinel]');
                if (sentinel) {
                    const vh = window.innerHeight || 0;
                    const rect = sentinel.getBoundingClientRect();
                    if (rect.top <= vh + 240) {
                        loadMore(root);
                    }
                }
            }
        }
    }

    function bind(root) {
        if (!root || root._lazyMoreBound) return;
        root._lazyMoreBound = true;
        const btn = root.querySelector('[data-lazy-more-btn]');
        if (btn) {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                loadMore(root);
            });
        }
        const sentinel = root.querySelector('[data-lazy-more-sentinel]');
        if (sentinel && 'IntersectionObserver' in window) {
            const margin = root.getAttribute('data-lazy-root-margin') || '240px 0px';
            const io = new IntersectionObserver((entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) loadMore(root);
                });
            }, { rootMargin: margin });
            io.observe(sentinel);
        }
        scheduleAutochain(root);
    }

    function initLazyMedia() {
        const nodes = document.querySelectorAll('[data-lazy-src]');
        if (!nodes.length) return;
        const apply = (el) => {
            const src = el.getAttribute('data-lazy-src');
            if (!src || el.getAttribute('data-lazy-loaded') === '1') return;
            el.setAttribute('data-lazy-loaded', '1');
            if (el.tagName === 'IFRAME' || el.tagName === 'IMG') {
                el.src = src;
            }
        };
        if (!('IntersectionObserver' in window)) {
            nodes.forEach(apply);
            return;
        }
        const io = new IntersectionObserver((entries, obs) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) return;
                apply(entry.target);
                obs.unobserve(entry.target);
            });
        }, { rootMargin: '120px 0px' });
        nodes.forEach((el) => io.observe(el));
    }

    function init() {
        document.querySelectorAll('[data-lazy-more]').forEach(bind);
        initLazyMedia();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    document.addEventListener('lazy-more:loaded', () => initLazyMedia());
    window.PrismateamsLazyMore = { loadMore, bind, init };
})();
