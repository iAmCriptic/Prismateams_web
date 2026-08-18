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

    function fallbackTransform(u8, keyBytes, iv) {
        const out = new Uint8Array(u8.length);
        for (let i = 0; i < u8.length; i += 1) {
            const k = keyBytes[i % keyBytes.length] ^ iv[i % iv.length];
            out[i] = u8[i] ^ k;
        }
        return out;
    }

    async function importKey(roomKey) {
        const raw = hexToBytes(roomKey);
        const keyBytes = raw.length >= 16 ? raw.slice(0, 32) : new TextEncoder().encode(roomKey || 'default').slice(0, 16);
        if (global.crypto && global.crypto.subtle) {
            try {
                const padded = new Uint8Array(16);
                padded.set(keyBytes.slice(0, 16));
                return await global.crypto.subtle.importKey('raw', padded, { name: 'AES-GCM' }, false, ['encrypt', 'decrypt']);
            } catch (err) {
                console.warn('SubtleCrypto importKey failed, using fallback:', err);
            }
        }
        return { fallback: true, keyBytes };
    }

    async function encryptJson(key, obj) {
        const encoded = new TextEncoder().encode(JSON.stringify(obj));
        const getRandomValues = (global.crypto && typeof global.crypto.getRandomValues === 'function')
            ? (arr) => global.crypto.getRandomValues(arr)
            : (arr) => { for (let i = 0; i < arr.length; i += 1) arr[i] = Math.floor(Math.random() * 256); return arr; };
        const iv = getRandomValues(new Uint8Array(12));

        if (key && key.fallback) {
            const cipher = fallbackTransform(encoded, key.keyBytes, iv);
            return { cipher, iv };
        }

        const cipher = await global.crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoded);
        return { cipher: new Uint8Array(cipher), iv };
    }

    async function decryptJson(key, cipher, iv) {
        const ivView = iv instanceof Uint8Array ? iv : new Uint8Array(iv);
        const data = cipher instanceof Uint8Array ? cipher : new Uint8Array(cipher);

        if (key && key.fallback) {
            const plainBytes = fallbackTransform(data, key.keyBytes, ivView);
            return JSON.parse(new TextDecoder().decode(plainBytes));
        }

        const plain = await global.crypto.subtle.decrypt({ name: 'AES-GCM', iv: ivView }, key, data);
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
            this.collaboratorsMap = new Map();
            this.presenceTimer = null;
            this.user = { id: null, name: 'User', color: '#0d6efd' };
            this.onCollaboratorsChange = null;
        }

        async start(options) {
            this.stop();
            this.options = options || {};
            const { roomUrl, roomId, roomKey, onStatus, username, userColor, userId, onCollaboratorsChange } = this.options;
            if (!global.io || !roomId || !roomKey) {
                if (onStatus) onStatus('off');
                return false;
            }
            this.user = { id: userId, name: username || 'User', color: userColor || '#0d6efd' };
            this.onCollaboratorsChange = onCollaboratorsChange;

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
                    this.broadcastPresence();
                    if (this.presenceTimer) clearInterval(this.presenceTimer);
                    this.presenceTimer = setInterval(() => this.broadcastPresence(), 4000);
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
            const payload = message.payload || {};
            const socketId = payload.socketId || message.senderId;

            if (message.type === 'INIT' || message.type === 'SCENE') {
                this.gotInit = true;
                if (this.options.applyScene && payload) {
                    this.options.applyScene(payload);
                }
            } else if (message.type === 'PRESENCE') {
                if (socketId && payload.username && socketId !== this.socket?.id) {
                    const colorHex = payload.userColor || '#0d6efd';
                    const existing = this.collaboratorsMap.get(socketId) || {};
                    this.collaboratorsMap.set(socketId, {
                        ...existing,
                        username: payload.username,
                        color: { background: colorHex + '22', stroke: colorHex },
                        userColor: colorHex,
                        lastSeen: Date.now(),
                    });
                    this._notifyCollaborators();
                }
            } else if (message.type === 'POINTER') {
                if (socketId && socketId !== this.socket?.id) {
                    const colorHex = payload.userColor || '#0d6efd';
                    const existing = this.collaboratorsMap.get(socketId) || {};
                    this.collaboratorsMap.set(socketId, {
                        ...existing,
                        username: payload.username || existing.username || 'User',
                        color: { background: colorHex + '22', stroke: colorHex },
                        userColor: colorHex,
                        pointer: payload.pointer || existing.pointer,
                        button: payload.button || 'up',
                        selectedElementIds: payload.selectedElementIds || existing.selectedElementIds,
                        lastSeen: Date.now(),
                    });
                    this._notifyCollaborators();
                }
            } else if (message.type === 'LEAVE') {
                if (socketId) {
                    this.collaboratorsMap.delete(socketId);
                    this._notifyCollaborators();
                }
            }
        }

        _notifyCollaborators() {
            const now = Date.now();
            for (const [id, collab] of this.collaboratorsMap.entries()) {
                if (now - (collab.lastSeen || 0) > 12000) {
                    this.collaboratorsMap.delete(id);
                }
            }
            if (typeof this.onCollaboratorsChange === 'function') {
                this.onCollaboratorsChange(this.collaboratorsMap);
            }
        }

        broadcastPresence() {
            if (!this.started || !this.socket) return;
            this.broadcast('PRESENCE', {
                userColor: this.user.color,
                username: this.user.name,
                socketId: this.socket.id,
            }, true);
        }

        broadcastPointer(pointer, button, selectedElementIds) {
            if (!this.started || !this.socket) return;
            this.broadcast('POINTER', {
                pointer,
                button,
                selectedElementIds,
                username: this.user.name,
                userColor: this.user.color,
                socketId: this.socket.id,
            }, true);
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
            if (this.presenceTimer) {
                clearInterval(this.presenceTimer);
                this.presenceTimer = null;
            }
            if (this.started && this.socket) {
                this.broadcast('LEAVE', { socketId: this.socket.id }, true);
            }
            this.started = false;
            this.gotInit = false;
            this.collaboratorsMap.clear();
            if (this.socket) {
                try { this.socket.disconnect(); } catch (err) { /* ignore */ }
            }
            this.socket = null;
            this.key = null;
        }
    }

    global.PrismateamsExcalidrawCollab = new ExcalidrawRoomClient();
})(window);
