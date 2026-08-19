/**
 * ESM bootstrap for Excalidraw 0.18.1 using bundled module URLs with fallback.
 */
const BOOT = window.EXCALIDRAW_BOOTSTRAP || {};
const VERSION = BOOT.version || '0.18.1';

const REACT_URLS = BOOT.reactUrls || [
    'https://esm.sh/react@18.3.1',
];
const REACT_DOM_URLS = BOOT.reactDomUrls || [
    'https://esm.sh/react-dom@18.3.1',
];
const EXCALIDRAW_MODULE_URLS = BOOT.excalidrawModuleUrls || [
    `https://esm.sh/@excalidraw/excalidraw@${VERSION}?external=react,react-dom&bundle`,
    `https://esm.sh/@excalidraw/excalidraw@${VERSION}?external=react,react-dom`,
];
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

async function importFromFallbacks(urls, name) {
    let lastError = null;
    for (const url of urls) {
        if (!url) continue;
        try {
            return await importModule(url);
        } catch (err) {
            lastError = err;
        }
    }
    throw new Error(`${name} failed to load (${lastError ? lastError.message : 'no URL'})`);
}

async function start() {
    const [React, ReactDOM] = await Promise.all([
        importFromFallbacks(REACT_URLS, 'React'),
        importFromFallbacks(REACT_DOM_URLS, 'ReactDOM'),
    ]);
    const ExcalidrawLib = await importFromFallbacks(EXCALIDRAW_MODULE_URLS, 'Excalidraw module');

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
