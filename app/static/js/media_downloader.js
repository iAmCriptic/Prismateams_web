(function () {
    'use strict';

    const PLAYLIST_LIST_PREFIXES = ['PL', 'OL', 'LL', 'FL', 'VL', 'PU', 'UU'];
    const VIEW_STORAGE_KEY = 'mediaDownloaderViewMode';
    const URL_IN_TEXT_RE = /https?:\/\/[^\s<>"']+/i;
    const BARE_YT_RE = /(?:www\.)?(?:music\.)?(?:m\.)?(?:youtube\.com|youtu\.be)\/\S+/i;

    function ready(fn) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', fn);
        } else {
            fn();
        }
    }

    ready(initMediaDownloader);

    function initMediaDownloader() {
        const root = document.getElementById('mediaDownloaderApp');
        if (!root) return;

        const cfg = {
            youtubeSearchEnabled: root.dataset.youtubeSearch === '1',
            previewUrl: root.dataset.previewUrl,
            batchUrl: root.dataset.batchUrl,
            jobsUrl: root.dataset.jobsUrl,
            clearAllUrl: root.dataset.clearAllUrl,
            youtubeSearchUrl: root.dataset.youtubeSearchUrl,
            downloadUrlTemplate: root.dataset.downloadUrlTemplate,
            statusUrlTemplate: root.dataset.statusUrlTemplate,
            deleteUrlTemplate: root.dataset.deleteUrlTemplate,
            progressUrlTemplate: root.dataset.progressUrlTemplate,
            uploadUrlTemplate: root.dataset.uploadUrlTemplate,
            failUrlTemplate: root.dataset.failUrlTemplate,
            maxConcurrent: Number(root.dataset.maxConcurrent) || 2,
            statusLabels: {
                pending: root.dataset.i18nStatusPending,
                processing: root.dataset.i18nStatusProcessing,
                downloading: root.dataset.i18nStatusDownloading,
                uploading: root.dataset.i18nStatusUploading,
                converting: root.dataset.i18nStatusConverting,
                completed: root.dataset.i18nStatusCompleted,
                failed: root.dataset.i18nStatusFailed,
                cancelled: root.dataset.i18nStatusCancelled,
                cancelling: root.dataset.i18nStatusCancelling,
            },
            formatLabels: {
                audio: root.dataset.i18nFormatAudio,
                video: root.dataset.i18nFormatVideo,
            },
            downloadLabel: root.dataset.i18nDownload,
            deleteLabel: root.dataset.i18nDelete,
            deleteConfirm: root.dataset.i18nDeleteConfirm,
            openSourceLabel: root.dataset.i18nOpenSource,
            actionsLabel: root.dataset.i18nActions,
            timePlaceholder: root.dataset.i18nTimePlaceholder,
            startLabel: root.dataset.i18nStartLabel,
            endLabel: root.dataset.i18nEndLabel,
            songCountTemplate: root.dataset.i18nSongCount,
            previewErrorLabel: root.dataset.i18nPreviewError,
            segmentTitle: root.dataset.i18nSegmentTitle,
            playlistSegmentTitle: root.dataset.i18nPlaylistSegmentTitle,
            submitLabel: root.dataset.i18nSubmit,
            submitPlaylistLabel: root.dataset.i18nSubmitPlaylist,
            clearAllConfirm: root.dataset.i18nClearConfirm,
            searchEmpty: root.dataset.i18nSearchEmpty,
            searchError: root.dataset.i18nSearchError,
            searchLoading: root.dataset.i18nSearchLoading,
            i18nYoutubeAuthLoading: root.dataset.i18nYoutubeAuthLoading,
            i18nYoutubeAuthFailed: root.dataset.i18nYoutubeAuthFailed,
            i18nYoutubeAuthUnavailable: root.dataset.i18nYoutubeAuthUnavailable,
            i18nYoutubeAuthRequired: root.dataset.i18nYoutubeAuthRequired,
            tabMeta: {
                download: { icon: 'bi-plus-circle', title: root.dataset.i18nTabDownload },
                jobs: { icon: 'bi-list-ul', title: root.dataset.i18nTabJobs },
            },
        };

        const progressState = new Map();
        const progressIntervals = new Map();
        const clientAbortControllers = new Map();
        const clientJobQueue = [];
        let clientActiveCount = 0;
        let clientReadyPromise = null;
        let playlistData = null;
        let playlistPreviewUrl = '';
        let previewInFlight = false;
        let lastPreviewedUrl = '';
        let inputMode = 'single'; // 'single' | 'playlist'
        let viewMode = localStorage.getItem(VIEW_STORAGE_KEY) || 'list';

        const singleUrlInput = document.getElementById('single_url');
        const playlistUrlInput = document.getElementById('playlist_url');
        const sourceUrlInput = singleUrlInput; // alias for job helpers that expect sourceUrlInput
        const downloadForm = document.getElementById('downloadForm');
        const submitBtn = document.getElementById('downloadSubmitBtn')
            || (downloadForm ? downloadForm.querySelector('button[type="submit"]') : null);
        const singleSegmentPanel = document.getElementById('singleSegmentPanel');
        const playlistSegmentPanel = document.getElementById('playlistSegmentPanel');
        const segmentCardTitle = document.getElementById('segmentCardTitle');
        const submitLabelEl = submitBtn ? submitBtn.querySelector('[data-submit-label]') : null;
        const searchInput = document.getElementById('mediaYoutubeSearch');
        const searchResultsEl = document.getElementById('mediaSearchResults');
        let searchTimer = null;
        let searchAbort = null;

        const statusRank = {
            pending: 1,
            downloading: 2,
            uploading: 3,
            processing: 4,
            converting: 4,
            cancelling: 5,
            completed: 6,
            failed: 6,
            cancelled: 6,
        };

        const ACTIVE_JOB_STATUSES = new Set([
            'pending', 'downloading', 'uploading', 'processing', 'converting', 'cancelling',
        ]);

        function configureClient() {
            const proxyUrl = root.dataset.youtubeProxyUrl;
            const youtubeiUrl = root.dataset.youtubeiUrl;
            const youtubeOAuthClientUrl = root.dataset.youtubeOauthClientUrl;
            if (window.MediaDownloaderClient?.configure) {
                window.MediaDownloaderClient.configure({
                    proxyUrl,
                    youtubeiUrl,
                    youtubeOAuthClientUrl,
                    onAuthPending: showYoutubeAuthModal,
                    onAuthStateChange: updateYoutubeAuthUi,
                });
                const client = window.MediaDownloaderClient;
                if (client.isYoutubeSignedIn?.()) {
                    updateYoutubeAuthUi(true);
                    client.warmupYoutubeSession?.().then((ok) => {
                        updateYoutubeAuthUi(Boolean(ok));
                    }).catch(() => {
                        updateYoutubeAuthUi(false);
                    });
                } else {
                    updateYoutubeAuthUi(false);
                }
            }
        }

        const youtubeAuthModalEl = document.getElementById('youtubeAuthModal');
        const youtubeAuthUserCodeEl = document.getElementById('youtubeAuthUserCode');
        const youtubeAuthVerifyLinkEl = document.getElementById('youtubeAuthVerifyLink');
        const youtubeSignInBtn = document.getElementById('youtubeSignInBtn');
        const youtubeSignOutBtn = document.getElementById('youtubeSignOutBtn');
        const youtubeAuthStatusSignedIn = document.getElementById('youtubeAuthStatusSignedIn');
        const youtubeAuthStatusSignedOut = document.getElementById('youtubeAuthStatusSignedOut');
        const youtubeAuthErrorEl = document.getElementById('youtubeAuthError');
        let youtubeAuthModal = null;
        let youtubeAuthLoading = false;
        let youtubeSignInPromise = null;

        function clearYoutubeAuthError() {
            if (!youtubeAuthErrorEl) return;
            youtubeAuthErrorEl.textContent = '';
            youtubeAuthErrorEl.classList.add('d-none');
        }

        function showYoutubeAuthError(message) {
            if (!youtubeAuthErrorEl || !message) return;
            youtubeAuthErrorEl.textContent = message;
            youtubeAuthErrorEl.classList.remove('d-none');
        }

        function setYoutubeAuthButtonLoading(loading) {
            youtubeAuthLoading = loading;
            if (!youtubeSignInBtn) return;
            youtubeSignInBtn.setAttribute('aria-busy', loading ? 'true' : 'false');
            const label = youtubeSignInBtn.querySelector('[data-yt-auth-label]');
            const spinner = youtubeSignInBtn.querySelector('[data-yt-auth-spinner]');
            if (label) label.classList.toggle('d-none', loading);
            if (spinner) spinner.classList.toggle('d-none', !loading);
        }

        function cleanupYoutubeAuthModalBackdrop() {
            document.querySelectorAll('.modal-backdrop').forEach((el) => el.remove());
            document.body.classList.remove('modal-open');
            document.body.style.removeProperty('overflow');
            document.body.style.removeProperty('padding-right');
        }

        function hideYoutubeAuthModal() {
            getYoutubeAuthModal()?.hide();
            cleanupYoutubeAuthModalBackdrop();
        }

        function cancelYoutubeSignInFlow() {
            if (window.MediaDownloaderClient?.cancelYoutubeSignIn) {
                window.MediaDownloaderClient.cancelYoutubeSignIn();
            }
            youtubeSignInPromise = null;
            setYoutubeAuthButtonLoading(false);
        }

        function highlightYoutubeAuthBar() {
            const bar = document.getElementById('youtubeAuthBar');
            if (!bar) return;
            bar.classList.add('media-youtube-auth-bar--highlight');
            window.setTimeout(() => bar.classList.remove('media-youtube-auth-bar--highlight'), 3200);
        }

        function promptYoutubeAuthAttention(errorKey) {
            if (errorKey === 'err_bot_check' || errorKey === 'err_age_restricted') {
                switchMediaTab('download');
                highlightYoutubeAuthBar();
                showYoutubeAuthError(cfg.i18nYoutubeAuthRequired || cfg.i18nYoutubeAuthFailed);
            }
        }

        function getYoutubeAuthModal() {
            if (!youtubeAuthModal && youtubeAuthModalEl && window.bootstrap?.Modal) {
                youtubeAuthModal = new window.bootstrap.Modal(youtubeAuthModalEl);
                youtubeAuthModalEl.addEventListener('hidden.bs.modal', () => {
                    cleanupYoutubeAuthModalBackdrop();
                    if (youtubeAuthLoading) {
                        cancelYoutubeSignInFlow();
                    }
                });
            }
            return youtubeAuthModal;
        }

        function showYoutubeAuthModal(payload) {
            if (youtubeAuthUserCodeEl && payload?.userCode) {
                youtubeAuthUserCodeEl.textContent = payload.userCode;
            }
            if (youtubeAuthVerifyLinkEl && payload?.verificationUrl) {
                youtubeAuthVerifyLinkEl.href = payload.verificationUrl;
            }
            getYoutubeAuthModal()?.show();
        }

        function updateYoutubeAuthUi(signedIn) {
            const isIn = Boolean(signedIn);
            youtubeSignInBtn?.classList.toggle('d-none', isIn);
            youtubeSignOutBtn?.classList.toggle('d-none', !isIn);
            youtubeAuthStatusSignedIn?.classList.toggle('d-none', !isIn);
            youtubeAuthStatusSignedOut?.classList.toggle('d-none', isIn);
            if (isIn) clearYoutubeAuthError();
        }

        async function promptYoutubeSignIn() {
            if (youtubeSignInPromise) {
                return youtubeSignInPromise;
            }
            youtubeSignInPromise = (async () => {
                await waitForClient();
                configureClient();
                const client = window.MediaDownloaderClient;
                if (!client?.signInToYoutube) {
                    throw new Error(cfg.i18nYoutubeAuthUnavailable || 'YouTube-Anmeldung ist noch nicht bereit.');
                }
                return client.signInToYoutube();
            })();
            try {
                return await youtubeSignInPromise;
            } finally {
                youtubeSignInPromise = null;
            }
        }

        async function handleYoutubeSignInClick() {
            if (!youtubeSignInBtn || youtubeAuthLoading) return;
            clearYoutubeAuthError();
            setYoutubeAuthButtonLoading(true);
            try {
                await waitForClient();
                configureClient();
                showYoutubeAuthModal({
                    userCode: cfg.i18nYoutubeAuthLoading || '…',
                    verificationUrl: 'https://www.youtube.com/activate',
                });
                await promptYoutubeSignIn();
                hideYoutubeAuthModal();
            } catch (err) {
                if (err?.name === 'AbortError' || err?.message === 'youtube_sign_in_cancelled') {
                    return;
                }
                console.error('[MediaDownloader] YouTube sign-in failed:', err);
                showYoutubeAuthError(err?.message || cfg.i18nYoutubeAuthFailed || 'YouTube-Anmeldung fehlgeschlagen.');
                hideYoutubeAuthModal();
            } finally {
                setYoutubeAuthButtonLoading(false);
            }
        }

        async function handleYoutubeSignOutClick() {
            clearYoutubeAuthError();
            try {
                await waitForClient();
                await window.MediaDownloaderClient?.signOutFromYoutube?.();
            } catch (err) {
                console.error('[MediaDownloader] YouTube sign-out failed:', err);
                showYoutubeAuthError(err?.message || cfg.i18nYoutubeAuthFailed || 'YouTube-Abmeldung fehlgeschlagen.');
            }
        }

        youtubeSignInBtn?.addEventListener('click', handleYoutubeSignInClick);
        youtubeSignOutBtn?.addEventListener('click', handleYoutubeSignOutClick);

        function waitForClient() {
            if (window.MediaDownloaderClient) {
                configureClient();
                return Promise.resolve(window.MediaDownloaderClient);
            }
            if (!clientReadyPromise) {
                clientReadyPromise = new Promise((resolve, reject) => {
                    let attempts = 0;
                    const timer = setInterval(() => {
                        if (window.MediaDownloaderClient) {
                            clearInterval(timer);
                            configureClient();
                            resolve(window.MediaDownloaderClient);
                            return;
                        }
                        attempts += 1;
                        if (attempts > 120) {
                            clearInterval(timer);
                            reject(new Error('client_load_failed'));
                        }
                    }, 250);
                });
            }
            return clientReadyPromise;
        }

        function jobProgressUrl(jobId) {
            return cfg.progressUrlTemplate.replace('/0', `/${jobId}`);
        }

        function jobUploadUrl(jobId) {
            return cfg.uploadUrlTemplate.replace('/0', `/${jobId}`);
        }

        function jobFailUrl(jobId) {
            return cfg.failUrlTemplate.replace('/0', `/${jobId}`);
        }

        async function patchJobProgress(jobId, payload) {
            try {
                await fetch(jobProgressUrl(jobId), {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
            } catch (err) {
                // ignore transient network errors during progress
            }
        }

        function setJobProgressUi(jobId, percent, status) {
            const id = String(jobId);
            progressState.set(id, { percent: Math.max(0, Math.min(100, percent)) });
            jobElements(id).forEach((el) => renderProgressBar(el, percent, status || el.dataset.status));
        }

        async function failClientJob(jobId, errorKey) {
            try {
                const response = await fetch(jobFailUrl(jobId), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ error_key: errorKey || 'client_download_failed' }),
                });
                const data = await response.json().catch(() => ({}));
                if (data.status === 'failed' && data.error_message) {
                    setFailedStatus(jobId, data.error_message);
                    updateJobsBadge();
                    return;
                }
                if (response.status === 410) {
                    removeJobElements(jobId);
                    return;
                }
            } catch (err) {
                // ignore
            }
            pollJob(jobId);
        }

        async function runClientJob(job, authRetry = false) {
            const jobId = job.id;
            const controller = new AbortController();
            clientAbortControllers.set(String(jobId), controller);

            try {
                const client = await waitForClient();
                const videoId = client.resolveVideoId(job.source_url);
                if (!videoId) {
                    await failClientJob(jobId, 'err_download_failed');
                    return;
                }

                setJobProgressUi(jobId, 2, 'downloading');
                await patchJobProgress(jobId, { status: 'downloading', progress: 2, title: job.title });

                const result = await client.downloadMedia(
                    videoId,
                    job.format,
                    {
                        signal: controller.signal,
                        title: job.title,
                        onProgress: (pct) => {
                            const mapped = Math.min(85, Math.max(3, Math.round(pct * 0.85)));
                            setJobProgressUi(jobId, mapped, 'downloading');
                            if (mapped % 5 === 0) {
                                patchJobProgress(jobId, { status: 'downloading', progress: mapped });
                            }
                        },
                    },
                );

                if (controller.signal.aborted) {
                    await failClientJob(jobId, 'cancelled');
                    return;
                }

                setJobProgressUi(jobId, 88, 'uploading');
                await patchJobProgress(jobId, {
                    status: 'uploading',
                    progress: 88,
                    title: result.title || job.title,
                });

                const formData = new FormData();
                if (result.title) formData.append('title', result.title);
                result.files.forEach((file) => {
                    const name = `${file.role}.${file.ext}`;
                    formData.append(file.role === 'muxed' ? 'file' : file.role, file.blob, name);
                });

                const uploadResponse = await fetch(jobUploadUrl(jobId), {
                    method: 'POST',
                    body: formData,
                    signal: controller.signal,
                });

                if (!uploadResponse.ok) {
                    await failClientJob(jobId, 'upload_failed');
                    return;
                }

                setJobProgressUi(jobId, 95, 'converting');
                pollJob(jobId);
            } catch (err) {
                if (err && err.name === 'AbortError') {
                    await failClientJob(jobId, 'cancelled');
                    return;
                }
                console.error('[MediaDownloader] Client download failed:', err);
                const client = window.MediaDownloaderClient;
                const errorKey = client ? client.mapClientError(err) : 'client_download_failed';
                if (errorKey === 'err_bot_check' && !authRetry && client?.signInToYoutube) {
                    promptYoutubeAuthAttention(errorKey);
                    if (client.isYoutubeSignedIn?.()) {
                        await client.signOutFromYoutube?.().catch(() => {});
                    }
                    try {
                        await promptYoutubeSignIn();
                        return runClientJob(job, true);
                    } catch (authErr) {
                        if (authErr?.name !== 'AbortError' && authErr?.message !== 'youtube_sign_in_cancelled') {
                            console.warn('[MediaDownloader] YouTube sign-in cancelled or failed:', authErr);
                        }
                    }
                }
                await failClientJob(jobId, errorKey);
            } finally {
                clientAbortControllers.delete(String(jobId));
            }
        }

        function pumpClientQueue() {
            while (clientActiveCount < cfg.maxConcurrent && clientJobQueue.length) {
                const job = clientJobQueue.shift();
                if (!job) break;
                clientActiveCount += 1;
                runClientJob(job).finally(() => {
                    clientActiveCount = Math.max(0, clientActiveCount - 1);
                    pumpClientQueue();
                });
            }
        }

        function enqueueClientJob(job) {
            if (!job || !job.id) return;
            if (!ACTIVE_JOB_STATUSES.has(job.status)) return;
            if (job.status === 'converting' || job.status === 'processing') {
                pollJob(job.id);
                return;
            }
            const id = String(job.id);
            if (clientJobQueue.some((queued) => String(queued.id) === id)) return;
            clientJobQueue.push(job);
            pumpClientQueue();
        }

        function switchMediaTab(tab) {
            if (!cfg.tabMeta[tab]) return;

            document.querySelectorAll('.mod-nav-link[data-media-tab]').forEach((btn) => {
                btn.classList.toggle('active', btn.getAttribute('data-media-tab') === tab);
            });

            document.querySelectorAll('[data-media-panel]').forEach((panel) => {
                const isActive = panel.getAttribute('data-media-panel') === tab;
                panel.classList.toggle('d-none', !isActive);
                if (isActive) {
                    panel.removeAttribute('hidden');
                } else {
                    panel.setAttribute('hidden', '');
                }
            });

            const heading = document.getElementById('mediaViewHeading');
            if (heading && cfg.tabMeta[tab]) {
                heading.innerHTML = `<i class="bi ${cfg.tabMeta[tab].icon}" aria-hidden="true"></i><span>${cfg.tabMeta[tab].title}</span>`;
            }
        }

        function dismissMediaOffcanvas() {
            const offcanvasEl = document.getElementById('mediaMobileNav');
            if (offcanvasEl && window.bootstrap && window.bootstrap.Offcanvas) {
                const instance = bootstrap.Offcanvas.getInstance(offcanvasEl);
                if (instance) instance.hide();
            }
        }

        function applyViewMode(mode) {
            viewMode = mode === 'grid' ? 'grid' : 'list';
            localStorage.setItem(VIEW_STORAGE_KEY, viewMode);

            const listView = document.getElementById('jobsListView');
            const gridView = document.getElementById('jobsGridView');
            const listBtn = document.getElementById('mediaListViewBtn');
            const gridBtn = document.getElementById('mediaGridViewBtn');
            const hasJobs = document.querySelectorAll('.media-job').length > 0;
            const isGrid = viewMode === 'grid';

            if (listBtn) listBtn.classList.toggle('active', !isGrid);
            if (gridBtn) gridBtn.classList.toggle('active', isGrid);

            if (!hasJobs) {
                if (listView) {
                    listView.classList.add('d-none');
                    listView.setAttribute('hidden', '');
                    listView.style.display = 'none';
                }
                if (gridView) {
                    gridView.classList.add('d-none');
                    gridView.setAttribute('hidden', '');
                    gridView.style.display = 'none';
                }
                return;
            }

            if (listView) {
                listView.classList.toggle('d-none', isGrid);
                if (isGrid) {
                    listView.setAttribute('hidden', '');
                    listView.style.display = 'none';
                } else {
                    listView.removeAttribute('hidden');
                    listView.style.display = '';
                }
            }
            if (gridView) {
                gridView.classList.toggle('d-none', !isGrid);
                if (!isGrid) {
                    gridView.setAttribute('hidden', '');
                    gridView.style.display = 'none';
                } else {
                    gridView.removeAttribute('hidden');
                    gridView.style.display = '';
                }
            }
        }

        function countActiveJobs() {
            const seen = new Set();
            let count = 0;
            document.querySelectorAll('.media-job').forEach((el) => {
                const id = el.dataset.jobId;
                if (seen.has(id)) return;
                seen.add(id);
                const status = el.dataset.status;
                if (status === 'pending' || status === 'downloading' || status === 'uploading'
                    || status === 'processing' || status === 'converting' || status === 'cancelling') {
                    count += 1;
                }
            });
            return count;
        }

        function updateJobsBadge() {
            const count = countActiveJobs();
            document.querySelectorAll('[data-media-jobs-badge]').forEach((badge) => {
                badge.dataset.count = String(count);
                badge.textContent = count > 0 ? String(count) : '';
            });
        }

        function getPlaylistModal() {
            // Modal removed — kept as no-op for safety
            return null;
        }

        function setInputMode(mode) {
            inputMode = mode === 'playlist' ? 'playlist' : 'single';
            const isPlaylist = inputMode === 'playlist';

            if (singleSegmentPanel) {
                singleSegmentPanel.classList.toggle('d-none', isPlaylist);
                if (isPlaylist) singleSegmentPanel.setAttribute('hidden', '');
                else singleSegmentPanel.removeAttribute('hidden');
            }
            if (playlistSegmentPanel) {
                playlistSegmentPanel.classList.toggle('d-none', !isPlaylist);
                if (isPlaylist) playlistSegmentPanel.removeAttribute('hidden');
                else playlistSegmentPanel.setAttribute('hidden', '');
            }
            if (segmentCardTitle) {
                segmentCardTitle.textContent = isPlaylist
                    ? (cfg.playlistSegmentTitle || cfg.segmentTitle)
                    : cfg.segmentTitle;
            }
            if (submitLabelEl) {
                submitLabelEl.textContent = isPlaylist
                    ? (cfg.submitPlaylistLabel || cfg.submitLabel)
                    : cfg.submitLabel;
            }
        }

        function resetPlaylistPanel() {
            playlistData = null;
            playlistPreviewUrl = '';
            lastPreviewedUrl = '';
            const loading = document.getElementById('playlistLoading');
            const err = document.getElementById('playlistError');
            const content = document.getElementById('playlistContent');
            const entries = document.getElementById('playlistEntries');
            if (loading) loading.classList.add('d-none');
            if (err) {
                err.classList.add('d-none');
                err.textContent = '';
            }
            if (content) content.classList.add('d-none');
            if (entries) entries.innerHTML = '';
        }

        function activateSingleMode(options) {
            const opts = options || {};
            if (!opts.keepPlaylistUrl && playlistUrlInput) {
                playlistUrlInput.value = '';
            }
            resetPlaylistPanel();
            setInputMode('single');
        }

        function activatePlaylistMode() {
            if (singleUrlInput) singleUrlInput.value = '';
            const start = document.getElementById('start_time');
            const end = document.getElementById('end_time');
            if (start) start.value = '';
            if (end) end.value = '';
            setInputMode('playlist');
        }

        function isTruePlaylistListId(listId) {
            if (!listId) return false;
            const upper = String(listId).trim().toUpperCase();
            return PLAYLIST_LIST_PREFIXES.some((prefix) => upper.startsWith(prefix));
        }

        function canonicalizePlaylistUrl(url) {
            const cleaned = normalizeMediaUrl(url);
            if (!cleaned || !isPlaylistUrl(cleaned)) return cleaned;
            try {
                const parsed = new URL(cleaned);
                let host = parsed.hostname.toLowerCase();
                if (host.startsWith('www.')) host = host.slice(4);
                const listId = parsed.searchParams.get('list');
                if (!listId) return cleaned;
                if (host === 'music.youtube.com' || host.endsWith('.music.youtube.com')) {
                    return `https://music.youtube.com/playlist?list=${encodeURIComponent(listId)}`;
                }
                return `https://www.youtube.com/playlist?list=${encodeURIComponent(listId)}`;
            } catch (e) {
                return cleaned;
            }
        }

        function normalizeMediaUrl(text) {
            if (!text) return '';
            let cleaned = String(text).trim();
            const httpMatch = cleaned.match(URL_IN_TEXT_RE);
            if (httpMatch) {
                cleaned = httpMatch[0];
            } else {
                const bare = cleaned.match(BARE_YT_RE);
                if (bare) {
                    cleaned = `https://${bare[0].replace(/^\/+/, '')}`;
                }
            }
            return cleaned.replace(/[),.;'"\]]+$/g, '');
        }

        function isPlaylistUrl(url) {
            const cleaned = normalizeMediaUrl(url);
            if (!cleaned) return false;
            try {
                const parsed = new URL(cleaned);
                let host = parsed.hostname.toLowerCase();
                if (host.startsWith('www.')) host = host.slice(4);

                const isYt = host === 'youtube.com' || host.endsWith('.youtube.com')
                    || host === 'youtu.be' || host === 'music.youtube.com'
                    || host.endsWith('.music.youtube.com');
                if (!isYt) return false;

                const path = (parsed.pathname || '').replace(/\/+$/, '').toLowerCase() || '/';
                const listId = parsed.searchParams.get('list');

                if (path === '/playlist' || path.endsWith('/playlist')) {
                    return Boolean(listId);
                }

                // Any real playlist list= id on an allowed YouTube host
                if (isTruePlaylistListId(listId)) {
                    return true;
                }

                if (host === 'music.youtube.com' || host.endsWith('.music.youtube.com')) {
                    if (path.startsWith('/browse/') && listId) return true;
                }

                return false;
            } catch (e) {
                return false;
            }
        }

        function extractUrlFromText(text) {
            return normalizeMediaUrl(text);
        }

        function formatDuration(seconds) {
            if (!seconds && seconds !== 0) return '';
            const mins = Math.floor(seconds / 60);
            const secs = Math.floor(seconds % 60);
            return `${mins}:${secs.toString().padStart(2, '0')}`;
        }

        function getSelectedFormat() {
            const checked = document.querySelector('input[name="format"]:checked');
            return checked ? checked.value : 'audio';
        }

        function showPlaylistLoading() {
            activatePlaylistMode();
            const loading = document.getElementById('playlistLoading');
            const content = document.getElementById('playlistContent');
            const err = document.getElementById('playlistError');
            if (loading) loading.classList.remove('d-none');
            if (content) content.classList.add('d-none');
            if (err) err.classList.add('d-none');
        }

        function showPlaylistError(message) {
            activatePlaylistMode();
            const errorEl = document.getElementById('playlistError');
            if (errorEl) {
                errorEl.textContent = message;
                errorEl.classList.remove('d-none');
            }
            const loading = document.getElementById('playlistLoading');
            const content = document.getElementById('playlistContent');
            if (loading) loading.classList.add('d-none');
            if (content) content.classList.add('d-none');
        }

        function escapeHtml(value) {
            return String(value || '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        }

        function renderPlaylistEntries() {
            const mode = document.querySelector('input[name="playlist_mode"]:checked')?.value || 'complete';
            const container = document.getElementById('playlistEntries');
            if (!container || !playlistData) return;
            container.innerHTML = '';

            (playlistData.entries || []).forEach((entry, index) => {
                const item = document.createElement('div');
                item.className = 'media-playlist-entry';
                const duration = entry.duration
                    ? `<small class="text-muted ms-2">${formatDuration(entry.duration)}</small>`
                    : '';
                let timestampFields = '';
                if (mode === 'timestamps') {
                    timestampFields = `
                        <div class="row g-2 mt-2 timestamp-fields">
                            <div class="col-md-6">
                                <label class="form-label small mb-1">${escapeHtml(cfg.startLabel)}</label>
                                <input type="text" class="form-control form-control-sm entry-start" data-index="${index}"
                                       placeholder="${escapeHtml(cfg.timePlaceholder)}" pattern="^\\d+:[0-5]\\d(:\\d+)?$">
                            </div>
                            <div class="col-md-6">
                                <label class="form-label small mb-1">${escapeHtml(cfg.endLabel)}</label>
                                <input type="text" class="form-control form-control-sm entry-end" data-index="${index}"
                                       placeholder="${escapeHtml(cfg.timePlaceholder)}" pattern="^\\d+:[0-5]\\d(:\\d+)?$">
                            </div>
                        </div>
                    `;
                }
                item.innerHTML = `
                    <div class="media-playlist-entry-title">${index + 1}. ${escapeHtml(entry.title)}${duration}</div>
                    ${timestampFields}
                `;
                container.appendChild(item);
            });
        }

        function showPlaylistContent(data) {
            playlistData = data;
            activatePlaylistMode();
            const titleEl = document.getElementById('playlistTitleText');
            const metaEl = document.getElementById('playlistMeta');
            if (titleEl) titleEl.textContent = data.playlist_title || cfg.playlistSegmentTitle || 'Playlist';
            if (metaEl) {
                metaEl.textContent = cfg.songCountTemplate.replace(
                    '%(count)s',
                    data.entry_count || (data.entries || []).length
                );
            }
            const loading = document.getElementById('playlistLoading');
            const err = document.getElementById('playlistError');
            const content = document.getElementById('playlistContent');
            if (loading) loading.classList.add('d-none');
            if (err) err.classList.add('d-none');
            if (content) content.classList.remove('d-none');
            renderPlaylistEntries();
        }

        async function loadPlaylistInline(url) {
            if (previewInFlight) return;

            let cleaned = normalizeMediaUrl(url);
            if (!cleaned) return;
            if (isPlaylistUrl(cleaned)) {
                cleaned = canonicalizePlaylistUrl(cleaned) || cleaned;
            }

            playlistPreviewUrl = cleaned;
            lastPreviewedUrl = cleaned;
            previewInFlight = true;
            if (playlistUrlInput) playlistUrlInput.value = cleaned;
            if (singleUrlInput) singleUrlInput.value = '';
            showPlaylistLoading();

            try {
                const client = await waitForClient();
                const data = await client.getPlaylistEntries(cleaned);
                showPlaylistContent(data);
            } catch (err) {
                lastPreviewedUrl = '';
                const code = (err && err.message) ? String(err.message) : '';
                if (code === 'not_a_playlist') {
                    activateSingleMode({ keepPlaylistUrl: false });
                    if (singleUrlInput) singleUrlInput.value = cleaned;
                    if (playlistUrlInput) playlistUrlInput.value = '';
                    return;
                }
                showPlaylistError(cfg.previewErrorLabel);
            } finally {
                previewInFlight = false;
            }
        }

        function maybeLoadPlaylistFromUrl(url) {
            let cleaned = normalizeMediaUrl(url);
            if (!cleaned || !isPlaylistUrl(cleaned)) return false;
            cleaned = canonicalizePlaylistUrl(cleaned) || cleaned;
            if (playlistUrlInput) playlistUrlInput.value = cleaned;
            loadPlaylistInline(cleaned);
            return true;
        }

        // Back-compat aliases used elsewhere in this file
        async function openPlaylistPreview(url) {
            return loadPlaylistInline(url);
        }

        function maybeOpenPlaylistFromUrl(url) {
            return maybeLoadPlaylistFromUrl(url);
        }

        function stopProgressAnimation(jobId) {
            const interval = progressIntervals.get(String(jobId));
            if (interval) {
                clearInterval(interval);
                progressIntervals.delete(String(jobId));
            }
        }

        function jobElements(jobId) {
            return document.querySelectorAll(`.media-job[data-job-id="${jobId}"]`);
        }

        function renderProgressBar(el, percent, status) {
            const statusCell = el.querySelector('.job-status-cell');
            if (!statusCell) return;
            const rounded = Math.max(0, Math.min(100, Math.round(percent)));
            let barClass = 'progress-bar';
            if (status === 'failed') {
                barClass += ' bg-danger';
            } else {
                barClass += ' progress-bar-striped progress-bar-animated bg-primary';
            }
            const errorEl = statusCell.querySelector('.job-error');
            const errorHtml = errorEl ? errorEl.outerHTML : '';
            statusCell.innerHTML = `
                <div class="progress media-job-progress job-progress">
                    <div class="${barClass}" role="progressbar" style="width: ${rounded}%">${rounded}%</div>
                </div>
                ${errorHtml}
            `;
        }

        function startProgressAnimation(jobId) {
            const id = String(jobId);
            if (progressIntervals.has(id)) return;

            if (!progressState.has(id)) {
                progressState.set(id, { percent: 5 });
            }

            const interval = setInterval(() => {
                const els = jobElements(id);
                if (!els.length) {
                    stopProgressAnimation(id);
                    return;
                }
                const status = els[0].dataset.status;
                if (status === 'completed' || status === 'failed' || status === 'cancelled') {
                    stopProgressAnimation(id);
                    return;
                }

                const state = progressState.get(id);
                const cap = (status === 'processing' || status === 'converting') ? 92 : 25;
                const increment = (status === 'processing' || status === 'converting')
                    ? (1 + Math.random() * 2)
                    : (0.3 + Math.random() * 0.5);
                state.percent = Math.min(cap, state.percent + increment);
                els.forEach((el) => renderProgressBar(el, state.percent, status));
            }, 400);

            progressIntervals.set(id, interval);
        }

        function setBadgeStatus(jobId, status, errorMessage) {
            stopProgressAnimation(jobId);
            let badgeClass = 'bg-secondary';
            if (status === 'completed') badgeClass = 'bg-success';
            if (status === 'failed') badgeClass = 'bg-danger';
            if (status === 'cancelled') badgeClass = 'bg-secondary';
            if (status === 'cancelling') badgeClass = 'bg-warning text-dark';
            if (status === 'downloading' || status === 'uploading' || status === 'converting') {
                badgeClass = 'bg-primary';
            }

            jobElements(jobId).forEach((el) => {
                el.dataset.status = status;
                const statusCell = el.querySelector('.job-status-cell');
                if (!statusCell) return;
                statusCell.innerHTML = `<span class="badge ${badgeClass}">${cfg.statusLabels[status] || status}</span>`;
                if (errorMessage) {
                    statusCell.innerHTML += `<div class="small text-danger mt-1 job-error">${escapeHtml(errorMessage)}</div>`;
                }
            });
        }

        function setCompletedStatus(jobId) {
            setBadgeStatus(jobId, 'completed');
            progressState.set(String(jobId), { percent: 100 });
        }

        function setFailedStatus(jobId, errorMessage) {
            setBadgeStatus(jobId, 'failed', errorMessage);
        }

        function formatExpires(isoString) {
            if (!isoString) return '–';
            const date = new Date(isoString);
            if (Number.isNaN(date.getTime())) return '–';
            const pad = (n) => n.toString().padStart(2, '0');
            return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
        }

        function ensureJobsVisible() {
            const empty = document.getElementById('jobsEmpty');
            if (empty) empty.classList.add('d-none');

            const listView = document.getElementById('jobsListView');
            const gridView = document.getElementById('jobsGridView');
            const listBtn = document.getElementById('mediaListViewBtn');
            const gridBtn = document.getElementById('mediaGridViewBtn');
            const isGrid = viewMode === 'grid';

            if (listBtn) listBtn.classList.toggle('active', !isGrid);
            if (gridBtn) gridBtn.classList.toggle('active', isGrid);

            if (listView) {
                listView.classList.toggle('d-none', isGrid);
                if (isGrid) {
                    listView.setAttribute('hidden', '');
                    listView.style.display = 'none';
                } else {
                    listView.removeAttribute('hidden');
                    listView.style.display = '';
                }
            }
            if (gridView) {
                gridView.classList.toggle('d-none', !isGrid);
                if (!isGrid) {
                    gridView.setAttribute('hidden', '');
                    gridView.style.display = 'none';
                } else {
                    gridView.removeAttribute('hidden');
                    gridView.style.display = '';
                }
            }
        }

        function titleHtml(job) {
            const title = escapeHtml(job.title || job.source_url || '');
            const segment = (job.start_time && job.end_time)
                ? `<br><small class="text-muted">${escapeHtml(job.start_time)} – ${escapeHtml(job.end_time)}</small>`
                : '';
            return `${title}${segment}`;
        }

        function formatIconClass(format) {
            return format === 'video' ? 'bi-film' : 'bi-music-note-beamed';
        }

        function jobDownloadUrl(jobId) {
            return cfg.downloadUrlTemplate.replace('/0', `/${jobId}`);
        }

        function jobDeleteUrl(jobId) {
            return cfg.deleteUrlTemplate.replace('/0', `/${jobId}`);
        }

        function buildMenuItemsHtml(job, downloadable) {
            const id = job.id;
            const sourceUrl = job.source_url || '';
            const downloadUrl = jobDownloadUrl(id);
            let html = '';
            if (downloadable) {
                html += `<li><a class="dropdown-item" href="${escapeHtml(downloadUrl)}"><i class="bi bi-download me-2"></i>${escapeHtml(cfg.downloadLabel)}</a></li>`;
            }
            if (sourceUrl) {
                html += `<li><a class="dropdown-item" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener"><i class="bi bi-box-arrow-up-right me-2"></i>${escapeHtml(cfg.openSourceLabel)}</a></li>`;
            }
            html += `<li><hr class="dropdown-divider"></li>`;
            html += `<li><button type="button" class="dropdown-item text-danger media-job-delete-btn" data-job-id="${id}"><i class="bi bi-trash me-2"></i>${escapeHtml(cfg.deleteLabel)}</button></li>`;
            return html;
        }

        function buildListActionsHtml(job, downloadable) {
            const id = job.id;
            const downloadUrl = jobDownloadUrl(id);
            const hover = downloadable
                ? `<a class="btn btn-sm btn-link job-download-btn" href="${escapeHtml(downloadUrl)}" title="${escapeHtml(cfg.downloadLabel)}"><i class="bi bi-download"></i></a>`
                : '';
            return `
                <div class="mod-list-actions job-actions-cell">
                    <div class="mod-list-hover-actions">${hover}</div>
                    <div class="dropdown d-inline-block">
                        <button class="btn btn-sm btn-link" type="button" data-bs-toggle="dropdown" data-bs-popper-config='{"strategy":"fixed"}' aria-expanded="false" aria-label="${escapeHtml(cfg.actionsLabel)}">
                            <i class="bi bi-three-dots-vertical"></i>
                        </button>
                        <ul class="dropdown-menu dropdown-menu-end media-job-actions-menu">
                            ${buildMenuItemsHtml(job, downloadable)}
                        </ul>
                    </div>
                </div>
            `;
        }

        function buildGridActionsHtml(job, downloadable) {
            const id = job.id;
            const downloadUrl = jobDownloadUrl(id);
            const hover = downloadable
                ? `<a class="btn btn-sm btn-link job-download-btn" href="${escapeHtml(downloadUrl)}" title="${escapeHtml(cfg.downloadLabel)}"><i class="bi bi-download"></i></a>`
                : '';
            return `
                <div class="media-grid-hover-actions">${hover}</div>
                <div class="dropdown media-job-card-menu">
                    <button class="btn btn-sm btn-link" type="button" data-bs-toggle="dropdown" data-bs-popper-config='{"strategy":"fixed"}' aria-expanded="false" aria-label="${escapeHtml(cfg.actionsLabel)}">
                        <i class="bi bi-three-dots-vertical"></i>
                    </button>
                    <ul class="dropdown-menu dropdown-menu-end media-job-actions-menu">
                        ${buildMenuItemsHtml(job, downloadable)}
                    </ul>
                </div>
            `;
        }

        function createJobElements(job) {
            const tbody = document.getElementById('jobsTableBody');
            const grid = document.getElementById('jobsGrid');
            if (!tbody || !grid) return;

            const formatLabel = cfg.formatLabels[job.format] || job.format;
            const expires = formatExpires(job.expires_at);
            const title = titleHtml(job);
            const iconClass = formatIconClass(job.format);
            const downloadable = Boolean(job.downloadable);
            const sourceUrl = job.source_url || '';

            const row = document.createElement('tr');
            row.className = 'mod-list-row media-job';
            row.dataset.jobId = job.id;
            row.dataset.status = job.status;
            row.dataset.format = job.format;
            if (sourceUrl) row.dataset.sourceUrl = sourceUrl;
            row.innerHTML = `
                <td>
                    <div class="d-flex align-items-center gap-2 min-width-0">
                        <span class="media-job-icon flex-shrink-0" aria-hidden="true"><i class="bi ${iconClass}"></i></span>
                        <div class="min-width-0 job-title-cell"><span class="mod-list-name">${title}</span></div>
                    </div>
                </td>
                <td class="job-format-cell d-none d-sm-table-cell">${escapeHtml(formatLabel)}</td>
                <td class="job-status-cell">
                    <div class="progress media-job-progress job-progress">
                        <div class="progress-bar progress-bar-striped progress-bar-animated bg-primary" role="progressbar" style="width: 5%">5%</div>
                    </div>
                </td>
                <td class="job-expires-cell d-none d-md-table-cell">${expires}</td>
                <td class="text-end">${buildListActionsHtml(job, downloadable)}</td>
            `;
            tbody.prepend(row);

            const col = document.createElement('div');
            col.className = 'col-12 col-md-6 col-lg-4 media-job-col';
            col.dataset.jobId = job.id;
            col.innerHTML = `
                <article class="card h-100 media-job-card media-job" data-job-id="${job.id}" data-status="${escapeHtml(job.status)}" data-format="${escapeHtml(job.format || '')}"${sourceUrl ? ` data-source-url="${escapeHtml(sourceUrl)}"` : ''}>
                    <div class="card-body d-flex flex-column">
                        <div class="d-flex align-items-start justify-content-between gap-2 mb-2">
                            <div class="media-job-card-preview flex-shrink-0" aria-hidden="true"><i class="bi ${iconClass}"></i></div>
                            <div class="d-flex align-items-start gap-1 media-job-card-actions-wrap job-actions-cell">
                                ${buildGridActionsHtml(job, downloadable)}
                            </div>
                        </div>
                        <h5 class="card-title media-job-card-title job-title-cell mb-2">${title}</h5>
                        <div class="media-job-card-meta mb-2">
                            <span class="job-format-cell">${escapeHtml(formatLabel)}</span>
                            <span class="job-expires-cell">${expires}</span>
                        </div>
                        <div class="media-job-card-status job-status-cell mt-auto">
                            <div class="progress media-job-progress job-progress">
                                <div class="progress-bar progress-bar-striped progress-bar-animated bg-primary" role="progressbar" style="width: 5%">5%</div>
                            </div>
                        </div>
                    </div>
                </article>
            `;
            grid.prepend(col);

            startProgressAnimation(job.id);
            pollJob(job.id);
            enqueueClientJob(job);
            updateJobsBadge();
        }

        async function startSingleDownload() {
            let url = normalizeMediaUrl(singleUrlInput ? singleUrlInput.value : '');
            if (!url) {
                if (singleUrlInput) singleUrlInput.focus();
                return false;
            }

            if (isPlaylistUrl(url)) {
                url = canonicalizePlaylistUrl(url) || url;
                if (playlistUrlInput) playlistUrlInput.value = url;
                if (singleUrlInput) singleUrlInput.value = '';
                setSubmitBusy(true);
                try {
                    await loadPlaylistInline(url);
                } finally {
                    setSubmitBusy(false);
                }
                return false;
            }

            const format = getSelectedFormat();
            const startTime = (document.getElementById('start_time')?.value || '').trim();
            const endTime = (document.getElementById('end_time')?.value || '').trim();

            setSubmitBusy(true);
            try {
                const response = await fetch(cfg.jobsUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        source_url: url,
                        format,
                        start_time: startTime,
                        end_time: endTime,
                    }),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    if (typeof window.showAppBanner === 'function') {
                        window.showAppBanner(data.error || cfg.previewErrorLabel, 'danger');
                    }
                    return false;
                }

                if (singleUrlInput) singleUrlInput.value = '';
                activateSingleMode();
                createJobElements(data);
                ensureJobsVisible();
                switchMediaTab('jobs');
                return true;
            } catch (err) {
                if (typeof window.showAppBanner === 'function') {
                    window.showAppBanner(cfg.previewErrorLabel, 'danger');
                }
                return false;
            } finally {
                setSubmitBusy(false);
            }
        }

        function updateJobTitle(jobId, data) {
            const html = titleHtml(data);
            jobElements(jobId).forEach((el) => {
                const titleCell = el.querySelector('.job-title-cell');
                if (!titleCell) return;
                if (titleCell.querySelector('.mod-list-name')) {
                    titleCell.querySelector('.mod-list-name').innerHTML = html;
                } else {
                    titleCell.innerHTML = html;
                }
            });
        }

        function updateJobExpires(jobId, iso) {
            const text = formatExpires(iso);
            jobElements(jobId).forEach((el) => {
                el.querySelectorAll('.job-expires-cell').forEach((cell) => {
                    cell.textContent = text;
                });
            });
        }

        function updateJobActions(jobId, downloadable, jobData) {
            const sourceUrl = (jobData && jobData.source_url)
                || (jobElements(jobId)[0] && jobElements(jobId)[0].dataset.sourceUrl)
                || '';
            const job = {
                id: jobId,
                source_url: sourceUrl,
            };
            jobElements(jobId).forEach((el) => {
                if (el.tagName === 'TR') {
                    const cell = el.querySelector('td.text-end');
                    if (cell) cell.innerHTML = buildListActionsHtml(job, downloadable);
                    return;
                }
                const wrap = el.querySelector('.media-job-card-actions-wrap, .job-actions-cell');
                if (wrap) wrap.innerHTML = buildGridActionsHtml(job, downloadable);
            });
        }

        function removeJobElements(jobId) {
            stopProgressAnimation(jobId);
            document.querySelectorAll(`.media-job[data-job-id="${jobId}"]`).forEach((el) => {
                if (el.tagName === 'TR') {
                    el.remove();
                } else {
                    const col = el.closest('.media-job-col');
                    if (col) col.remove();
                    else el.remove();
                }
            });
            document.querySelectorAll(`.media-job-col[data-job-id="${jobId}"]`).forEach((col) => col.remove());
            updateJobsBadge();
            if (!document.querySelectorAll('.media-job').length) {
                const empty = document.getElementById('jobsEmpty');
                if (empty) empty.classList.remove('d-none');
                applyViewMode(viewMode);
            }
        }

        async function portalConfirm(message, options) {
            if (typeof window.ptConfirm === 'function') {
                return window.ptConfirm(String(message || ''), options || {});
            }
            return window.confirm(String(message || ''));
        }

        async function deleteJob(jobId) {
            if (!cfg.deleteUrlTemplate) return;
            const abort = clientAbortControllers.get(String(jobId));
            if (abort) abort.abort();

            const ok = await portalConfirm(cfg.deleteConfirm || cfg.clearAllConfirm, {
                danger: true,
                confirmLabel: cfg.deleteLabel || undefined,
            });
            if (!ok) return;

            try {
                const response = await fetch(jobDeleteUrl(jobId), { method: 'POST' });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) return;
                if (data.cancelling) {
                    setBadgeStatus(jobId, 'cancelling');
                    pollJob(jobId);
                    updateJobsBadge();
                    // Nach kurzer Zeit endgültig aus Liste nehmen (Backend purged parallel)
                    setTimeout(() => {
                        const el = document.querySelector(`.media-job[data-job-id="${jobId}"]`);
                        if (!el) return;
                        if (el.dataset.status === 'cancelling' || el.dataset.status === 'cancelled') {
                            fetch(`${jobDeleteUrl(jobId)}?force=1`, { method: 'POST' }).finally(() => {
                                removeJobElements(jobId);
                            });
                        }
                    }, 8000);
                    return;
                }
                removeJobElements(jobId);
            } catch (err) {
                // ignore
            }
        }

        function pollJob(jobId) {
            const id = String(jobId);
            fetch(cfg.statusUrlTemplate.replace('/0', `/${id}`))
                .then((response) => {
                    if (response.status === 404) {
                        removeJobElements(id);
                        return null;
                    }
                    return response.json();
                })
                .then((data) => {
                    if (!data) return;
                    const els = jobElements(id);
                    if (!els.length) return;

                    const previousStatus = els[0].dataset.status;
                    const previousRank = statusRank[previousStatus] || 0;
                    const incomingRank = statusRank[data.status] || 0;
                    if (previousRank > incomingRank) {
                        if (ACTIVE_JOB_STATUSES.has(previousStatus)) {
                            setTimeout(() => pollJob(id), 2500);
                        }
                        return;
                    }

                    els.forEach((el) => {
                        el.dataset.status = data.status;
                    });

                    if (data.title) {
                        updateJobTitle(id, data);
                    }

                    if (typeof data.progress === 'number' && ACTIVE_JOB_STATUSES.has(data.status)) {
                        stopProgressAnimation(id);
                        setJobProgressUi(id, data.progress, data.status);
                    }

                    if (data.status === 'completed') {
                        setCompletedStatus(id);
                    } else if (data.status === 'failed') {
                        setFailedStatus(id, data.error_message);
                        const wasActive = ACTIVE_JOB_STATUSES.has(previousStatus);
                        if (wasActive && data.error_message && typeof window.showAppBanner === 'function') {
                            window.showAppBanner(data.error_message, 'danger', {
                                timeout: 12000,
                                title: cfg.statusLabels.failed || '',
                            });
                        }
                    } else if (data.status === 'cancelled') {
                        removeJobElements(id);
                        return;
                    } else if (data.status === 'cancelling') {
                        setBadgeStatus(id, data.status, data.error_message);
                    } else if (data.status === 'converting') {
                        stopProgressAnimation(id);
                        const state = progressState.get(id) || { percent: 90 };
                        state.percent = Math.max(state.percent, 90);
                        progressState.set(id, state);
                        els.forEach((el) => renderProgressBar(el, state.percent, data.status));
                        startProgressAnimation(id);
                    } else if (data.status === 'downloading' || data.status === 'uploading') {
                        if (typeof data.progress === 'number') {
                            setJobProgressUi(id, data.progress, data.status);
                        }
                    } else if (previousStatus !== data.status && data.status === 'processing') {
                        const state = progressState.get(id) || { percent: 5 };
                        state.percent = Math.max(state.percent, 25);
                        progressState.set(id, state);
                        els.forEach((el) => renderProgressBar(el, state.percent, data.status));
                        startProgressAnimation(id);
                    }

                    if (data.expires_at) {
                        updateJobExpires(id, data.expires_at);
                    }

                    updateJobActions(id, data.downloadable, data);
                    updateJobsBadge();

                    if (ACTIVE_JOB_STATUSES.has(data.status)) {
                        setTimeout(() => pollJob(id), 2500);
                    }
                })
                .catch(() => setTimeout(() => pollJob(id), 5000));
        }

        async function downloadPlaylistBatch() {
            if (!playlistData || !playlistData.entries || !playlistData.entries.length) return false;

            const mode = document.querySelector('input[name="playlist_mode"]:checked')?.value || 'complete';
            const format = getSelectedFormat();
            const items = playlistData.entries.map((entry, index) => {
                const item = {
                    source_url: entry.url,
                    title: entry.title,
                };
                if (mode === 'timestamps') {
                    const startInput = document.querySelector(`.entry-start[data-index="${index}"]`);
                    const endInput = document.querySelector(`.entry-end[data-index="${index}"]`);
                    item.start_time = startInput ? startInput.value.trim() : '';
                    item.end_time = endInput ? endInput.value.trim() : '';
                }
                return item;
            });

            setSubmitBusy(true);

            try {
                const response = await fetch(cfg.batchUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ format, items }),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    showPlaylistError(data.error || cfg.previewErrorLabel);
                    setSubmitBusy(false);
                    return false;
                }

                if (playlistUrlInput) playlistUrlInput.value = '';
                if (singleUrlInput) singleUrlInput.value = '';
                resetPlaylistPanel();
                activateSingleMode();
                (data.jobs || []).forEach((job) => {
                    createJobElements(job);
                });
                ensureJobsVisible();
                switchMediaTab('jobs');
                setSubmitBusy(false);
                return true;
            } catch (err) {
                showPlaylistError(cfg.previewErrorLabel);
                setSubmitBusy(false);
                return false;
            }
        }

        function setSubmitBusy(busy) {
            if (!submitBtn) return;
            submitBtn.disabled = busy;
            if (busy) {
                submitBtn.dataset.originalHtml = submitBtn.innerHTML;
                submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span>';
            } else if (submitBtn.dataset.originalHtml) {
                submitBtn.innerHTML = submitBtn.dataset.originalHtml;
                // re-bind label span after restore
            }
        }

        function hideSearchResults() {
            if (!searchResultsEl) return;
            searchResultsEl.classList.add('d-none');
            searchResultsEl.setAttribute('hidden', '');
            searchResultsEl.innerHTML = '';
            if (searchInput) searchInput.setAttribute('aria-expanded', 'false');
        }

        function showSearchResults(html) {
            if (!searchResultsEl) return;
            searchResultsEl.innerHTML = html;
            searchResultsEl.classList.remove('d-none');
            searchResultsEl.removeAttribute('hidden');
            if (searchInput) searchInput.setAttribute('aria-expanded', 'true');
        }

        function selectSearchResult(track) {
            if (!track || !track.url) return;
            hideSearchResults();
            if (searchInput) searchInput.value = '';
            const audio = document.getElementById('format_audio');
            if (audio) audio.checked = true;

            if (isPlaylistUrl(track.url)) {
                maybeLoadPlaylistFromUrl(track.url);
                if (playlistUrlInput) playlistUrlInput.focus();
                return;
            }

            activateSingleMode();
            if (singleUrlInput) {
                singleUrlInput.value = normalizeMediaUrl(track.url);
                singleUrlInput.focus();
            }
        }

        async function runYoutubeSearch(query) {
            if (!cfg.youtubeSearchEnabled || !cfg.youtubeSearchUrl) return;
            const q = (query || '').trim();
            if (q.length < 2) {
                hideSearchResults();
                return;
            }

            if (searchAbort) searchAbort.abort();
            searchAbort = new AbortController();
            showSearchResults(`<div class="media-search-loading">${escapeHtml(cfg.searchLoading)}</div>`);

            try {
                const response = await fetch(cfg.youtubeSearchUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query: q, limit: 8 }),
                    signal: searchAbort.signal,
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    showSearchResults(`<div class="media-search-error">${escapeHtml(data.error || cfg.searchError)}</div>`);
                    return;
                }
                const results = data.results || [];
                if (!results.length) {
                    showSearchResults(`<div class="media-search-empty">${escapeHtml(cfg.searchEmpty)}</div>`);
                    return;
                }
                const html = results.map((track, idx) => {
                    const thumb = track.image_url
                        ? `<img class="media-search-thumb" src="${escapeHtml(track.image_url)}" alt="">`
                        : `<div class="media-search-thumb d-flex align-items-center justify-content-center"><i class="bi bi-music-note"></i></div>`;
                    return `
                        <button type="button" class="media-search-result" data-search-index="${idx}" role="option">
                            ${thumb}
                            <span class="media-search-meta">
                                <span class="media-search-title">${escapeHtml(track.title || '')}</span>
                                <span class="media-search-artist">${escapeHtml(track.artist || '')}</span>
                            </span>
                        </button>
                    `;
                }).join('');
                showSearchResults(html);
                searchResultsEl.querySelectorAll('.media-search-result').forEach((btn) => {
                    btn.addEventListener('click', () => {
                        const index = Number(btn.dataset.searchIndex);
                        selectSearchResult(results[index]);
                    });
                });
            } catch (err) {
                if (err.name === 'AbortError') return;
                showSearchResults(`<div class="media-search-error">${escapeHtml(cfg.searchError)}</div>`);
            }
        }

        // —— Bindings ——
        if (downloadForm) {
            downloadForm.addEventListener('submit', (event) => {
                // Playlist mode → batch API
                if (inputMode === 'playlist' || (playlistData && playlistData.entries && playlistData.entries.length)) {
                    event.preventDefault();
                    event.stopPropagation();
                    if (!playlistData || !playlistData.entries || !playlistData.entries.length) {
                        const plUrl = normalizeMediaUrl(playlistUrlInput ? playlistUrlInput.value : '');
                        if (plUrl) {
                            setSubmitBusy(true);
                            loadPlaylistInline(plUrl).finally(() => setSubmitBusy(false));
                        }
                        return false;
                    }
                    downloadPlaylistBatch();
                    return false;
                }

                // Single mode
                let url = normalizeMediaUrl(singleUrlInput ? singleUrlInput.value : '');
                if (!url) {
                    event.preventDefault();
                    if (singleUrlInput) singleUrlInput.focus();
                    return false;
                }

                // Playlist URL accidentally in single field → move to playlist flow
                if (isPlaylistUrl(url)) {
                    event.preventDefault();
                    event.stopPropagation();
                    url = canonicalizePlaylistUrl(url) || url;
                    if (playlistUrlInput) playlistUrlInput.value = url;
                    if (singleUrlInput) singleUrlInput.value = '';
                    setSubmitBusy(true);
                    loadPlaylistInline(url).finally(() => setSubmitBusy(false));
                    return false;
                }

                if (singleUrlInput) singleUrlInput.value = url;
                event.preventDefault();
                startSingleDownload();
                return false;
            });
        }

        if (singleUrlInput) {
            singleUrlInput.addEventListener('focus', () => {
                if (playlistUrlInput && playlistUrlInput.value.trim()) {
                    // Keep playlist data until they type something in single
                }
            });

            singleUrlInput.addEventListener('paste', (event) => {
                const text = (event.clipboardData || window.clipboardData)?.getData('text') || '';
                let url = normalizeMediaUrl(text);
                if (!url) return;
                event.preventDefault();
                if (isPlaylistUrl(url)) {
                    url = canonicalizePlaylistUrl(url) || url;
                    if (playlistUrlInput) playlistUrlInput.value = url;
                    singleUrlInput.value = '';
                    lastPreviewedUrl = '';
                    maybeLoadPlaylistFromUrl(url);
                    return;
                }
                activateSingleMode();
                singleUrlInput.value = url;
            });

            let singleDebounce = null;
            singleUrlInput.addEventListener('input', () => {
                clearTimeout(singleDebounce);
                singleDebounce = setTimeout(() => {
                    let url = normalizeMediaUrl(singleUrlInput.value);
                    if (!singleUrlInput.value.trim()) {
                        return;
                    }
                    if (url && url !== singleUrlInput.value.trim()) singleUrlInput.value = url;
                    if (isPlaylistUrl(url)) {
                        url = canonicalizePlaylistUrl(url) || url;
                        if (playlistUrlInput) playlistUrlInput.value = url;
                        singleUrlInput.value = '';
                        maybeLoadPlaylistFromUrl(url);
                        return;
                    }
                    // Switching to single clears playlist state
                    if (playlistUrlInput && playlistUrlInput.value.trim()) {
                        playlistUrlInput.value = '';
                    }
                    resetPlaylistPanel();
                    activateSingleMode({ keepPlaylistUrl: true });
                }, 350);
            });
        }

        if (playlistUrlInput) {
            playlistUrlInput.addEventListener('paste', (event) => {
                const text = (event.clipboardData || window.clipboardData)?.getData('text') || '';
                let url = normalizeMediaUrl(text);
                if (!url) return;
                event.preventDefault();
                if (!isPlaylistUrl(url)) {
                    // Non-playlist → put in single field
                    activateSingleMode();
                    if (singleUrlInput) singleUrlInput.value = url;
                    playlistUrlInput.value = '';
                    return;
                }
                url = canonicalizePlaylistUrl(url) || url;
                playlistUrlInput.value = url;
                lastPreviewedUrl = '';
                maybeLoadPlaylistFromUrl(url);
            });

            let playlistDebounce = null;
            const triggerPlaylistLoad = () => {
                let url = normalizeMediaUrl(playlistUrlInput.value);
                if (!url) {
                    resetPlaylistPanel();
                    activateSingleMode({ keepPlaylistUrl: true });
                    return;
                }
                if (url !== playlistUrlInput.value.trim()) playlistUrlInput.value = url;
                if (!isPlaylistUrl(url)) {
                    showPlaylistError(cfg.previewErrorLabel);
                    return;
                }
                url = canonicalizePlaylistUrl(url) || url;
                playlistUrlInput.value = url;
                if (url !== lastPreviewedUrl && !previewInFlight) {
                    maybeLoadPlaylistFromUrl(url);
                }
            };

            playlistUrlInput.addEventListener('input', () => {
                clearTimeout(playlistDebounce);
                playlistDebounce = setTimeout(triggerPlaylistLoad, 450);
            });

            playlistUrlInput.addEventListener('blur', triggerPlaylistLoad);
            playlistUrlInput.addEventListener('change', () => {
                lastPreviewedUrl = '';
                triggerPlaylistLoad();
            });
        }

        document.querySelectorAll('input[name="playlist_mode"]').forEach((input) => {
            input.addEventListener('change', () => {
                if (playlistData) renderPlaylistEntries();
            });
        });

        document.querySelectorAll('.media-clear-all-btn').forEach((clearBtn) => {
            clearBtn.addEventListener('click', async () => {
                const ok = await portalConfirm(cfg.clearAllConfirm, {
                    danger: true,
                    confirmLabel: cfg.deleteLabel || undefined,
                });
                if (!ok) return;
                document.querySelectorAll('.media-clear-all-btn').forEach((btn) => { btn.disabled = true; });
                try {
                    const response = await fetch(cfg.clearAllUrl, { method: 'POST' });
                    if (response.ok) {
                        window.location.reload();
                        return;
                    }
                } catch (error) {
                    // re-enable below
                }
                document.querySelectorAll('.media-clear-all-btn').forEach((btn) => { btn.disabled = false; });
            });
        });

        root.addEventListener('click', (event) => {
            const deleteBtn = event.target.closest('.media-job-delete-btn');
            if (!deleteBtn) return;
            event.preventDefault();
            event.stopPropagation();
            const jobId = deleteBtn.getAttribute('data-job-id');
            if (jobId) deleteJob(jobId);
        });

        document.querySelectorAll('[data-media-tab]').forEach((button) => {
            button.addEventListener('click', function () {
                const tab = this.getAttribute('data-media-tab');
                if (tab) switchMediaTab(tab);
                if (this.hasAttribute('data-media-dismiss-offcanvas')) {
                    dismissMediaOffcanvas();
                }
            });
        });

        document.querySelectorAll('[data-media-dismiss-offcanvas]').forEach((el) => {
            if (el.hasAttribute('data-media-tab')) return;
            el.addEventListener('click', dismissMediaOffcanvas);
        });

        document.querySelectorAll('[data-media-view]').forEach((btn) => {
            btn.addEventListener('click', () => {
                applyViewMode(btn.getAttribute('data-media-view'));
            });
        });

        // no modal — playlist UI lives in segment card

        if (searchInput) {
            searchInput.addEventListener('input', () => {
                if (!cfg.youtubeSearchEnabled) return;
                clearTimeout(searchTimer);
                searchTimer = setTimeout(() => runYoutubeSearch(searchInput.value), 350);
            });
            searchInput.addEventListener('keydown', (event) => {
                if (event.key === 'Escape') {
                    hideSearchResults();
                    return;
                }
                if (event.key === 'Enter') {
                    const first = searchResultsEl && searchResultsEl.querySelector('.media-search-result');
                    if (first && !searchResultsEl.classList.contains('d-none')) {
                        event.preventDefault();
                        first.click();
                    }
                }
            });
            searchInput.addEventListener('focus', () => {
                if (!cfg.youtubeSearchEnabled) return;
                if ((searchInput.value || '').trim().length >= 2) {
                    runYoutubeSearch(searchInput.value);
                }
            });
            document.addEventListener('click', (event) => {
                if (!event.target.closest('.media-search-wrap')) {
                    hideSearchResults();
                }
            });
        }

        waitForClient().then(() => configureClient()).catch(() => {});
        window.addEventListener('media-downloader-client-ready', () => configureClient());
        window.addEventListener('media-downloader-client-error', () => {
            showYoutubeAuthError(cfg.i18nYoutubeAuthUnavailable || 'YouTube-Anmeldung ist noch nicht bereit.');
        });

        const seenPoll = new Set();
        document.querySelectorAll('.media-job').forEach((el) => {
            const id = el.dataset.jobId;
            if (seenPoll.has(id)) return;
            seenPoll.add(id);
            if (el.dataset.status === 'pending' || el.dataset.status === 'processing'
                || el.dataset.status === 'downloading' || el.dataset.status === 'uploading'
                || el.dataset.status === 'converting' || el.dataset.status === 'cancelling') {
                if (el.dataset.status === 'downloading' || el.dataset.status === 'uploading') {
                    enqueueClientJob({
                        id: Number(id),
                        status: el.dataset.status,
                        source_url: el.dataset.sourceUrl,
                        format: el.dataset.format,
                    });
                } else {
                    startProgressAnimation(id);
                }
                pollJob(id);
            }
        });

        applyViewMode(viewMode);
        updateJobsBadge();
        setInputMode('single');

        if (window.location.hash === '#jobs') {
            switchMediaTab('jobs');
        }

        const pendingPlaylist = canonicalizePlaylistUrl(
            normalizeMediaUrl(root.dataset.pendingPlaylistUrl || '')
        );
        if (pendingPlaylist && isPlaylistUrl(pendingPlaylist)) {
            switchMediaTab('download');
            if (playlistUrlInput) playlistUrlInput.value = pendingPlaylist;
            if (singleUrlInput) singleUrlInput.value = '';
            try {
                const cleanUrl = new URL(window.location.href);
                cleanUrl.searchParams.delete('playlist_url');
                window.history.replaceState({}, '', cleanUrl.pathname + cleanUrl.search + cleanUrl.hash);
            } catch (e) {
                // ignore
            }
            setTimeout(() => loadPlaylistInline(pendingPlaylist), 150);
        }
    }
})();
