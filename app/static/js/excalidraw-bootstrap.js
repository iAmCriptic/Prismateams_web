/**
 * ESM bootstrap for Excalidraw 0.18.1.
 * Loads React + Excalidraw via esm.sh (bare imports in the npm ESM bundle
 * cannot be resolved from local vendor/index.js without an import map).
 */
const BOOT = window.EXCALIDRAW_BOOTSTRAP || {};
const VERSION = BOOT.version || '0.18.1';

const REACT_URL = BOOT.reactUrl || 'https://esm.sh/react@18.3.1';
const REACT_DOM_URL = BOOT.reactDomUrl || 'https://esm.sh/react-dom@18.3.1';
const EXCALIDRAW_MODULE_URL = BOOT.moduleUrl
    || `https://esm.sh/@excalidraw/excalidraw@${VERSION}?external=react,react-dom`;
const COLLAB_URL = BOOT.collabUrl;
const EDITOR_URL = BOOT.editorUrl;

async function loadClassicScript(src) {
    await new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = src;
        script.onload = resolve;
        script.onerror = () => reject(new Error(`Failed to load ${src}`));
        document.head.appendChild(script);
    });
}

async function importModule(url) {
    return import(/* webpackIgnore: true */ url);
}

async function start() {
    const [React, ReactDOM] = await Promise.all([
        importModule(REACT_URL),
        importModule(REACT_DOM_URL),
    ]);

    let ExcalidrawLib;
    try {
        ExcalidrawLib = await importModule(EXCALIDRAW_MODULE_URL);
    } catch (err) {
        const fallback = BOOT.moduleFallback
            || `https://esm.sh/@excalidraw/excalidraw@${VERSION}`;
        console.warn('Excalidraw module failed, using fallback', err);
        if (BOOT.assetFallback) {
            window.EXCALIDRAW_ASSET_PATH = BOOT.assetFallback;
        }
        ExcalidrawLib = await importModule(fallback);
    }

    window.React = React.default || React;
    window.ReactDOM = ReactDOM.default || ReactDOM;
    window.ExcalidrawLib = ExcalidrawLib;

    if (COLLAB_URL) {
        await loadClassicScript(COLLAB_URL);
    }
    if (EDITOR_URL) {
        await loadClassicScript(EDITOR_URL);
    }
    if (typeof window.excalidrawEditorBoot === 'function') {
        window.excalidrawEditorBoot();
    }
}

start().catch((err) => {
    console.error('Excalidraw bootstrap failed:', err);
    const root = document.getElementById('excalidraw-root');
    if (root) {
        root.innerHTML = '<div class="alert alert-danger m-3 p-4">Excalidraw Editor konnte nicht geladen werden. Bitte prüfen Sie die Konsolen-Logs oder laden Sie die Seite neu.</div>';
    }
});
