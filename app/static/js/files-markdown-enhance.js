/**
 * Shared post-process for Files Markdown (/view + edit preview):
 * MathJax typesetting and Mermaid diagrams.
 */
(function (window) {
    'use strict';

    const MATHJAX_CDN = 'https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js';
    const MERMAID_CDN = 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js';

    let mathJaxLoading = null;
    let mermaidLoading = null;
    let mermaidReady = false;

    function ensureMathJaxConfig() {
        if (window.MathJax && window.MathJax.typesetPromise) return;
        window.MathJax = window.MathJax || {
            tex: {
                inlineMath: [['$', '$'], ['\\(', '\\)']],
                displayMath: [['$$', '$$'], ['\\[', '\\]']],
                processEscapes: true,
                processEnvironments: true
            },
            options: {
                ignoreHtmlClass: 'tex2jax_ignore',
                processHtmlClass: 'tex2jax_process',
                // Assistive MathML oft Ursache für Mini-Scrollbars neben Formeln
                renderActions: {
                    assistiveMml: []
                }
            }
        };
    }

    function loadMathJax() {
        ensureMathJaxConfig();
        if (window.MathJax && typeof window.MathJax.typesetPromise === 'function') {
            return Promise.resolve(window.MathJax);
        }
        if (mathJaxLoading) return mathJaxLoading;

        mathJaxLoading = new Promise((resolve, reject) => {
            const existing = document.getElementById('MathJax-script');
            if (existing) {
                existing.addEventListener('load', () => resolve(window.MathJax));
                existing.addEventListener('error', reject);
                return;
            }
            const script = document.createElement('script');
            script.id = 'MathJax-script';
            script.async = true;
            script.src = MATHJAX_CDN;
            script.onload = () => resolve(window.MathJax);
            script.onerror = reject;
            document.head.appendChild(script);
        });
        return mathJaxLoading;
    }

    function loadMermaid() {
        if (window.mermaid) return Promise.resolve(window.mermaid);
        if (mermaidLoading) return mermaidLoading;

        mermaidLoading = new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = MERMAID_CDN;
            script.async = true;
            script.onload = () => resolve(window.mermaid);
            script.onerror = reject;
            document.head.appendChild(script);
        });
        return mermaidLoading;
    }

    function resolveRoot(root) {
        if (!root) {
            return document.querySelector('.markdown-content');
        }
        if (typeof root === 'string') {
            return document.querySelector(root);
        }
        return root;
    }

    function typesetMath(rootEl) {
        return loadMathJax()
            .then(() => {
                if (!window.MathJax || typeof window.MathJax.typesetPromise !== 'function') {
                    return;
                }
                const nodes = rootEl ? [rootEl] : undefined;
                return window.MathJax.typesetPromise(nodes);
            })
            .catch((err) => {
                console.error('MathJax rendering error:', err);
            });
    }

    function renderMermaid(rootEl) {
        if (!rootEl) return Promise.resolve();
        const nodes = rootEl.querySelectorAll('.mermaid');
        if (!nodes.length) return Promise.resolve();

        return loadMermaid()
            .then((mermaid) => {
                if (!mermaid) return;
                if (!mermaidReady) {
                    const dark = document.documentElement.getAttribute('data-bs-theme') === 'dark';
                    mermaid.initialize({
                        startOnLoad: false,
                        theme: dark ? 'dark' : 'default',
                        securityLevel: 'strict'
                    });
                    mermaidReady = true;
                }
                // Re-run after dynamic HTML inject
                nodes.forEach((node) => {
                    if (node.getAttribute('data-processed')) {
                        node.removeAttribute('data-processed');
                    }
                });
                return mermaid.run({ nodes: Array.from(nodes) });
            })
            .catch((err) => {
                console.error('Mermaid rendering error:', err);
            });
    }

    const previewCache = {};
    let hoverTimer = null;
    let hideTimer = null;
    let activeAnchor = null;

    function previewI18n(path, fallback) {
        const pack = (window.MARKDOWN_EDITOR_I18N && window.MARKDOWN_EDITOR_I18N.preview) || {};
        return pack[path] || fallback;
    }

    function ensureHoverCard() {
        let card = document.getElementById('markdownLinkHoverCard');
        if (card) return card;
        card = document.createElement('div');
        card.id = 'markdownLinkHoverCard';
        card.className = 'md-link-hover';
        card.hidden = true;
        card.innerHTML =
            '<div class="md-link-hover-head">' +
                '<span class="md-link-hover-url"></span>' +
                '<span class="md-link-hover-actions">' +
                    '<a class="md-link-hover-btn" data-md-hover-open target="_blank" rel="noopener">' +
                        '<i class="bi bi-box-arrow-up-right" aria-hidden="true"></i>' +
                    '</a>' +
                '</span>' +
            '</div>' +
            '<div class="md-link-hover-body">' +
                '<div class="md-link-hover-icon" aria-hidden="true"><i class="bi bi-file-earmark-text"></i></div>' +
                '<div class="md-link-hover-copy">' +
                    '<div class="md-link-hover-title"></div>' +
                    '<div class="md-link-hover-desc"></div>' +
                '</div>' +
            '</div>';
        document.body.appendChild(card);
        card.addEventListener('mouseenter', function () {
            window.clearTimeout(hideTimer);
        });
        card.addEventListener('mouseleave', scheduleHideHover);
        return card;
    }

    function hideHoverCard() {
        const card = document.getElementById('markdownLinkHoverCard');
        if (card) card.hidden = true;
        activeAnchor = null;
    }

    function scheduleHideHover() {
        window.clearTimeout(hideTimer);
        hideTimer = window.setTimeout(hideHoverCard, 220);
    }

    function fillHoverCard(card, data, href) {
        const urlEl = card.querySelector('.md-link-hover-url');
        const titleEl = card.querySelector('.md-link-hover-title');
        const descEl = card.querySelector('.md-link-hover-desc');
        const openEl = card.querySelector('[data-md-hover-open]');
        const iconEl = card.querySelector('.md-link-hover-icon i');
        const displayUrl = (data && data.url) || href;
        if (urlEl) urlEl.textContent = displayUrl;
        if (openEl) {
            openEl.href = href;
            openEl.title = previewI18n('open', 'Öffnen');
        }
        if (titleEl) {
            titleEl.textContent = (data && data.title) || previewI18n('unavailable_title', 'Keine Vorschau');
        }
        if (descEl) {
            descEl.textContent = (data && data.description) || '';
        }
        if (iconEl) {
            iconEl.className = data && data.ok
                ? 'bi bi-file-earmark-text'
                : 'bi bi-exclamation-circle';
        }
        card.classList.toggle('is-error', !(data && data.ok));
    }

    function positionHoverCard(card, anchor) {
        const rect = anchor.getBoundingClientRect();
        card.hidden = false;
        const width = card.offsetWidth || 360;
        const height = card.offsetHeight || 140;
        let left = rect.left;
        let top = rect.bottom + 8;
        if (left + width > window.innerWidth - 12) left = window.innerWidth - width - 12;
        if (top + height > window.innerHeight - 12) top = rect.top - height - 8;
        card.style.left = Math.max(8, left) + 'px';
        card.style.top = Math.max(8, top) + 'px';
    }

    function fetchPreview(url) {
        if (previewCache[url]) return Promise.resolve(previewCache[url]);
        const endpoint = window.MARKDOWN_LINK_PREVIEW_URL;
        if (!endpoint) {
            let host = url;
            try { host = new URL(url, window.location.origin).hostname || url; } catch (e) { /* keep */ }
            const fallback = {
                ok: false,
                url: url,
                title: host,
                description: previewI18n('unavailable_body', 'Die Vorschau konnte nicht geladen werden.')
            };
            previewCache[url] = fallback;
            return Promise.resolve(fallback);
        }
        return fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify({ url: url })
        }).then(function (res) {
            return res.json().catch(function () { return null; });
        }).then(function (data) {
            const payload = data || {
                ok: false,
                url: url,
                title: previewI18n('unavailable_title', 'Keine Vorschau'),
                description: previewI18n('unavailable_body', 'Die Vorschau konnte nicht geladen werden.')
            };
            previewCache[url] = payload;
            return payload;
        }).catch(function () {
            const payload = {
                ok: false,
                url: url,
                title: previewI18n('unavailable_title', 'Keine Vorschau'),
                description: previewI18n('unavailable_body', 'Die Vorschau konnte nicht geladen werden.')
            };
            previewCache[url] = payload;
            return payload;
        });
    }

    function bindLinkHover(rootEl) {
        if (!rootEl || rootEl.dataset.mdLinkHover === '1') return;
        rootEl.dataset.mdLinkHover = '1';
        rootEl.addEventListener('mouseover', function (e) {
            const anchor = e.target.closest && e.target.closest('a[href]');
            if (!anchor || !rootEl.contains(anchor)) return;
            if (anchor.closest('.md-link-hover')) return;
            const href = anchor.getAttribute('href') || '';
            if (!href || href.charAt(0) === '#' || href.indexOf('javascript:') === 0 || href.indexOf('mailto:') === 0) {
                return;
            }
            window.clearTimeout(hoverTimer);
            hoverTimer = window.setTimeout(function () {
                activeAnchor = anchor;
                const href = anchor.getAttribute('href');
                const card = ensureHoverCard();
                fillHoverCard(card, {
                    ok: true,
                    url: href,
                    title: previewI18n('loading', 'Lade Vorschau…'),
                    description: ''
                }, href);
                positionHoverCard(card, anchor);
                fetchPreview(href).then(function (data) {
                    if (activeAnchor !== anchor) return;
                    fillHoverCard(card, data, href);
                    positionHoverCard(card, anchor);
                });
            }, 280);
        });
        rootEl.addEventListener('mouseout', function (e) {
            const anchor = e.target.closest && e.target.closest('a[href]');
            if (!anchor) return;
            const related = e.relatedTarget;
            if (related && (anchor.contains(related) || (related.closest && related.closest('#markdownLinkHoverCard')))) {
                return;
            }
            window.clearTimeout(hoverTimer);
            scheduleHideHover();
        });
    }

    /**
     * Enhance markdown HTML root (MathJax + Mermaid + link hover cards).
     * @param {Element|string|null} root
     * @returns {Promise}
     */
    function enhanceMarkdown(root) {
        const rootEl = resolveRoot(root);
        if (!rootEl) return Promise.resolve();
        bindLinkHover(rootEl);
        return Promise.all([typesetMath(rootEl), renderMermaid(rootEl)]);
    }

    window.FilesMarkdownEnhance = {
        enhance: enhanceMarkdown,
        typesetMath: typesetMath,
        renderMermaid: renderMermaid
    };
})(window);
