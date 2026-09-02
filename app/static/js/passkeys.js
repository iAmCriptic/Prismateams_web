(function (global) {
    'use strict';

    function supportsWebAuthn() {
        return !!(global.PublicKeyCredential && global.navigator && global.navigator.credentials);
    }

    function base64urlToBuffer(base64url) {
        var padding = '='.repeat((4 - (base64url.length % 4)) % 4);
        var base64 = (base64url + padding).replace(/-/g, '+').replace(/_/g, '/');
        var raw = global.atob(base64);
        var buffer = new ArrayBuffer(raw.length);
        var view = new Uint8Array(buffer);
        for (var i = 0; i < raw.length; i++) {
            view[i] = raw.charCodeAt(i);
        }
        return buffer;
    }

    function bufferToBase64url(buffer) {
        var bytes = new Uint8Array(buffer);
        var binary = '';
        for (var i = 0; i < bytes.length; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return global.btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
    }

    function normalizeOptions(options) {
        if (!options) {
            return null;
        }
        if (typeof options === 'string') {
            return JSON.parse(options);
        }
        return options;
    }

    function decodeCreationOptions(options) {
        var publicKey = Object.assign({}, normalizeOptions(options));
        if (!publicKey || !publicKey.challenge) {
            throw new Error('Invalid WebAuthn options');
        }
        publicKey.challenge = base64urlToBuffer(publicKey.challenge);
        publicKey.user = Object.assign({}, publicKey.user || {});
        if (!publicKey.user.id) {
            throw new Error('Invalid WebAuthn user handle');
        }
        publicKey.user.id = base64urlToBuffer(publicKey.user.id);
        if (publicKey.excludeCredentials) {
            publicKey.excludeCredentials = publicKey.excludeCredentials.map(function (cred) {
                return Object.assign({}, cred, { id: base64urlToBuffer(cred.id) });
            });
        }
        return publicKey;
    }

    function decodeRequestOptions(options) {
        var publicKey = Object.assign({}, normalizeOptions(options));
        if (!publicKey || !publicKey.challenge) {
            throw new Error('Invalid WebAuthn options');
        }
        publicKey.challenge = base64urlToBuffer(publicKey.challenge);
        if (publicKey.allowCredentials && publicKey.allowCredentials.length) {
            publicKey.allowCredentials = publicKey.allowCredentials.map(function (cred) {
                return Object.assign({}, cred, { id: base64urlToBuffer(cred.id) });
            });
        }
        return publicKey;
    }

    function credentialToJSON(credential) {
        var response = credential.response;
        var clientExtensionResults = {};
        try {
            if (typeof credential.getClientExtensionResults === 'function') {
                clientExtensionResults = credential.getClientExtensionResults();
            }
        } catch (e) { /* ignore */ }

        var result = {
            id: credential.id,
            rawId: bufferToBase64url(credential.rawId),
            type: credential.type,
            clientExtensionResults: clientExtensionResults,
            response: {
                clientDataJSON: bufferToBase64url(response.clientDataJSON),
            },
        };

        if (response.attestationObject) {
            result.response.attestationObject = bufferToBase64url(response.attestationObject);
            if (typeof response.getTransports === 'function') {
                result.response.transports = response.getTransports();
            }
        }
        if (response.authenticatorData) {
            result.response.authenticatorData = bufferToBase64url(response.authenticatorData);
            result.response.signature = bufferToBase64url(response.signature);
            if (response.userHandle) {
                result.response.userHandle = bufferToBase64url(response.userHandle);
            }
        }
        return result;
    }

    function postJson(url, body) {
        return fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            credentials: 'same-origin',
            body: JSON.stringify(body || {}),
        }).then(function (res) {
            return res.json().then(function (data) {
                return { ok: res.ok, status: res.status, data: data };
            });
        });
    }

    function registerPasskey(button) {
        if (!button || !supportsWebAuthn()) {
            return Promise.reject(new Error('WebAuthn not supported'));
        }

        var optionsUrl = button.getAttribute('data-options-url');
        var verifyUrl = button.getAttribute('data-verify-url');
        if (!optionsUrl || !verifyUrl) {
            return Promise.reject(new Error('Missing passkey URLs'));
        }

        button.disabled = true;

        return postJson(optionsUrl, {})
            .then(function (res) {
                if (!res.ok || !res.data.success) {
                    throw new Error((res.data && res.data.error) || 'Options failed');
                }
                var publicKey = decodeCreationOptions(res.data.options);
                return navigator.credentials.create({ publicKey: publicKey });
            })
            .then(function (credential) {
                if (!credential) {
                    throw new Error('No credential');
                }
                var promptMessage = button.getAttribute('data-label-prompt') || 'Gerätename (optional):';
                var promptOpts = {
                    title: button.getAttribute('data-label-title') || promptMessage,
                    placeholder: button.getAttribute('data-label-placeholder') || '',
                    confirmLabel: button.getAttribute('data-label-ok') || undefined,
                };
                var askLabel = typeof global.ptPrompt === 'function'
                    ? global.ptPrompt(promptMessage, promptOpts)
                    : Promise.resolve(global.prompt(promptMessage, ''));
                return askLabel.then(function (label) {
                    // Abbrechen → null: Registrierung ohne Gerätename fortsetzen (optional)
                    return postJson(verifyUrl, {
                        credential: credentialToJSON(credential),
                        device_label: label || null,
                    });
                });
            })
            .then(function (res) {
                if (!res.ok || !res.data.success) {
                    throw new Error((res.data && res.data.error) || 'Registration failed');
                }
                global.location.reload();
            })
            .finally(function () {
                button.disabled = false;
            });
    }

    function authenticate(optionsUrl, verifyUrl, mediation) {
        if (!supportsWebAuthn()) {
            return Promise.reject(new Error('WebAuthn not supported'));
        }

        var fetchOptions = { mediation: mediation || 'optional' };

        return postJson(optionsUrl, {})
            .then(function (res) {
                if (!res.ok || !res.data.success) {
                    throw new Error((res.data && res.data.error) || 'Options failed');
                }
                var publicKey = decodeRequestOptions(res.data.options);
                fetchOptions.publicKey = publicKey;
                return navigator.credentials.get(fetchOptions);
            })
            .then(function (credential) {
                if (!credential) {
                    return null;
                }
                return postJson(verifyUrl, { credential: credentialToJSON(credential) });
            })
            .then(function (res) {
                if (!res) {
                    return;
                }
                if (!res.ok || !res.data.success) {
                    throw new Error((res.data && res.data.error) || 'Authentication failed');
                }
                if (res.data.redirect) {
                    global.location.href = res.data.redirect;
                } else {
                    global.location.reload();
                }
            });
    }

    function initRegisterButton(selector) {
        var button = typeof selector === 'string' ? document.querySelector(selector) : selector;
        if (!button) {
            return;
        }
        button.addEventListener('click', function () {
            registerPasskey(button).catch(function (err) {
                if (err && err.name === 'NotAllowedError') {
                    return;
                }
                var msg = err.message || 'Passkey registration failed';
                if (typeof global.showAppBanner === 'function') {
                    global.showAppBanner(msg, 'danger');
                } else {
                    global.alert(msg);
                }
            });
        });
    }

    function initLogin(config) {
        if (!config || !supportsWebAuthn()) {
            return;
        }

        var optionsUrl = config.optionsUrl;
        var verifyUrl = config.verifyUrl;
        var button = config.buttonSelector ? document.querySelector(config.buttonSelector) : null;

        if (button) {
            button.addEventListener('click', function () {
                button.disabled = true;
                authenticate(optionsUrl, verifyUrl, 'optional')
                    .catch(function (err) {
                        if (err && err.name !== 'NotAllowedError') {
                            global.alert(err.message || 'Passkey login failed');
                        }
                    })
                    .finally(function () {
                        button.disabled = false;
                    });
            });
        }

        if (config.conditional && global.PublicKeyCredential && PublicKeyCredential.isConditionalMediationAvailable) {
            PublicKeyCredential.isConditionalMediationAvailable().then(function (available) {
                if (!available) {
                    return;
                }
                authenticate(optionsUrl, verifyUrl, 'conditional').catch(function () {
                    /* silent — user may not have a passkey */
                });
            });
        }
    }

    function init2fa(config) {
        if (!config || !supportsWebAuthn()) {
            return;
        }

        var button = config.buttonSelector ? document.querySelector(config.buttonSelector) : null;
        if (!button) {
            return;
        }

        button.addEventListener('click', function () {
            button.disabled = true;
            authenticate(config.optionsUrl, config.verifyUrl, 'optional')
                .catch(function (err) {
                    if (err && err.name !== 'NotAllowedError') {
                        global.alert(err.message || 'Passkey verification failed');
                    }
                })
                .finally(function () {
                    button.disabled = false;
                });
        });
    }

    global.PrismateamsPasskeys = {
        supportsWebAuthn: supportsWebAuthn,
        initRegisterButton: initRegisterButton,
        initLogin: initLogin,
        init2fa: init2fa,
    };
})(window);
