/**
 * Embedded PDF viewer (PDF.js) — mobile only.
 * Desktop uses the browser-native PDF iframe.
 *
 * Layout: scroll container (root) wraps a zoom layer (transform only when zoomed).
 * At 1x: native vertical scroll through pages. Pinch/double-tap zoom stays inside
 * the PDF pane so the portal header never scales.
 */
(function (global) {
    'use strict';

    var PDFJS_VERSION = '3.11.174';
    var PDFJS_BASE = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@' + PDFJS_VERSION;
    var loadPromise = null;
    var DESKTOP_MQ = '(pointer: fine) and (min-width: 768px)';

    function isDesktopNativePdf() {
        try {
            return window.matchMedia(DESKTOP_MQ).matches;
        } catch (e) {
            return window.innerWidth >= 768 && !('ontouchstart' in window);
        }
    }

    function loadPdfJs() {
        if (global.pdfjsLib) {
            return Promise.resolve(global.pdfjsLib);
        }
        if (loadPromise) {
            return loadPromise;
        }
        loadPromise = new Promise(function (resolve, reject) {
            var script = document.createElement('script');
            script.src = PDFJS_BASE + '/build/pdf.min.js';
            script.async = true;
            script.onload = function () {
                if (!global.pdfjsLib) {
                    reject(new Error('pdfjsLib missing after load'));
                    return;
                }
                global.pdfjsLib.GlobalWorkerOptions.workerSrc =
                    PDFJS_BASE + '/build/pdf.worker.min.js';
                resolve(global.pdfjsLib);
            };
            script.onerror = function () {
                loadPromise = null;
                reject(new Error('Failed to load PDF.js'));
            };
            document.head.appendChild(script);
        });
        return loadPromise;
    }

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function setStatus(root, html, isError) {
        var status = root.querySelector('.pdf-embed-status');
        if (!status) return;
        status.classList.toggle('pdf-embed-status--error', !!isError);
        status.innerHTML = html;
        status.hidden = !html;
    }

    function pagePlaceholder(pageNum) {
        var wrap = document.createElement('div');
        wrap.className = 'pdf-embed-page';
        wrap.dataset.page = String(pageNum);
        wrap.setAttribute('aria-label', 'Seite ' + pageNum);
        var canvas = document.createElement('canvas');
        canvas.className = 'pdf-embed-canvas';
        wrap.appendChild(canvas);
        return wrap;
    }

    function lockViewportForPdfZoom() {
        var meta = document.querySelector('meta[name="viewport"]');
        if (!meta) return;
        if (!meta.dataset.pdfEmbedPrev) {
            meta.dataset.pdfEmbedPrev = meta.getAttribute('content') || '';
        }
        meta.setAttribute(
            'content',
            'width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover'
        );
    }

    /**
     * Pinch + double-tap zoom + momentum-pan on the zoom layer.
     *
     * Koordinatensystem:
     *   tx/ty sind Verschiebungen im CSS-Koordinatensystem des Scrollers
     *   (ohne scrollTop), d.h. der Zoom-Ursprung wird immer relativ zur
     *   sichtbaren Viewport-Position des Fingers berechnet.
     *
     * Beim 1x-Zoom: natives Scroll bleibt komplett unangetastet.
     * Beim Pinch:   sofort preventDefault — kein gleichzeitiges Scrollen.
     * Im Zoom-Modus (1x+): Pan per transform + Momentum (Fling) nach
     *   Finger-Abheben, damit schnelles Wischen natürlich weiterfährt.
     */
    function enableContainedZoom(scroller, zoomLayer) {
        var MIN = 1;
        var MAX = 4;
        var scale = 1;
        var tx = 0;
        var ty = 0;

        var pointers = Object.create(null);
        var pinch = null;
        var pan = null;
        var moved = false;
        var didPinch = false;
        var pinchActive = false;
        var lastTapTime = 0;
        var lastTapX = 0;
        var lastTapY = 0;

        // Momentum / Fling
        var flingRaf = null;
        var flingVx = 0;
        var flingVy = 0;
        var FLING_FRICTION = 0.88;
        var FLING_MIN = 0.4;

        function isZoomed() { return scale > 1.01; }

        function applyTransform() {
            if (!isZoomed()) {
                zoomLayer.style.transform = '';
                scroller.classList.remove('pdf-embed--zoomed');
                return;
            }
            zoomLayer.style.transform =
                'translate(' + tx + 'px, ' + ty + 'px) scale(' + scale + ')';
            scroller.classList.add('pdf-embed--zoomed');
        }

        function clampPan() {
            if (!isZoomed()) { tx = 0; ty = 0; return; }
            var rect = scroller.getBoundingClientRect();
            var contentW = zoomLayer.offsetWidth  || zoomLayer.scrollWidth;
            var contentH = zoomLayer.offsetHeight || zoomLayer.scrollHeight;
            var scaledW = contentW * scale;
            var scaledH = contentH * scale;
            // transform-origin ist 0 0, d.h. tx/ty verschieben ab der oberen linken Ecke.
            // tx darf maximal 0 sein (kein Überhang links) und minimal (rect.width - scaledW).
            // Wenn scaledW < rect.width → zentrieren
            if (scaledW <= rect.width) {
                tx = (rect.width - scaledW) / 2;
            } else {
                tx = Math.min(0, Math.max(rect.width - scaledW, tx));
            }
            if (scaledH <= rect.height) {
                ty = (rect.height - scaledH) / 2;
            } else {
                ty = Math.min(0, Math.max(rect.height - scaledH, ty));
            }
        }

        function stopFling() {
            if (flingRaf) { cancelAnimationFrame(flingRaf); flingRaf = null; }
            flingVx = 0;
            flingVy = 0;
        }

        function startFling() {
            if (!isZoomed()) return;
            if (Math.abs(flingVx) < FLING_MIN && Math.abs(flingVy) < FLING_MIN) return;
            function step() {
                flingVx *= FLING_FRICTION;
                flingVy *= FLING_FRICTION;
                tx += flingVx;
                ty += flingVy;
                clampPan();
                applyTransform();
                if (Math.abs(flingVx) > FLING_MIN || Math.abs(flingVy) > FLING_MIN) {
                    flingRaf = requestAnimationFrame(step);
                } else {
                    flingRaf = null;
                }
            }
            flingRaf = requestAnimationFrame(step);
        }

        function pointerList() {
            return Object.keys(pointers).map(function (id) { return pointers[id]; });
        }

        function dist(a, b) {
            var dx = a.x - b.x; var dy = a.y - b.y;
            return Math.sqrt(dx * dx + dy * dy);
        }

        /**
         * Zoom um einen Bildschirmpunkt herum.
         * clientX/Y: Viewport-Koordinaten des Fingers.
         * transform-origin ist 0 0 → Formel:
         *   neues tx = finger_im_scroller - inhaltspunkt * nextScale
         *
         * scrollTop wird eingerechnet: vor dem ersten Zoom ist overflow:auto
         * und der Scroller kann gescrollt sein. Danach ist overflow:hidden
         * und scrollTop = 0. Deshalb wird scrollTop nur berücksichtigt wenn
         * der Scale-Wechsel von 1x auf >1x passiert (baseTy == 0 und scrollTop > 0).
         */
        function setScaleAround(clientX, clientY, nextScale, baseScale, baseTx, baseTy) {
            nextScale = Math.max(MIN, Math.min(MAX, nextScale));
            var rect = scroller.getBoundingClientRect();
            var fx = clientX - rect.left;
            // Beim Übergang 1x → gezoomt: scrollTop einrechnen damit der
            // sichtbare Fingerpunkt korrekt gemappt wird.
            // Im gezoomten Zustand ist scrollTop bereits 0 (overflow:hidden).
            var scrollOffset = (baseScale <= 1.01) ? scroller.scrollTop : 0;
            var fy = clientY - rect.top + scrollOffset;
            // Inhaltspunkt unter dem Finger im unscalierten Raum
            var contentX = (fx - baseTx) / baseScale;
            var contentY = (fy - baseTy) / baseScale;
            tx = fx - contentX * nextScale;
            ty = fy - contentY * nextScale;
            scale = nextScale;
            if (!isZoomed()) {
                scale = 1; tx = 0; ty = 0;
            } else {
                clampPan();
            }
            applyTransform();
        }

        // ── Pointer-Events ─────────────────────────────────────────────────

        scroller.addEventListener('pointerdown', function (e) {
            if (e.pointerType === 'mouse' && e.button !== 0) return;
            stopFling();
            pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
            moved = false;

            var pts = pointerList();
            if (pts.length === 2) {
                e.preventDefault();
                didPinch = true;
                pinchActive = true;
                pan = null;
                pinch = {
                    startDist: dist(pts[0], pts[1]) || 1,
                    startScale: scale,
                    startTx: tx,
                    startTy: ty,
                    originX: (pts[0].x + pts[1].x) / 2,
                    originY: (pts[0].y + pts[1].y) / 2
                };
                try { scroller.setPointerCapture(e.pointerId); } catch (_) {}
            } else if (pts.length === 1 && isZoomed()) {
                pan = { x: e.clientX, y: e.clientY, t: Date.now(), vx: 0, vy: 0 };
                try { scroller.setPointerCapture(e.pointerId); } catch (_) {}
            }
            // 1x + 1 Finger → natives Scrollen erlaubt
        }, { passive: false });

        scroller.addEventListener('pointermove', function (e) {
            if (!pointers[e.pointerId]) return;
            var prev = pointers[e.pointerId];
            var dx = e.clientX - prev.x;
            var dy = e.clientY - prev.y;
            if (Math.abs(dx) > 3 || Math.abs(dy) > 3) moved = true;
            pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
            var pts = pointerList();

            if (pinch && pts.length >= 2) {
                e.preventDefault();
                var d = dist(pts[0], pts[1]);
                var midX = (pts[0].x + pts[1].x) / 2;
                var midY = (pts[0].y + pts[1].y) / 2;
                var next = pinch.startScale * (d / pinch.startDist);
                // Zoom: Ursprung = Startmittelpunkt der Finger (konstant),
                // dann Versatz durch Mittelpunkt-Wanderung dazuaddieren
                setScaleAround(
                    pinch.originX, pinch.originY,
                    next,
                    pinch.startScale, pinch.startTx, pinch.startTy
                );
                // Mittelpunktversatz (Translation der Finger) einrechnen
                tx += midX - pinch.originX;
                ty += midY - pinch.originY;
                clampPan();
                applyTransform();
            } else if (pan && pts.length === 1 && isZoomed()) {
                e.preventDefault();
                var now = Date.now();
                var dt = Math.max(1, now - pan.t);
                // Geschwindigkeit für Fling-Berechnung tracken (exponentieller Glättung)
                pan.vx = (pan.vx * 0.6) + (dx / dt * 16 * 0.4);
                pan.vy = (pan.vy * 0.6) + (dy / dt * 16 * 0.4);
                pan.t = now;
                tx += dx;
                ty += dy;
                pan.x = e.clientX;
                pan.y = e.clientY;
                clampPan();
                applyTransform();
            }
        }, { passive: false });

        function onPointerEnd(e) {
            var wasInPointers = !!pointers[e.pointerId];
            delete pointers[e.pointerId];
            var pts = pointerList();

            if (pts.length < 2) pinch = null;
            if (pts.length === 0) pinchActive = false;

            if (pts.length === 1 && isZoomed()) {
                pan = { x: pts[0].x, y: pts[0].y, t: Date.now(), vx: 0, vy: 0 };
            } else if (pts.length === 0) {
                // Fling starten wenn der letzte Pan-Finger gehoben wird
                if (pan && isZoomed()) {
                    flingVx = pan.vx;
                    flingVy = pan.vy;
                    startFling();
                }
                pan = null;
            }

            if (!wasInPointers) return;
            if (e.pointerType === 'mouse') return;
            if (pts.length > 0) return;
            if (didPinch) { didPinch = false; return; }
            if (moved) return;

            // Double-tap
            var now = Date.now();
            var dt = now - lastTapTime;
            var ddx = Math.abs(e.clientX - lastTapX);
            var ddy = Math.abs(e.clientY - lastTapY);
            if (dt < 280 && ddx < 28 && ddy < 28) {
                e.preventDefault();
                if (scale > 1.2) {
                    scale = 1; tx = 0; ty = 0;
                    applyTransform();
                } else {
                    setScaleAround(e.clientX, e.clientY, 2.5, scale, tx, ty);
                }
                lastTapTime = 0;
            } else {
                lastTapTime = now;
                lastTapX = e.clientX;
                lastTapY = e.clientY;
            }
        }

        scroller.addEventListener('pointerup', onPointerEnd);
        scroller.addEventListener('pointercancel', onPointerEnd);

        // ── Touch-Events: Pinch/Zoom-Scroll-Konflikte blockieren ───────────
        // iOS Safari leitet Scroll schon beim touchstart ein → sofort stoppen
        scroller.addEventListener('touchstart', function (e) {
            if (e.touches.length >= 2) e.preventDefault();
        }, { passive: false });

        scroller.addEventListener('gesturestart', function (e) { e.preventDefault(); });
        scroller.addEventListener('gesturechange', function (e) { e.preventDefault(); });

        scroller.addEventListener('touchmove', function (e) {
            if (e.touches.length >= 2 || pinchActive || isZoomed()) {
                e.preventDefault();
            }
        }, { passive: false });

        // ── Trackpad-Pinch-Zoom (Desktop) ──────────────────────────────────
        scroller.addEventListener('wheel', function (e) {
            if (!(e.ctrlKey || e.metaKey)) return;
            e.preventDefault();
            var factor = e.deltaY < 0 ? 1.08 : 1 / 1.08;
            setScaleAround(e.clientX, e.clientY, scale * factor, scale, tx, ty);
        }, { passive: false });

        applyTransform();
    }

    function mountNativeIframe(root) {
        var url = root.getAttribute('data-pdf-url');
        var title = root.getAttribute('aria-label') || 'PDF Viewer';
        if (!url) return;
        root.classList.add('file-viewer-pdf-native');
        root.classList.remove('file-viewer-pdf-embed');
        root.innerHTML =
            '<iframe class="file-viewer-pdf-frame" src="' + escapeHtml(url) +
            '#view=FitH" title="' + escapeHtml(title) + '" allowfullscreen></iframe>';
    }

    function mountPdfJs(root) {
        var url = root.getAttribute('data-pdf-url');
        var downloadUrl = root.getAttribute('data-download-url') || url;
        var loadingText = root.getAttribute('data-loading') || 'PDF wird geladen…';
        var errorText = root.getAttribute('data-error') || 'PDF konnte nicht angezeigt werden.';
        var downloadLabel = root.getAttribute('data-download-label') || 'Herunterladen';

        if (!url) {
            root.innerHTML = '<div class="pdf-embed-status pdf-embed-status--error" role="status">' +
                escapeHtml(errorText) + '</div>';
            return;
        }

        lockViewportForPdfZoom();
        root.classList.add('file-viewer-pdf-embed', 'pdf-embed--mobile');

        root.innerHTML =
            '<div class="pdf-embed-status" role="status">' + escapeHtml(loadingText) + '</div>' +
            '<div class="pdf-embed-zoom">' +
            '  <div class="pdf-embed-pages" hidden></div>' +
            '</div>';

        var pagesEl = root.querySelector('.pdf-embed-pages');
        var zoomEl = root.querySelector('.pdf-embed-zoom');
        var rendered = Object.create(null);
        var pdfDoc = null;
        var renderToken = 0;

        function availableWidth() {
            var pad = 16;
            return Math.max(280, Math.floor((root.clientWidth || root.offsetWidth || 320) - pad));
        }

        function renderPage(pageNum) {
            if (!pdfDoc || rendered[pageNum]) {
                return Promise.resolve();
            }
            var pageEl = pagesEl.querySelector('.pdf-embed-page[data-page="' + pageNum + '"]');
            if (!pageEl) {
                return Promise.resolve();
            }
            rendered[pageNum] = true;
            var token = renderToken;

            return pdfDoc.getPage(pageNum).then(function (page) {
                if (token !== renderToken) return;

                var canvas = pageEl.querySelector('canvas');
                var context = canvas.getContext('2d', { alpha: false });
                var baseViewport = page.getViewport({ scale: 1 });
                var cssWidth = availableWidth();
                var pageScale = cssWidth / baseViewport.width;
                var outputScale = Math.min(window.devicePixelRatio || 1, 2);
                var viewport = page.getViewport({ scale: pageScale });

                canvas.width = Math.floor(viewport.width * outputScale);
                canvas.height = Math.floor(viewport.height * outputScale);
                canvas.style.width = Math.floor(viewport.width) + 'px';
                canvas.style.height = Math.floor(viewport.height) + 'px';
                pageEl.style.width = Math.floor(viewport.width) + 'px';

                var transform = outputScale !== 1
                    ? [outputScale, 0, 0, outputScale, 0, 0]
                    : null;

                return page.render({
                    canvasContext: context,
                    viewport: viewport,
                    transform: transform
                }).promise;
            }).catch(function () {
                rendered[pageNum] = false;
            });
        }

        function observePages() {
            if (!('IntersectionObserver' in window)) {
                var chain = Promise.resolve();
                for (var i = 1; i <= pdfDoc.numPages; i++) {
                    (function (n) {
                        chain = chain.then(function () { return renderPage(n); });
                    })(i);
                }
                return;
            }

            var observer = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (!entry.isIntersecting) return;
                    var n = parseInt(entry.target.getAttribute('data-page'), 10);
                    if (n) renderPage(n);
                });
            }, {
                root: root,
                rootMargin: '320px 0px',
                threshold: 0.01
            });

            Array.prototype.forEach.call(pagesEl.children, function (el) {
                observer.observe(el);
            });
            root._pdfEmbedObserver = observer;
        }

        function rebuildPages() {
            renderToken += 1;
            rendered = Object.create(null);
            if (root._pdfEmbedObserver) {
                root._pdfEmbedObserver.disconnect();
                root._pdfEmbedObserver = null;
            }
            pagesEl.innerHTML = '';
            for (var i = 1; i <= pdfDoc.numPages; i++) {
                pagesEl.appendChild(pagePlaceholder(i));
            }
            var seed = Math.min(2, pdfDoc.numPages);
            var chain = Promise.resolve();
            for (var p = 1; p <= seed; p++) {
                (function (n) {
                    chain = chain.then(function () { return renderPage(n); });
                })(p);
            }
            chain.then(observePages);
        }

        var resizeTimer = null;
        function onResize() {
            if (!pdfDoc) return;
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(rebuildPages, 180);
        }

        loadPdfJs()
            .then(function (pdfjsLib) {
                return pdfjsLib.getDocument({
                    url: url,
                    withCredentials: true
                }).promise;
            })
            .then(function (pdf) {
                pdfDoc = pdf;
                setStatus(root, '', false);
                pagesEl.hidden = false;
                rebuildPages();
                enableContainedZoom(root, zoomEl);
                window.addEventListener('resize', onResize, { passive: true });
                window.addEventListener('orientationchange', onResize, { passive: true });
            })
            .catch(function () {
                setStatus(
                    root,
                    '<p class="mb-3">' + escapeHtml(errorText) + '</p>' +
                    '<a class="btn btn-outline-primary files-pill-btn" href="' + escapeHtml(downloadUrl) + '">' +
                    '<i class="bi bi-download"></i> ' + escapeHtml(downloadLabel) +
                    '</a>',
                    true
                );
            });
    }

    function mount(root) {
        if (!root || root.dataset.pdfEmbedReady === '1') {
            return;
        }
        root.dataset.pdfEmbedReady = '1';

        if (isDesktopNativePdf()) {
            mountNativeIframe(root);
            return;
        }
        mountPdfJs(root);
    }

    function autoMount(selector) {
        var nodes = document.querySelectorAll(selector || '[data-pdf-embed]');
        Array.prototype.forEach.call(nodes, mount);
    }

    global.PortalPdfEmbed = {
        mount: mount,
        autoMount: autoMount,
        isDesktopNativePdf: isDesktopNativePdf
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            autoMount();
        });
    } else {
        autoMount();
    }
})(window);
