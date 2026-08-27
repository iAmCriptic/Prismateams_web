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

    /**
     * Enhance markdown HTML root (MathJax + Mermaid).
     * @param {Element|string|null} root
     * @returns {Promise}
     */
    function enhanceMarkdown(root) {
        const rootEl = resolveRoot(root);
        if (!rootEl) return Promise.resolve();
        return Promise.all([typesetMath(rootEl), renderMermaid(rootEl)]);
    }

    window.FilesMarkdownEnhance = {
        enhance: enhanceMarkdown,
        typesetMath: typesetMath,
        renderMermaid: renderMermaid
    };
})(window);
