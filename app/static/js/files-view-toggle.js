/* Deprecated stub — use js/mod-view-toggle.js.
 * Kept so any old script tags keep working without duplicating logic.
 */
(function () {
    'use strict';
    if (typeof window.initModViewToggle === 'function') {
        window.initFilesViewToggle = window.initModViewToggle;
        return;
    }
    var s = document.createElement('script');
    s.src = (document.currentScript && document.currentScript.src || '')
        .replace(/files-view-toggle\.js(?:\?.*)?$/, 'mod-view-toggle.js');
    if (!s.src || s.src === (document.currentScript && document.currentScript.src)) {
        s.src = '/static/js/mod-view-toggle.js';
    }
    document.head.appendChild(s);
})();
