/* Excalidraw room client — uses official excalidraw-room socket events. */
(function (global) {
    const WS_JOIN = 'join-room';
    const WS_SERVER = 'server-broadcast';
    const WS_VOLATILE = 'server-volatile-broadcast';
    const WS_CLIENT = 'client-broadcast';

    function hexToBytes(hex) {
        const clean = (hex || '').replace(/[^0-9a-f]/gi, '');
        const out = new Uint8Array(clean.length / 2);
        for (let i = 0; i < out.length; i += 1) {
            out[i] = parseInt(clean.substr(i * 2, 2), 16);
        }
        return out;
    }

    async function importKey(roomKey) {
        const raw = hexToBytes(roomKey);
        const keyBytes = raw.length >= 16 ? raw.slice(0, 32) : new TextEncoder().encode(roomKey).slice(0, 16);
        const padded = new Uint8Array(16);
        padded.set(keyBytes.slice(0, 16));
        return crypto.subtle.importKey('raw', padded, { name: 'AES-GCM' }, false, ['encrypt', 'decrypt']);
    }

    async function encryptJson(key, obj) {
        const iv = crypto.getRandomValues(new Uint8Array(12));
        const encoded = new TextEncoder().encode(JSON.stringify(obj));
        const cipher = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoded);
        return { cipher: new Uint8Array(cipher), iv };
    }

    async function decryptJson(key, cipher, iv) {
        const ivView = iv instanceof Uint8Array ? iv : new Uint8Array(iv);
        const data = cipher instanceof Uint8Array ? cipher : new Uint8Array(cipher);
        const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: ivView }, key, data);
        return JSON.parse(new TextDecoder().decode(plain));
    }

    function toArrayBuffer(u8) {
        return u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.byteLength);
    }

    class ExcalidrawRoomClient {
        constructor() {
            this.socket = null;
            this.key = null;
            this.options = null;
            this.started = false;
            this.gotInit = false;
        }

        async start(options) {
            this.stop();
            this.options = options || {};
            const { roomUrl, roomId, roomKey, onStatus } = this.options;
            if (!global.io || !roomId || !roomKey) {
                if (onStatus) onStatus('off');
                return false;
            }
            try {
                this.key = await importKey(roomKey);
            } catch (err) {
                console.warn('Excalidraw collab key import failed', err);
                if (onStatus) onStatus('off');
                return false;
            }

            const origin = window.location.origin;
            const path = (roomUrl || '/excalidraw-room').replace(/\/$/, '') + '/socket.io';
            this.socket = global.io(origin, {
                path: path,
                transports: ['websocket', 'polling'],
                reconnection: true,
                timeout: 8000,
            });

            return new Promise((resolve) => {
                let settled = false;
                const failTimer = window.setTimeout(() => {
                    if (settled) return;
                    settled = true;
                    if (onStatus) onStatus('off');
                    resolve(false);
                }, 6000);

                this.socket.on('connect', () => {
                    this.socket.emit(WS_JOIN, roomId);
                    this.started = true;
                    if (!settled) {
                        settled = true;
                        window.clearTimeout(failTimer);
                        if (onStatus) onStatus('on');
                        resolve(true);
                    }
                    window.setTimeout(() => {
                        if (!this.gotInit && this.options.getScene) {
                            const scene = this.options.getScene();
                            this.broadcast('INIT', scene);
                        }
                    }, 400);
                });

                this.socket.on('connect_error', () => {
                    if (!settled) {
                        settled = true;
                        window.clearTimeout(failTimer);
                        if (onStatus) onStatus('off');
                        resolve(false);
                    }
                });

                this.socket.on(WS_CLIENT, async (encryptedData, iv) => {
                    try {
                        const message = await decryptJson(this.key, encryptedData, iv);
                        this._handleMessage(message);
                    } catch (err) {
                        console.warn('Excalidraw collab decrypt failed', err);
                    }
                });
            });
        }

        _handleMessage(message) {
            if (!message || !message.type) return;
            if (message.type === 'INIT' || message.type === 'SCENE') {
                this.gotInit = true;
                if (this.options.applyScene && message.payload) {
                    this.options.applyScene(message.payload);
                }
            }
        }

        async broadcast(type, payload, volatile) {
            if (!this.started || !this.socket || !this.key || !this.options.roomId) return;
            try {
                const { cipher, iv } = await encryptJson(this.key, { type, payload });
                const event = volatile ? WS_VOLATILE : WS_SERVER;
                this.socket.emit(event, this.options.roomId, toArrayBuffer(cipher), toArrayBuffer(iv));
            } catch (err) {
                console.warn('Excalidraw collab broadcast failed', err);
            }
        }

        broadcastScene(elements, files) {
            this.broadcast('SCENE', { elements: elements || [], files: files || {} });
        }

        stop() {
            this.started = false;
            this.gotInit = false;
            if (this.socket) {
                try { this.socket.disconnect(); } catch (err) { /* ignore */ }
            }
            this.socket = null;
            this.key = null;
        }
    }

    global.PrismateamsExcalidrawCollab = new ExcalidrawRoomClient();
})(window);
