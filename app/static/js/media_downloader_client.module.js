/**
 * Client-side YouTube download via youtubei.js (InnerTube API).
 * Uses mobile/TV clients to avoid WEB login/bot blocks in the browser.
 */

/** Pre-bundled browser build (esbuild). esm.sh chunks break with "Class extends value undefined". */
const YTJS_VERSION = '18.0.0';
const YTJS_LOCAL_URL = new URL('../vendor/youtubei.js/browser.js', import.meta.url).href;
const YTJS_CDN_URL = `https://unpkg.com/youtubei.js@${YTJS_VERSION}/bundle/browser.js`;

let youtubeJsModulePromise = null;

const PLAYLIST_LIST_PREFIXES = ['PL', 'OL', 'LL', 'FL', 'VL', 'PU', 'UU'];

/** Must match youtubei.js@18 client constants exactly (stream URLs are UA-bound). */
const CLIENT_USER_AGENTS = {
    IOS: 'com.google.ios.youtube/20.11.6 (iPhone10,4; U; CPU iOS 16_7_7 like Mac OS X)',
    ANDROID: 'com.google.android.youtube/21.03.36(Linux; U; Android 16; en_US; SM-S908E Build/TP1A.220624.014) gzip',
    ANDROID_VR: 'com.google.android.apps.youtube.vr.oculus/1.65.10 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip',
    TV_EMBEDDED: 'Mozilla/5.0 (ChromiumStylePlatform) Cobalt/Version',
    TV: 'Mozilla/5.0 (ChromiumStylePlatform) Cobalt/Version',
    WEB_EMBEDDED: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    MWEB: 'Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
};

/** Clients that often expose progressive/direct URLs without nsig decipher. */
const DEFAULT_DOWNLOAD_CLIENTS = ['TV_EMBEDDED', 'WEB_EMBEDDED', 'ANDROID', 'ANDROID_VR', 'MWEB', 'IOS'];

/** Windows desktop browsers: TV/embedded clients before Android adaptive. */
function getDownloadClients() {
    if (typeof navigator !== 'undefined' && /Windows/i.test(navigator.userAgent)) {
        return ['TV_EMBEDDED', 'WEB_EMBEDDED', 'ANDROID', 'ANDROID_VR', 'MWEB', 'IOS'];
    }
    return DEFAULT_DOWNLOAD_CLIENTS;
}

let platformReady = false;
let playlistClientPromise = null;
let proxyUrl = null;
let cachedProxyFetch = null;
let cachedSmartFetch = null;
let configuredYoutubeiUrl = null;
let authenticatedInnertube = null;
const authCallbacks = { onAuthPending: null, onAuthStateChange: null };
const YT_OAUTH_STORAGE_KEY = 'media_downloader_yt_oauth';
const AUTHENTICATED_CLIENT = 'TV';

export function configure(options = {}) {
    if (options.proxyUrl) {
        proxyUrl = options.proxyUrl;
        cachedProxyFetch = null;
        cachedSmartFetch = null;
    }
    if (options.youtubeiUrl) {
        configuredYoutubeiUrl = options.youtubeiUrl;
        youtubeJsModulePromise = null;
    }
    if (options.onAuthPending) authCallbacks.onAuthPending = options.onAuthPending;
    if (options.onAuthStateChange) authCallbacks.onAuthStateChange = options.onAuthStateChange;
}

function shouldProxyUrl(url) {
    try {
        const parsed = new URL(url);
        if (parsed.protocol !== 'https:') return false;
        const host = parsed.hostname.toLowerCase();
        if (host === 'youtu.be') return true;
        return host.includes('youtube')
            || host.endsWith('.googlevideo.com')
            || host.endsWith('.ggpht.com')
            || host.endsWith('.googleusercontent.com')
            || host.endsWith('.googleapis.com')
            || host.endsWith('.gstatic.com')
            || host.endsWith('.ytimg.com')
            || host === 'youtubei.googleapis.com';
    } catch (e) {
        return false;
    }
}

function resolveRequestUrl(input) {
    if (typeof input === 'string') return input;
    if (input instanceof URL) return input.href;
    if (input && typeof input.url === 'string') return input.url;
    return '';
}

function headersToObject(headers) {
    const out = {};
    if (!headers) return out;
    const h = headers instanceof Headers ? headers : new Headers(headers);
    h.forEach((value, key) => {
        const lower = key.toLowerCase();
        if (['host', 'connection', 'content-length', 'transfer-encoding'].includes(lower)) {
            return;
        }
        out[key] = value;
    });
    return out;
}

