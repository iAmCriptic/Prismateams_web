/**
 * ESM bootstrap for Excalidraw 0.18.1 — loads React + Excalidraw module,
 * sets window globals expected by excalidraw-editor.js, then starts the editor.
 */
const BOOT = window.EXCALIDRAW_BOOTSTRAP || {};

const REACT_URL = BOOT.reactUrl || 'https://esm.sh/react@18.3.1';
const REACT_DOM_URL = BOOT.reactDomUrl || 'https://esm.sh/react-dom@18.3.1';
const EXCALIDRAW_MODULE_URL = BOOT.moduleUrl
    || BOOT.moduleFallback
    || 'https://unpkg.com/@excalidraw/excalidraw@0.18.1/dist/prod/index.js';
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

async function start() {
    let moduleUrl = EXCALIDRAW_MODULE_URL;
    const [React, ReactDOM] = await Promise.all([
        import(REACT_URL),
        import(REACT_DOM_URL),
    ]);

    let ExcalidrawLib;
    try {
        ExcalidrawLib = await import(moduleUrl);
    } catch (err) {
        if (BOOT.moduleFallback && moduleUrl !== BOOT.moduleFallback) {
            console.warn('Local Excalidraw module failed, using CDN fallback', err);
            if (BOOT.assetFallback) {
                window.EXCALIDRAW_ASSET_PATH = BOOT.assetFallback;
            }
            moduleUrl = BOOT.moduleFallback;
            ExcalidrawLib = await import(moduleUrl);
        } else {
            throw err;
        }
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
