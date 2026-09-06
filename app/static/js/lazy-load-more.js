/**
 * Infinite / lazy "load more" via full-page fragment fetch + DOM extract.
 * Containers: [data-lazy-more] with data-lazy-page / data-lazy-has-more / data-lazy-param
 */
(function () {
    function csrfHeaders() {
        const token = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
        return token ? { 'X-CSRFToken': token } : {};
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

    async function loadMore(root) {
        if (root.getAttribute('data-lazy-loading') === '1') return;
        if (root.getAttribute('data-lazy-has-more') !== '1') return;

        const btn = root.querySelector('[data-lazy-more-btn]');
        const status = root.querySelector('[data-lazy-more-status]');
        root.setAttribute('data-lazy-loading', '1');
        if (btn) btn.disabled = true;
        if (status) status.hidden = false;

        const { url, next } = nextUrl(root);
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
            console.warn('lazy-load-more', err);
            if (status) {
                status.textContent = status.getAttribute('data-error') || 'Fehler beim Laden';
            }
        } finally {
            root.setAttribute('data-lazy-loading', '0');
            if (btn) btn.disabled = false;
            if (status) status.hidden = true;
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
            const io = new IntersectionObserver((entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) loadMore(root);
                });
            }, { rootMargin: '240px 0px' });
            io.observe(sentinel);
        }
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