async function bodyToPayload(body, method) {
    if (!body || method === 'GET' || method === 'HEAD') return null;
    if (typeof body === 'string') return { body, encoding: 'utf8' };
    if (body instanceof ArrayBuffer) {
        const bytes = new Uint8Array(body);
        let binary = '';
        for (let i = 0; i < bytes.length; i += 1) {
            binary += String.fromCharCode(bytes[i]);
        }
        return { body: btoa(binary), encoding: 'base64' };
    }
    if (body instanceof Uint8Array) {
        let binary = '';
        for (let i = 0; i < body.length; i += 1) {
            binary += String.fromCharCode(body[i]);
        }
        return { body: btoa(binary), encoding: 'base64' };
    }
    const text = await new Response(body).text();
    return { body: text, encoding: 'utf8' };
}

function resolveFetchParams(input, init = {}) {
    const isRequest = typeof Request !== 'undefined' && input instanceof Request;
    const method = (
        init.method
        || (isRequest ? input.method : null)
        || 'GET'
    ).toUpperCase();

    let headers = init.headers;
    if (!headers && isRequest) {
        headers = input.headers;
    }

    let body = init.body;
    if (body === undefined && isRequest && method !== 'GET' && method !== 'HEAD') {
        body = input.body;
    }

    let signal = init.signal;
    if (!signal && isRequest) {
        signal = input.signal;
    }

    return { method, headers, body, signal };
}

function createYoutubeProxyFetch() {
    return async (input, init = {}) => {
        const targetUrl = resolveRequestUrl(input);

        if (!proxyUrl || !targetUrl || !shouldProxyUrl(targetUrl)) {
            return fetch(input, init);
        }

        const { method, headers, body, signal } = resolveFetchParams(input, init);
        const headerObj = headersToObject(headers);

        const payload = await bodyToPayload(body, method);

        return fetch(proxyUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                Accept: '*/*',
            },
            body: JSON.stringify({
                url: targetUrl,
                method,
                headers: headerObj,
                body: payload ? payload.body : null,
                encoding: payload ? payload.encoding : null,
            }),
            signal,
        });
    };
}

function getProxyFetch() {
    if (!proxyUrl) return null;
    if (!cachedProxyFetch) {
        cachedProxyFetch = createYoutubeProxyFetch();
    }
    return cachedProxyFetch;
}

/** Browser fetch first (user IP); server proxy only as CORS/network fallback. */
function getSmartFetch() {
    if (!cachedSmartFetch) {
        cachedSmartFetch = async (input, init = {}) => {
            const targetUrl = resolveRequestUrl(input);
            try {
                const response = await fetch(input, init);
                if (response.type !== 'opaque') {
                    return response;
                }
                throw new Error('cors_opaque');
            } catch (directErr) {
                const proxy = getProxyFetch();
                if (proxy && targetUrl && shouldProxyUrl(targetUrl)) {
                    return proxy(input, init);
                }
                throw directErr;
            }
        };
    }
    return cachedSmartFetch;
}

async function proxiedFetch(url, init = {}) {
    return getSmartFetch()(url, init);
}

