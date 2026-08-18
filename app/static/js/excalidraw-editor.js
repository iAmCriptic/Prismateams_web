const React = window.React;
const ReactDOM = window.ReactDOM;
const ExcalidrawLib = window.ExcalidrawLib || {};
const Excalidraw = ExcalidrawLib.Excalidraw || ExcalidrawLib.default;
const exportToBlob = ExcalidrawLib.exportToBlob;
const getSceneVersion = ExcalidrawLib.getSceneVersion;

const CONFIG = window.EXCALIDRAW_EDITOR_CONFIG || {};

let api = null;
let saveTimer = null;
let lastSavedVersion = -1;
let lastElements = [];
let lastAppState = {};
let lastFiles = {};
let saving = false;
let dirty = false;
let leaving = false;
let applyingRemote = false;
const SAVE_DELAY_MS = 3000;

const statusEl = () => document.getElementById('excalidrawSaveStatus');
const bannerEl = () => document.getElementById('excalidrawCollabBanner');

function setStatus(text) {
    const el = statusEl();
    if (el) el.textContent = text || '';
}

function setBanner(on) {
    const el = bannerEl();
    if (!el) return;
    el.classList.toggle('is-on', !!on);
    el.textContent = on ? (CONFIG.i18n.collabOn || '') : (CONFIG.i18n.collabOff || '');
    el.hidden = false;
}

function currentScene() {
    return {
        type: 'excalidraw',
        version: 2,
        source: 'prismateams',
        elements: lastElements || [],
        appState: {
            viewBackgroundColor: (lastAppState && lastAppState.viewBackgroundColor) || '#ffffff',
            gridSize: lastAppState ? lastAppState.gridSize : null,
        },
        files: lastFiles || {},
    };
}

async function thumbnailDataUrl() {
    if (!api || typeof exportToBlob !== 'function') return null;
    try {
        const blob = await exportToBlob({
            elements: lastElements || [],
            appState: { ...(lastAppState || {}), exportBackground: true, exportWithDarkMode: false },
            files: lastFiles || {},
            mimeType: 'image/png',
            quality: 0.6,
            exportPadding: 8,
            maxWidthOrHeight: 640,
        });
        return await new Promise((resolve) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => resolve(null);
            reader.readAsDataURL(blob);
        });
    } catch (err) {
        return null;
    }
}

async function saveScene(force) {
    if (!CONFIG.canEdit || !CONFIG.sceneUrl) return true;
    const version = typeof getSceneVersion === 'function' ? getSceneVersion(lastElements || []) : Date.now();
    if (!force && version === lastSavedVersion && !dirty) return true;
    if (saving) return false;
    saving = true;
    setStatus(CONFIG.i18n.saving || '');
    try {
        const thumbnail = await thumbnailDataUrl();
        const response = await fetch(CONFIG.sceneUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                scene: currentScene(),
                thumbnail,
                name: CONFIG.name,
            }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
            setStatus(CONFIG.i18n.saveFailed || '');
            saving = false;
            return false;
        }
        lastSavedVersion = version;
        dirty = false;
        setStatus(CONFIG.i18n.saved || '');
        window.setTimeout(() => {
            if (!dirty) setStatus('');
        }, 1800);
        saving = false;
        return true;
    } catch (err) {
        setStatus(CONFIG.i18n.saveFailed || '');
        saving = false;
        return false;
    }
}

function scheduleSave() {
    if (!CONFIG.canEdit) return;
    dirty = true;
    if (saveTimer) window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => {
        saveScene(false);
    }, SAVE_DELAY_MS);
}

function applyRemoteScene(payload) {
    if (!api || !payload) return;
    applyingRemote = true;
    try {
        const elements = payload.elements || [];
        lastElements = elements;
        if (payload.files) lastFiles = payload.files;
        api.updateScene({
            elements,
            appState: lastAppState,
            collaborators: api.getAppState ? api.getAppState().collaborators : undefined,
        });
        if (payload.files && api.addFiles) {
            api.addFiles(payload.files);
        }
    } finally {
        window.setTimeout(() => { applyingRemote = false; }, 50);
    }
}

