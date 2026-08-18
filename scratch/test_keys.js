const fs = require('fs');
global.React = { createElement: () => {}, createContext: () => ({ Provider: {} }), useState: () => [], useEffect: () => {}, useRef: () => ({}) };
global.ReactDOM = { createRoot: () => {} };
try {
    const lib = require('../app/static/vendor/excalidraw/excalidraw.production.min.js');
    console.log('--- ExcalidrawLib keys ---');
    console.log(Object.keys(lib));
    if (lib.Excalidraw) {
        console.log('--- Excalidraw keys ---');
        console.log(Object.keys(lib.Excalidraw));
    }
} catch (err) {
    console.error('Error:', err);
}