function loadOAuthCredentials() {
    try {
        const raw = localStorage.getItem(YT_OAUTH_STORAGE_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch (e) {
        return null;
    }
}

function saveOAuthCredentials(credentials) {
    localStorage.setItem(YT_OAUTH_STORAGE_KEY, JSON.stringify(credentials));
}

function clearOAuthCredentials() {
    localStorage.removeItem(YT_OAUTH_STORAGE_KEY);
}

function resetAuthenticatedSession() {
    authenticatedInnertube = null;
    playlistClientPromise = null;
}

export function isYoutubeSignedIn() {
    return Boolean(loadOAuthCredentials()?.access_token);
}

export async function signInToYoutube() {
    await ensurePlatform();
    const { Innertube } = await importYoutubeJs();

    if (authenticatedInnertube?.session?.logged_in) {
        return loadOAuthCredentials();
    }

    const innertube = await Innertube.create({
        lang: 'de',
        location: 'DE',
        client_type: AUTHENTICATED_CLIENT,
        retrieve_player: false,
        enable_session_cache: false,
        generate_session_locally: true,
        fetch: getSmartFetch(),
        user_agent: CLIENT_USER_AGENTS.TV,
    });

    const cached = loadOAuthCredentials();

    return new Promise((resolve, reject) => {
        const cleanup = () => {
            innertube.session.off('auth-pending', onPending);
            innertube.session.off('auth', onAuth);
            innertube.session.off('auth-error', onError);
        };

        const onPending = (data) => {
            if (authCallbacks.onAuthPending) {
                authCallbacks.onAuthPending({
                    verificationUrl: data.verification_url,
                    userCode: data.user_code,
                });
            }
        };
        const onAuth = ({ credentials }) => {
            cleanup();
            saveOAuthCredentials(credentials);
            authenticatedInnertube = innertube;
            playlistClientPromise = null;
            if (authCallbacks.onAuthStateChange) authCallbacks.onAuthStateChange(true);
            resolve(credentials);
        };
        const onError = (err) => {
            cleanup();
            reject(err);
        };

        innertube.session.on('auth-pending', onPending);
        innertube.session.once('auth', onAuth);
        innertube.session.once('auth-error', onError);

        innertube.session.signIn(cached || undefined).catch((err) => {
            cleanup();
            reject(err);
        });
    });
}

export async function signOutFromYoutube() {
    if (authenticatedInnertube?.session?.logged_in) {
        try {
            await authenticatedInnertube.session.signOut();
        } catch (e) {
            // ignore revoke failures
        }
    }
    clearOAuthCredentials();
    resetAuthenticatedSession();
    if (authCallbacks.onAuthStateChange) authCallbacks.onAuthStateChange(false);
}

function isTruePlaylistListId(listId) {
    if (!listId) return false;
    const upper = String(listId).toUpperCase();
    return PLAYLIST_LIST_PREFIXES.some((prefix) => upper.startsWith(prefix));
}

export function resolveVideoId(url) {
    if (!url) return null;
    const cleaned = String(url).trim();
    try {
        const parsed = new URL(cleaned);
        const host = parsed.hostname.replace(/^www\./, '').toLowerCase();
        if (host === 'youtu.be') {
            const id = parsed.pathname.replace(/^\//, '').split('/')[0];
            return id || null;
        }
        if (host.includes('youtube.com')) {
            const v = parsed.searchParams.get('v');
            if (v) return v;
            const shorts = parsed.pathname.match(/^\/shorts\/([^/?#]+)/);
            if (shorts) return shorts[1];
        }
    } catch (e) {
        // fall through
    }
    const watchMatch = cleaned.match(/[?&]v=([a-zA-Z0-9_-]{6,})/);
    if (watchMatch) return watchMatch[1];
    const shortMatch = cleaned.match(/youtu\.be\/([a-zA-Z0-9_-]{6,})/);
    if (shortMatch) return shortMatch[1];
    return null;
}

export function resolvePlaylistId(url) {
    if (!url) return null;
    try {
        const parsed = new URL(String(url).trim());
        const listId = parsed.searchParams.get('list');
        if (listId && isTruePlaylistListId(listId)) return listId;
    } catch (e) {
        // ignore
    }
    const match = String(url).match(/[?&]list=([^&]+)/);
    if (match && isTruePlaylistListId(match[1])) return match[1];
    return null;
}

export function isPlaylistUrl(url) {
    return Boolean(resolvePlaylistId(url));
}

export function canonicalizePlaylistUrl(url) {
    const listId = resolvePlaylistId(url);
    if (!listId) return url;
    try {
        const parsed = new URL(String(url).trim());
        const host = parsed.hostname.replace(/^www\./, '').toLowerCase();
        if (host.startsWith('music.')) {
            return `https://music.youtube.com/playlist?list=${listId}`;
        }
    } catch (e) {
        // ignore
    }
    return `https://www.youtube.com/playlist?list=${listId}`;
}

async function importYoutubeJs() {
    if (!youtubeJsModulePromise) {
        youtubeJsModulePromise = (async () => {
            const candidates = [
                configuredYoutubeiUrl,
                YTJS_CDN_URL,
                YTJS_LOCAL_URL,
            ].filter(Boolean);

            let lastErr;
            for (const url of candidates) {
                try {
                    return await import(/* webpackIgnore: true */ url);
                } catch (err) {
                    lastErr = err;
                    console.warn('[MediaDownloader] youtubei.js load failed, trying next source:', url, err);
                }
            }
            throw lastErr || new Error('youtubei_load_failed');
        })();
    }
    return youtubeJsModulePromise;
}

async function ensurePlatform() {
    if (platformReady) return;
    const { Platform } = await importYoutubeJs();
    if (Platform?.shim) {
        // youtubei.js v18: data.output already includes getNsigProcessorFn() when decipher runs.
        Platform.shim.eval = async (data) => {
            const output = String(data?.output || '').trim();
            if (!output) {
                throw new Error('empty_player_eval');
            }
            return new Function(output)();
        };
    }
    platformReady = true;
}

async function createInnertube(clientType = 'WEB', { retrievePlayer = false } = {}) {
    await ensurePlatform();
    const { Innertube } = await importYoutubeJs();
    const options = {
        lang: 'de',
        location: 'DE',
        retrieve_player: retrievePlayer,
        retrieve_innertube_config: false,
        client_type: clientType,
        enable_safety_mode: false,
        generate_session_locally: true,
        fast_fail: false,
        enable_session_cache: false,
        fetch: getSmartFetch(),
    };
    if (CLIENT_USER_AGENTS[clientType]) {
        options.user_agent = CLIENT_USER_AGENTS[clientType];
    }
    return Innertube.create(options);
}

async function ensureAuthenticatedInnertube() {
    if (authenticatedInnertube?.session?.logged_in) {
        return authenticatedInnertube;
    }
    const creds = loadOAuthCredentials();
    if (!creds) {
        throw new ClientDownloadError('err_bot_check', 'youtube_not_signed_in');
    }
    await signInToYoutube();
    if (!authenticatedInnertube) {
        throw new ClientDownloadError('err_bot_check', 'youtube_auth_failed');
    }
    return authenticatedInnertube;
}

async function getPlaylistClient() {
    if (isYoutubeSignedIn()) {
        return ensureAuthenticatedInnertube();
    }
    if (!playlistClientPromise) {
        playlistClientPromise = createInnertube('WEB', { retrievePlayer: false });
    }
    return playlistClientPromise;
}

function durationSeconds(video) {
    if (!video) return null;
    if (typeof video.duration === 'number') return video.duration;
    if (video.duration?.seconds != null) return video.duration.seconds;
    if (video.length_seconds != null) return video.length_seconds;
    return null;
}

function titleText(video) {
    if (!video) return '';
    if (typeof video.title === 'string') return video.title;
    return video.title?.text || video.title?.toString?.() || '';
}

function playabilityError(info) {
    const status = info?.playability_status;
    if (!status) return null;
    const state = String(status.status || '').toUpperCase();
    if (state === 'OK' || state === 'LIVE_STREAM') return null;
    const reason = status.reason || status.error_screen?.text?.text || state;
    return reason || 'unplayable';
}

function isBotCheckText(text) {
    const lower = String(text || '').toLowerCase();
    if (!lower) return false;
    return (
        lower.includes('not a bot')
        || lower.includes('no bot')
        || lower.includes('kein bot')
        || lower.includes('bot bist')
        || lower.includes('nicht bot')
        || lower.includes('verify you\'re not')
        || lower.includes('confirm you\'re not')
        || lower.includes('unusual traffic')
        || lower.includes('ungewöhnlich')
        || (lower.includes('bot') && (lower.includes('sign in') || lower.includes('melde dich an')))
    );
}

function isBotCheckInfo(info) {
    const status = info?.playability_status;
    if (!status) return false;
    const reason = status.reason || status.error_screen?.text?.text || '';
    const state = String(status.status || '');
    return isBotCheckText(reason) || isBotCheckText(state);
}

function isAgeRestrictionText(text) {
    const lower = String(text || '').toLowerCase();
    if (!lower) return false;
    if (isBotCheckText(lower)) return false;
    return (
        lower.includes('age-restricted')
        || lower.includes('age restricted')
        || lower.includes('confirm your age')
        || lower.includes('age_verification')
        || lower.includes('content_check')
        || lower.includes('inappropriate for some users')
        || lower.includes('altersbeschränkt')
        || lower.includes('altersbeschraenkt')
        || lower.includes('alter zu bestätigen')
        || lower.includes('alter zu bestaetigen')
        || lower.includes('nutzer unangemessen')
        || lower.includes('melde dich an, um dein alter')
        || lower.includes('restricción de edad')
        || lower.includes('restriccion de edad')
        || lower.includes('restrição de idade')
        || lower.includes('restricao de idade')
        || lower.includes('возраст')
    );
}

function isAgeRestrictedInfo(info) {
    const status = info?.playability_status;
    if (!status) return false;
    if (isBotCheckInfo(info)) return false;

    const state = String(status.status || '').toUpperCase();
    const reason = status.reason || status.error_screen?.text?.text || '';

    if (state === 'CONTENT_CHECK_REQUIRED') {
        return true;
    }
    if (state === 'LOGIN_REQUIRED') {
        return isAgeRestrictionText(reason);
    }
    return isAgeRestrictionText(reason) || isAgeRestrictionText(state);
}

function throwPlayabilityFailure(info, playErr) {
    if (isBotCheckInfo(info) || isBotCheckText(playErr)) {
        throw new ClientDownloadError('err_bot_check', playErr);
    }
    if (isAgeRestrictedInfo(info)) {
        throw new ClientDownloadError('err_age_restricted', playErr);
    }
    throw new Error(playErr);
}

function hasStreamFormats(info) {
    const data = info?.streaming_data;
    if (!data) return false;
    const adaptive = data.adaptive_formats || data.adaptiveFormats || [];
    const progressive = data.formats || [];
    return (adaptive.length + progressive.length) > 0;
}

function guessExt(mimeType, fallback) {
    const mime = String(mimeType || '').toLowerCase();
    if (mime.includes('webm')) return 'webm';
    if (mime.includes('mp4')) return 'mp4';
    if (mime.includes('mpeg')) return 'mp3';
    if (mime.includes('m4a') || mime.includes('mp4a')) return 'm4a';
    return fallback || 'bin';
}

async function readableStreamToBlob(stream, onProgress, signal) {
    if (!stream || typeof stream.getReader !== 'function') {
        throw new Error('no_stream');
    }

    const reader = stream.getReader();
    const chunks = [];
    let received = 0;

    while (true) {
        if (signal?.aborted) {
            const err = new Error('cancelled');
            err.name = 'AbortError';
            throw err;
        }

        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        received += value.byteLength;
        if (typeof onProgress === 'function') {
            onProgress(received, received);
        }
    }

    return new Blob(chunks);
}

function stripRangeFromUrl(url) {
    // Do NOT use URL()/searchParams — re-encoding breaks YouTube signatures.
    if (!/[?&]range=/.test(url) && !/[?&]rn=/.test(url) && !/[?&]rbuf=/.test(url)) {
        return url;
    }
    return url
        .replace(/([?&])range=[^&]*/g, '$1')
        .replace(/([?&])rn=[^&]*/g, '$1')
        .replace(/([?&])rbuf=[^&]*/g, '$1')
        .replace(/[?&]{2,}/g, (m) => m[0])
        .replace(/[?&]$/, '');
}

function streamHeadersForClient(clientType) {
    const headers = { Accept: '*/*' };
    if (CLIENT_USER_AGENTS[clientType]) {
        headers['User-Agent'] = CLIENT_USER_AGENTS[clientType];
    }
    return headers;
}

async function fetchUrlToBlob(url, onProgress, signal, clientType = 'ANDROID') {
    // googlevideo blocks cross-origin fetch from the app origin (CORS). Stream URLs are
    // obtained via the same-origin proxy, so downloads must use that proxy too (matching IP).
    const fetchUrl = stripRangeFromUrl(url);
    const response = await proxiedFetch(fetchUrl, {
        method: 'GET',
        signal,
        credentials: 'omit',
        headers: streamHeadersForClient(clientType),
    });
    if (!response.ok) {
        throw new Error(`http_${response.status}`);
    }

    const total = Number(response.headers.get('content-length')) || 0;
    if (!response.body) {
        return new Blob([await response.arrayBuffer()]);
    }

    const reader = response.body.getReader();
    const chunks = [];
    let received = 0;

    while (true) {
        if (signal?.aborted) {
            const err = new Error('cancelled');
            err.name = 'AbortError';
            throw err;
        }
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        received += value.byteLength;
        if (typeof onProgress === 'function') {
            onProgress(received, total || received);
        }
    }

    return new Blob(chunks);
}

async function downloadViaBasicInfo(innertube, videoId, clientType, format, onProgress, signal) {
    const clientOpt = { client: clientType };
    const info = await innertube.getBasicInfo(videoId, clientOpt);

    const playErr = playabilityError(info);
    if (playErr) {
        throwPlayabilityFailure(info, playErr);
    }
    if (!hasStreamFormats(info)) {
        throw new Error('no_streaming_data');
    }

    const title = info.basic_info?.title || titleText(info) || videoId;
    const downloadOpts = {
        quality: 'best',
        client: clientType,
    };

    if (format === 'audio') {
        const stream = await info.download({ ...downloadOpts, type: 'audio' });
        const blob = await readableStreamToBlob(stream, onProgress, signal);
        return {
            title,
            files: [{ role: 'audio', blob, ext: guessExt(blob.type, 'm4a') }],
        };
    }

    try {
        const stream = await info.download({
            ...downloadOpts,
            type: 'video+audio',
            format: 'mp4',
        });
        const blob = await readableStreamToBlob(stream, onProgress, signal);
        return {
            title,
            files: [{ role: 'muxed', blob, ext: guessExt(blob.type, 'mp4') }],
        };
    } catch (muxErr) {
        const videoStream = await info.download({
            ...downloadOpts,
            type: 'video',
            format: 'mp4',
        });
        const audioStream = await info.download({
            ...downloadOpts,
            type: 'audio',
        });

        let videoReceived = 0;
        let audioReceived = 0;

        const videoBlob = await readableStreamToBlob(
            videoStream,
            (received) => {
                videoReceived = received;
                if (typeof onProgress === 'function') onProgress(videoReceived + audioReceived, videoReceived + audioReceived);
            },
            signal,
        );

        const audioBlob = await readableStreamToBlob(
            audioStream,
            (received) => {
                audioReceived = received;
                if (typeof onProgress === 'function') onProgress(videoReceived + audioReceived, videoReceived + audioReceived);
            },
            signal,
        );

        return {
            title,
            files: [
                { role: 'video', blob: videoBlob, ext: guessExt(videoBlob.type, 'mp4') },
                { role: 'audio', blob: audioBlob, ext: guessExt(audioBlob.type, 'm4a') },
            ],
        };
    }
}

function listAllFormats(info) {
    const data = info?.streaming_data;
    if (!data) return [];
    return [...(data.formats || []), ...(data.adaptive_formats || [])];
}

function formatNeedsCipher(format) {
    return Boolean(format?.signature_cipher || format?.cipher);
}

function urlNeedsNsig(url) {
    if (!url) return false;
    try {
        return Boolean(new URL(url).searchParams.get('n'));
    } catch (e) {
        return false;
    }
}

function playerCanDecipher(innertube) {
    const player = innertube?.session?.player;
    if (!player?.data?.exported) return false;
    return player.data.exported.includes('nsigFunction');
}

function sortFormatsForTarget(formats, targetFormat) {
    const audioItags = [140, 251, 250, 141, 139, 171];
    const muxedItags = [18, 22];
    const videoItags = [137, 136, 135, 134, 133, 299, 298, 22, 18];

    const score = (fmt) => {
        const itag = Number(fmt.itag) || 0;
        let value = 0;
        if (!formatNeedsCipher(fmt) && fmt.url) value += 100;
        if (targetFormat === 'audio') {
            if (audioItags.includes(itag)) value += 50;
            if (muxedItags.includes(itag)) value += 30;
            if (fmt.has_audio && !fmt.has_video) value += 20;
            if (fmt.has_audio && fmt.has_video) value += 10;
        } else {
            if (muxedItags.includes(itag)) value += 40;
            if (videoItags.includes(itag)) value += 30;
            if (fmt.has_video) value += 10;
        }
        if (fmt.url && !urlNeedsNsig(fmt.url)) value += 25;
        return value + (Number(fmt.bitrate) || 0) / 1_000_000;
    };

    return [...formats].sort((a, b) => score(b) - score(a));
}

async function resolveFormatStreamUrl(format, innertube) {
    const player = innertube?.session?.player;
    const needsCipher = formatNeedsCipher(format);
    const rawUrl = format?.url || '';
    const needsN = urlNeedsNsig(rawUrl);

    if (!needsCipher && rawUrl && !needsN) {
        return rawUrl;
    }
    if ((needsCipher || needsN) && !playerCanDecipher(innertube)) {
        throw new Error('needs_player_decipher');
    }
    const url = await format.decipher(player);
    if (!url) {
        throw new Error('no_stream_url');
    }
    return url;
}

function roleForFormat(format, targetFormat) {
    if (targetFormat === 'audio') {
        if (format.has_audio && !format.has_video) return 'audio';
        return 'muxed';
    }
    if (format.has_video && format.has_audio) return 'muxed';
    return 'video';
}

async function tryDirectFormatDownloads(info, innertube, targetFormat, onProgress, signal, clientType) {
    const formats = sortFormatsForTarget(listAllFormats(info), targetFormat);
    let lastError = null;

    for (const format of formats) {
        try {
            const streamUrl = await resolveFormatStreamUrl(format, innertube);
            const blob = await fetchUrlToBlob(streamUrl, onProgress, signal, clientType);
            return [{
                role: roleForFormat(format, targetFormat),
                blob,
                ext: guessExt(format.mime_type || blob.type, targetFormat === 'audio' ? 'm4a' : 'mp4'),
            }];
        } catch (err) {
            lastError = err;
        }
    }

    if (lastError) throw lastError;
    throw new Error('no_stream_url');
}

async function downloadViaInnertubeDownload(innertube, videoId, clientType, targetFormat, onProgress, signal) {
    const info = await innertube.getBasicInfo(videoId, { client: clientType });
    const playErr = playabilityError(info);
    if (playErr) throwPlayabilityFailure(info, playErr);
    if (!hasStreamFormats(info)) throw new Error('no_streaming_data');

    const title = info.basic_info?.title || titleText(info) || videoId;
    const downloadOpts = {
        quality: 'best',
        client: clientType,
        type: 'video+audio',
        format: 'mp4',
    };

    try {
        const stream = await info.download(downloadOpts);
        const blob = await readableStreamToBlob(stream, onProgress, signal);
        return {
            title,
            files: [{ role: 'muxed', blob, ext: guessExt(blob.type, 'mp4') }],
        };
    } catch (muxErr) {
        if (targetFormat !== 'video') {
            throw muxErr;
        }
        const files = await tryDirectFormatDownloads(info, innertube, targetFormat, onProgress, signal, clientType);
        return { title, files };
    }
}

async function downloadViaDirectUrl(innertube, videoId, clientType, targetFormat, onProgress, signal) {
    const info = await innertube.getBasicInfo(videoId, { client: clientType });

    const playErr = playabilityError(info);
    if (playErr) {
        throwPlayabilityFailure(info, playErr);
    }
    if (!hasStreamFormats(info)) {
        throw new Error('no_streaming_data');
    }

    const title = info.basic_info?.title || titleText(info) || videoId;
    const files = await tryDirectFormatDownloads(info, innertube, targetFormat, onProgress, signal, clientType);
    return { title, files };
}

function shouldRetryWithPlayer(err) {
    const msg = String(err?.message || err || '').toLowerCase();
    return msg.includes('decipher')
        || msg.includes('signature')
        || msg.includes('no_stream')
        || msg.includes('no matching formats')
        || msg.includes('needs_player')
        || msg.includes('http_403')
        || msg.includes('non 2xx')
        || msg.includes('fetch_failed')
        || msg.includes('failed to fetch')
        || msg.includes('empty_player');
}

async function downloadWithClient(clientType, videoId, format, options = {}) {
    const { onProgress, signal } = options;

    // Avoid loading the JS player unless necessary (player parser often breaks on new YouTube builds).
    let innertube = await createInnertube(clientType, { retrievePlayer: false });
    try {
        return await downloadViaDirectUrl(innertube, videoId, clientType, format, onProgress, signal);
    } catch (directErr) {
        console.warn(`[MediaDownloader] ${clientType} direct failed for ${videoId}:`, directErr);
        if (!shouldRetryWithPlayer(directErr)) {
            throw directErr;
        }
    }

    try {
        return await downloadViaInnertubeDownload(innertube, videoId, clientType, format, onProgress, signal);
    } catch (muxErr) {
        console.warn(`[MediaDownloader] ${clientType} muxed failed for ${videoId}:`, muxErr);
        if (!shouldRetryWithPlayer(muxErr)) {
            throw muxErr;
        }
    }

    innertube = await createInnertube(clientType, { retrievePlayer: true });
    if (!playerCanDecipher(innertube)) {
        throw new Error('player_decipher_unavailable');
    }
    return await downloadViaDirectUrl(innertube, videoId, clientType, format, onProgress, signal);
}

export async function getVideoMetadata(videoId) {
    for (const clientType of getDownloadClients()) {
        try {
            const innertube = await createInnertube(clientType, { retrievePlayer: false });
            const info = await innertube.getBasicInfo(videoId, { client: clientType });
            if (playabilityError(info)) continue;
            return {
                id: videoId,
                title: info.basic_info?.title || titleText(info) || videoId,
                duration: info.basic_info?.duration || durationSeconds(info),
            };
        } catch (e) {
            // try next client
        }
    }
    const innertube = await createInnertube('WEB', { retrievePlayer: false });
    const info = await innertube.getBasicInfo(videoId, { client: 'WEB' });
    return {
        id: videoId,
        title: info.basic_info?.title || titleText(info) || videoId,
        duration: info.basic_info?.duration || durationSeconds(info),
    };
}

async function downloadWithAuthenticatedClient(videoId, format, options = {}) {
    const { onProgress, signal } = options;
    const innertube = await ensureAuthenticatedInnertube();
    try {
        return await downloadViaDirectUrl(innertube, videoId, AUTHENTICATED_CLIENT, format, onProgress, signal);
    } catch (directErr) {
        console.warn(`[MediaDownloader] ${AUTHENTICATED_CLIENT} auth direct failed for ${videoId}:`, directErr);
        if (!shouldRetryWithPlayer(directErr)) {
            throw directErr;
        }
    }
    return downloadViaInnertubeDownload(innertube, videoId, AUTHENTICATED_CLIENT, format, onProgress, signal);
}

/**
 * Download media for a video ID.
 * @returns {Promise<{title: string, files: Array<{role: string, blob: Blob, ext: string}>}>}
 */
export async function downloadMedia(videoId, format, options = {}) {
    const { onProgress, signal, title: titleOverride } = options;
    let lastError = null;

    if (isYoutubeSignedIn()) {
        try {
            const result = await downloadWithAuthenticatedClient(videoId, format, options);
            if (titleOverride) result.title = titleOverride;
            if (typeof onProgress === 'function') onProgress(100);
            return result;
        } catch (err) {
            lastError = err;
            console.warn(`[MediaDownloader] Authenticated download failed for ${videoId}:`, err);
            if (err?.code === 'err_age_restricted' || mapClientError(err) === 'err_age_restricted') {
                throw err;
            }
        }
    }

    for (const clientType of getDownloadClients()) {
        try {
            const result = await downloadWithClient(clientType, videoId, format, options);
            if (titleOverride) result.title = titleOverride;
            if (typeof onProgress === 'function') onProgress(100);
            return result;
        } catch (err) {
            lastError = err;
            console.warn(`[MediaDownloader] ${clientType} failed for ${videoId}:`, err);
            if (err?.code === 'err_age_restricted' || mapClientError(err) === 'err_age_restricted') {
                throw err;
            }
        }
    }

    throw lastError || new Error('client_download_failed');
}

function extractPlaylistVideos(playlist) {
    const items = playlist?.items || playlist?.videos || [];
    const entries = [];

    for (const item of items) {
        if (!item) continue;
        const video = item.video || item;
        const id = video.id || video.video_id || item.id;
        if (!id || typeof id !== 'string') continue;

        const title = titleText(video) || titleText(item) || id;
        if (['[Private video]', '[Deleted video]', '[Unavailable video]'].includes(title)) {
            continue;
        }

        entries.push({
            id,
            title,
            url: `https://www.youtube.com/watch?v=${id}`,
            duration: durationSeconds(video) || durationSeconds(item),
        });
    }

    return entries;
}

export async function getPlaylistEntries(url) {
    const playlistId = resolvePlaylistId(url);
    if (!playlistId) {
        throw new Error('not_a_playlist');
    }

    const innertube = await getPlaylistClient();
    const playlist = await innertube.getPlaylist(playlistId);
    const entries = extractPlaylistVideos(playlist);

    if (!entries.length) {
        throw new Error('empty_playlist');
    }

    const playlistTitle = titleText(playlist) || titleText(playlist.header) || 'Playlist';
    return {
        playlist_title: playlistTitle,
        entry_count: entries.length,
        entries,
    };
}

export class ClientDownloadError extends Error {
    constructor(code, message) {
        super(message || code);
        this.code = code;
        this.name = 'ClientDownloadError';
    }
}

function extractErrorText(err) {
    if (!err) return '';
    const parts = [
        err.message,
        err.code,
        err.status,
        err.info?.reason,
        err.info?.playability_status?.reason,
        err.fallback?.message,
    ].filter(Boolean);
    return parts.join(' ');
}

export function mapClientError(err) {
    if (err?.code === 'err_age_restricted') return 'err_age_restricted';
    if (err?.code === 'err_bot_check') return 'err_bot_check';

    const lower = extractErrorText(err).toLowerCase();

    if (err?.name === 'AbortError' || lower.includes('cancelled')) return 'cancelled';
    if (lower.includes('private video') || lower.includes('video unavailable')
        || lower.includes('not available') || lower.includes('unavailable')) {
        return 'err_video_unavailable';
    }
    if (isBotCheckText(lower)) {
        return 'err_bot_check';
    }
    if (isAgeRestrictionText(lower)) {
        return 'err_age_restricted';
    }
    if (lower.includes('sign in') || lower.includes('login required')
        || lower.includes('http_403') || lower.includes(' 403') || lower.includes('forbidden')) {
        return 'err_bot_check';
    }
    if (lower.includes('unexpected token') || lower.includes('decipher') || lower.includes('signature')
        || lower.includes('player_decipher')) {
        return 'err_download_failed';
    }
    if (lower.includes('proxy_failed') || lower.includes('failed to fetch')) {
        return 'client_download_failed';
    }
    if (lower.includes('no_stream') || lower.includes('no_audio') || lower.includes('no_video')
        || lower.includes('no_streaming')) {
        return 'err_download_failed';
    }
    return 'client_download_failed';
}