function onChange(elements, appState, files) {
    lastElements = elements;
    lastAppState = appState;
    lastFiles = files;
    if (applyingRemote) return;
    scheduleSave();
    const collab = window.PrismateamsExcalidrawCollab;
    if (collab && collab.started) {
        if (onChange._t) window.clearTimeout(onChange._t);
        onChange._t = window.setTimeout(() => {
            collab.broadcastScene(elements, files);
        }, 250);
    }
}

async function goBack() {
    if (leaving) return;
    leaving = true;
    if (CONFIG.canEdit) {
        await saveScene(true);
    }
    const collab = window.PrismateamsExcalidrawCollab;
    if (collab) collab.stop();
    window.location.href = CONFIG.returnUrl || '/excalidraw/';
}

async function boot() {
    const rootEl = document.getElementById('excalidraw-root');
    if (!rootEl) return;

    if (!React || !ReactDOM || !Excalidraw) {
        console.error('Excalidraw dependencies missing:', { React: !!React, ReactDOM: !!ReactDOM, Excalidraw: !!Excalidraw });
        rootEl.innerHTML = '<div class="alert alert-danger m-3 p-4">Excalidraw Editor konnte nicht geladen werden. Bitte prüfen Sie die Konsolen-Logs oder laden Sie die Seite neu.</div>';
        return;
    }

    let initialData = {
        type: 'excalidraw',
        version: 2,
        elements: [],
        appState: { viewBackgroundColor: '#ffffff' },
        files: {},
    };
    try {
        const response = await fetch(CONFIG.sceneUrl, { headers: { Accept: 'application/json' } });
        const data = await response.json();
        if (data && data.scene) initialData = data.scene;
    } catch (err) {
        console.warn('Failed to load Excalidraw scene', err);
    }

    lastElements = initialData.elements || [];
    lastAppState = initialData.appState || {};
    lastFiles = initialData.files || {};
    lastSavedVersion = typeof getSceneVersion === 'function' ? getSceneVersion(lastElements) : 0;

    const theme = CONFIG.themeDark ? 'dark' : 'light';
    const createRoot = ReactDOM.createRoot ? ((el) => ReactDOM.createRoot(el)) : ((el) => ({ render: (c) => ReactDOM.render(c, el) }));
    const root = createRoot(rootEl);
    root.render(React.createElement(Excalidraw, {
        initialData,
        onChange,
        theme,
        name: CONFIG.name,
        viewModeEnabled: !CONFIG.canEdit,
        UIOptions: {
            canvasActions: {
                loadScene: false,
                saveToActiveFile: false,
                toggleTheme: true,
            },
        },
        excalidrawAPI: (nextApi) => { api = nextApi; },
    }));

    const closeBtn = document.getElementById('excalidrawCloseBtn');
    if (closeBtn) closeBtn.addEventListener('click', goBack);

    document.addEventListener('keydown', (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
            event.preventDefault();
            saveScene(true);
        }
        if (event.key === 'Escape') {
            goBack();
        }
    });

    window.addEventListener('beforeunload', (event) => {
        if (dirty && CONFIG.canEdit && !leaving) {
            event.preventDefault();
            event.returnValue = '';
            saveScene(true);
        }
    });

    const collab = window.PrismateamsExcalidrawCollab;
    if (CONFIG.collabEnabled && collab) {
        const ok = await collab.start({
            roomUrl: CONFIG.roomUrl,
            roomId: CONFIG.roomId,
            roomKey: CONFIG.roomKey,
            getScene: () => ({ elements: lastElements, files: lastFiles }),
            applyScene: applyRemoteScene,
            onStatus: (status) => setBanner(status === 'on'),
        });
        if (!ok) setBanner(false);
    } else {
        setBanner(false);
    }
}

boot();
