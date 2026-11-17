/**
 * ESM bootstrap for Excalidraw 0.18.1.
 * Loads React + Excalidraw via modern ESM (esm.sh with jsDelivr fallback).
 */
const BOOT = window.EXCALIDRAW_BOOTSTRAP || {};
const VERSION = BOOT.version || '0.18.1';

const REACT_URLS = [
    BOOT.reactUrl,
    BOOT.reactFallbackUrl,
    'https://esm.sh/react@18.3.1',
    'https://cdn.jsdelivr.net/npm/react@18.3.1/+esm',
].filter(Boolean);

const REACT_DOM_URLS = [
    BOOT.reactDomUrl,
    BOOT.reactDomFallbackUrl,
    'https://esm.sh/react-dom@18.3.1',
    'https://cdn.jsdelivr.net/npm/react-dom@18.3.1/+esm',
].filter(Boolean);

const EXCALIDRAW_URLS = [
    BOOT.moduleUrl,
    BOOT.moduleFallback,
    `https://esm.sh/@excalidraw/excalidraw@${VERSION}?external=react,react-dom`,
    `https://esm.sh/@excalidraw/excalidraw@${VERSION}`,
].filter(Boolean);

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

async function importWithFallback(urls, name) {
    let lastError = null;
    for (const url of urls) {
        if (!url) continue;
        try {
            const mod = await import(/* webpackIgnore: true */ url);
            if (mod) return mod;
        } catch (err) {
            lastError = err;
            console.warn(`[Excalidraw] Failed to load ${name} from ${url}:`, err);
        }
    }
    throw lastError || new Error(`Failed to load ${name} from all candidate URLs`);
}

async function start() {
    const [ReactModule, ReactDOMModule] = await Promise.all([
        importWithFallback(REACT_URLS, 'React'),
        importWithFallback(REACT_DOM_URLS, 'ReactDOM'),
    ]);

    let ExcalidrawLib = null;
    try {
        ExcalidrawLib = await importWithFallback(EXCALIDRAW_URLS, 'Excalidraw module');
    } catch (err) {
        if (BOOT.assetFallback) {
            window.EXCALIDRAW_ASSET_PATH = BOOT.assetFallback;
        }
        throw err;
    }

    window.React = ReactModule.default || ReactModule;
    window.ReactDOM = ReactDOMModule.default || ReactDOMModule;
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
