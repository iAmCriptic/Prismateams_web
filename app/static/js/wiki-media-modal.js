/**
 * Wiki Media Modal & Embed Support:
 * - Dialog for uploading photos/videos and embedding YouTube/Vimeo/direct video links
 * - Drag & Drop media upload directly onto the markdown editor
 * - Clipboard paste upload (e.g. screenshots)
 * - Live Markdown preview modal
 */
(function (window) {
    'use strict';

    let activeEditor = null;
    let savedSelection = null;

    function getEditor() {
        if (window.MarkdownToolbar && typeof window.MarkdownToolbar.getEditor === 'function') {
            const ed = window.MarkdownToolbar.getEditor();
            if (ed) return ed;
        }
        if (window.MarkdownTableEditor) {
            const ed = window.MarkdownTableEditor.getActiveTextarea('wikiEditor') ||
                       window.MarkdownTableEditor.getActiveTextarea('markdownEditor');
            if (ed) return ed;
        }
        if (activeEditor && document.body.contains(activeEditor)) return activeEditor;
        return document.getElementById('wikiEditor') || document.getElementById('markdownEditor');
    }

    function insertAtCursor(target, text) {
        const editor = target || getEditor();
        if (!editor) return;

        // Wenn aktives Ziel eine MarkdownTableEditor-Zelle ist
        if (typeof editor.setText === 'function' && typeof editor.getText === 'function') {
            editor.setText(text);
            return;
        }

        editor.focus();
        let start = typeof editor.selectionStart === 'number' ? editor.selectionStart : editor.value.length;
        let end = typeof editor.selectionEnd === 'number' ? editor.selectionEnd : start;

        // Gespeicherte Selektion wiederherstellen, falls aktiv
        if (savedSelection && target === activeEditor) {
            start = savedSelection.start;
            end = savedSelection.end;
            savedSelection = null;
        }

        const before = editor.value.substring(0, start);
        const after = editor.value.substring(end);

        // Füge bei Bedarf neue Zeilen hinzu
        const needsNewlineBefore = before.length > 0 && !before.endsWith('\n');
        const needsNewlineAfter = after.length > 0 && !after.startsWith('\n');
        const insertText = (needsNewlineBefore ? '\n' : '') + text + (needsNewlineAfter ? '\n' : '');

        editor.value = before + insertText + after;
        const newPos = start + insertText.length;
        editor.selectionStart = newPos;
        editor.selectionEnd = newPos;

        // Triggere Input-Event für Autosave / Dirty Check / MarkdownTableEditor
        editor.dispatchEvent(new Event('input', { bubbles: true }));

        // Visuellen Editor synchronisieren
        if (window.MarkdownToolbar && typeof window.MarkdownToolbar.syncVisual === 'function') {
            window.MarkdownToolbar.syncVisual();
        } else if (window.MarkdownTableEditor) {
            window.MarkdownTableEditor.sync('wikiEditor');
            window.MarkdownTableEditor.sync('markdownEditor');
        }
    }

    function createMediaModal() {
        let modalEl = document.getElementById('wikiMediaModal');
        if (modalEl) return modalEl;

        modalEl = document.createElement('div');
        modalEl.id = 'wikiMediaModal';
        modalEl.className = 'modal fade';
        modalEl.setAttribute('tabindex', '-1');
        modalEl.setAttribute('aria-hidden', 'true');

        modalEl.innerHTML = `
            <div class="modal-dialog modal-dialog-centered modal-lg">
                <div class="modal-content mod-card">
                    <div class="modal-header border-bottom">
                        <h5 class="modal-title d-flex align-items-center gap-2">
                            <i class="bi bi-collection-play text-primary"></i>
                            <span id="wikiMediaModalTitle">Foto oder Video hinzufügen</span>
                        </h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Schließen"></button>
                    </div>
                    <div class="modal-body p-4">
                        <ul class="nav nav-pills nav-fill mb-3" id="wikiMediaTabs" role="tablist">
                            <li class="nav-item" role="presentation">
                                <button class="nav-link active" id="wiki-tab-upload" data-bs-toggle="pill" data-bs-target="#wiki-pane-upload" type="button" role="tab">
                                    <i class="bi bi-cloud-arrow-up me-1"></i> Datei hochladen
                                </button>
                            </li>
                            <li class="nav-item" role="presentation">
                                <button class="nav-link" id="wiki-tab-video" data-bs-toggle="pill" data-bs-target="#wiki-pane-video" type="button" role="tab">
                                    <i class="bi bi-camera-video me-1"></i> Video einbetten (URL)
                                </button>
                            </li>
                            <li class="nav-item" role="presentation">
                                <button class="nav-link" id="wiki-tab-image" data-bs-toggle="pill" data-bs-target="#wiki-pane-image" type="button" role="tab">
                                    <i class="bi bi-image me-1"></i> Bild-Link (URL)
                                </button>
                            </li>
                        </ul>

                        <div class="tab-content" id="wikiMediaTabContent">
                            <!-- TAB 1: UPLOAD (Fotos & Videos) -->
                            <div class="tab-pane fade show active" id="wiki-pane-upload" role="tabpanel">
                                <div class="wiki-upload-dropzone p-4 text-center border rounded-3 mb-3" id="wikiUploadDropzone">
                                    <i class="bi bi-cloud-arrow-up display-5 text-primary mb-2 d-block"></i>
                                    <h6 id="wikiUploadDropzoneTitle">Datei hierher ziehen</h6>
                                    <p class="text-muted small mb-2" id="wikiUploadDropzoneDesc">Unterstützt: MP4, WebM, OGG, MOV sowie JPEG, PNG, GIF, WebP, SVG</p>
                                    <label class="btn btn-outline-primary mod-pill-btn btn-sm">
                                        <i class="bi bi-folder2-open me-1"></i> Datei auswählen
                                        <input type="file" id="wikiMediaFileInput" class="d-none" accept="image/*,video/*">
                                    </label>
                                    <div id="wikiUploadFileDetails" class="mt-2 text-primary small fw-semibold" style="display:none;"></div>
                                </div>
                                <div class="progress mb-3 d-none" id="wikiUploadProgress" style="height: 6px;">
                                    <div class="progress-bar progress-bar-striped progress-bar-animated" role="progressbar" style="width: 0%"></div>
                                </div>
                                <div id="wikiUploadAlert" class="alert alert-danger py-2 d-none"></div>
                                <div class="text-end">
                                    <button type="button" class="btn btn-outline-secondary mod-pill-btn" data-bs-dismiss="modal">Abbrechen</button>
                                    <button type="button" class="btn btn-accent mod-pill-btn ms-2" id="wikiUploadSubmitBtn" disabled>
                                        <i class="bi bi-upload me-1"></i> Hochladen & Einfügen
                                    </button>
                                </div>
                            </div>

                            <!-- TAB 2: VIDEO EMBED -->
                            <div class="tab-pane fade" id="wiki-pane-video" role="tabpanel">
                                <div class="mb-3">
                                    <label for="wikiVideoUrlInput" class="form-label small fw-semibold">Video-Link / URL</label>
                                    <input type="url" class="form-control" id="wikiVideoUrlInput" placeholder="https://www.youtube.com/watch?v=... oder https://vimeo.com/... oder .mp4">
                                    <div class="form-text small">
                                        Unterstützt YouTube, Vimeo oder direkte Video-Dateien (.mp4, .webm).
                                    </div>
                                </div>
                                <div class="mb-3">
                                    <label for="wikiVideoCaptionInput" class="form-label small fw-semibold">Titel / Beschriftung (optional)</label>
                                    <input type="text" class="form-control" id="wikiVideoCaptionInput" placeholder="Z. B. Produkt-Demo oder Tutorial">
                                </div>
                                <div class="text-end">
                                    <button type="button" class="btn btn-outline-secondary mod-pill-btn" data-bs-dismiss="modal">Abbrechen</button>
                                    <button type="button" class="btn btn-accent mod-pill-btn ms-2" id="wikiVideoEmbedSubmitBtn">
                                        <i class="bi bi-plus-lg me-1"></i> Video einfügen
                                    </button>
                                </div>
                            </div>

                            <!-- TAB 3: IMAGE LINK -->
                            <div class="tab-pane fade" id="wiki-pane-image" role="tabpanel">
                                <div class="mb-3">
                                    <label for="wikiImageUrlInput" class="form-label small fw-semibold">Bild-URL</label>
                                    <input type="url" class="form-control" id="wikiImageUrlInput" placeholder="https://example.com/bild.jpg">
                                </div>
                                <div class="mb-3">
                                    <label for="wikiImageAltInput" class="form-label small fw-semibold">Beschreibung (Alt-Text)</label>
                                    <input type="text" class="form-control" id="wikiImageAltInput" placeholder="Beschreibung des Bildes">
                                </div>
                                <div class="text-end">
                                    <button type="button" class="btn btn-outline-secondary mod-pill-btn" data-bs-dismiss="modal">Abbrechen</button>
                                    <button type="button" class="btn btn-accent mod-pill-btn ms-2" id="wikiImageLinkSubmitBtn">
                                        <i class="bi bi-plus-lg me-1"></i> Bild einfügen
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(modalEl);

        // Events im Modal
        const fileInput = modalEl.querySelector('#wikiMediaFileInput');
        const fileDetails = modalEl.querySelector('#wikiUploadFileDetails');
        const uploadBtn = modalEl.querySelector('#wikiUploadSubmitBtn');
        const dropzone = modalEl.querySelector('#wikiUploadDropzone');
        const alertBox = modalEl.querySelector('#wikiUploadAlert');
        const progressBar = modalEl.querySelector('#wikiUploadProgress');
        const progressBarInner = progressBar.querySelector('.progress-bar');

        let selectedFile = null;

        function setFile(file) {
            selectedFile = file;
            if (file) {
                fileDetails.textContent = `${file.name} (${formatBytes(file.size)})`;
                fileDetails.style.display = 'block';
                uploadBtn.disabled = false;
                alertBox.classList.add('d-none');
            } else {
                fileDetails.style.display = 'none';
                uploadBtn.disabled = true;
            }
        }

        fileInput.addEventListener('change', function () {
            if (fileInput.files && fileInput.files[0]) {
                setFile(fileInput.files[0]);
            }
        });

        dropzone.addEventListener('dragover', function (e) {
            e.preventDefault();
            dropzone.classList.add('border-primary', 'bg-light');
        });
        dropzone.addEventListener('dragleave', function (e) {
            e.preventDefault();
            dropzone.classList.remove('border-primary', 'bg-light');
        });
        dropzone.addEventListener('drop', function (e) {
            e.preventDefault();
            dropzone.classList.remove('border-primary', 'bg-light');
            if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                setFile(e.dataTransfer.files[0]);
            }
        });

        uploadBtn.addEventListener('click', function () {
            if (!selectedFile) return;

            uploadBtn.disabled = true;
            uploadBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span> Lade hoch...';
            progressBar.classList.remove('d-none');
            progressBarInner.style.width = '60%';

            uploadMediaFile(selectedFile)
                .then(function (data) {
                    progressBarInner.style.width = '100%';
                    const editor = getEditor();
                    insertAtCursor(editor, data.markdown);
                    bootstrap.Modal.getInstance(modalEl).hide();
                    setFile(null);
                    fileInput.value = '';
                })
                .catch(function (err) {
                    alertBox.textContent = err.message || 'Fehler beim Hochladen.';
                    alertBox.classList.remove('d-none');
                })
                .finally(function () {
                    uploadBtn.disabled = false;
                    uploadBtn.innerHTML = '<i class="bi bi-upload me-1"></i> Hochladen & Einfügen';
                    setTimeout(function () {
                        progressBar.classList.add('d-none');
                        progressBarInner.style.width = '0%';
                    }, 500);
                });
        });

        // Tab 2: Video Embed Submit
        const videoSubmitBtn = modalEl.querySelector('#wikiVideoEmbedSubmitBtn');
        const videoUrlInput = modalEl.querySelector('#wikiVideoUrlInput');
        const videoCaptionInput = modalEl.querySelector('#wikiVideoCaptionInput');

        videoSubmitBtn.addEventListener('click', function () {
            const url = videoUrlInput.value.trim();
            const caption = videoCaptionInput.value.trim();
            if (!url) {
                videoUrlInput.focus();
                return;
            }

            let md = '';
            if (url.includes('youtube.com') || url.includes('youtu.be') || url.includes('vimeo.com')) {
                md = `![${caption || 'Video'}](${url})`;
            } else if (/\.(mp4|webm|ogg|mov|m4v)($|\?)/i.test(url)) {
                md = `![${caption || 'Video'}](${url})`;
            } else {
                md = `@[video](${url})`;
            }

            const editor = getEditor();
            insertAtCursor(editor, md);
            bootstrap.Modal.getInstance(modalEl).hide();
            videoUrlInput.value = '';
            videoCaptionInput.value = '';
        });

        // Tab 3: Image Link Submit
        const imageSubmitBtn = modalEl.querySelector('#wikiImageLinkSubmitBtn');
        const imageUrlInput = modalEl.querySelector('#wikiImageUrlInput');
        const imageAltInput = modalEl.querySelector('#wikiImageAltInput');

        imageSubmitBtn.addEventListener('click', function () {
            const url = imageUrlInput.value.trim();
            const alt = imageAltInput.value.trim();
            if (!url) {
                imageUrlInput.focus();
                return;
            }
            const md = `![${alt || 'Bild'}](${url})`;
            const editor = getEditor();
            insertAtCursor(editor, md);
            bootstrap.Modal.getInstance(modalEl).hide();
            imageUrlInput.value = '';
            imageAltInput.value = '';
        });

        return modalEl;
    }

    function formatBytes(bytes) {
        if (!bytes || bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    function uploadMediaFile(file) {
        const formData = new FormData();
        formData.append('file', file);
        if (window.PrismateamsCsrf && typeof window.PrismateamsCsrf.getToken === 'function') {
            const token = window.PrismateamsCsrf.getToken();
            if (token) formData.append('csrf_token', token);
        }

        return fetch('/wiki/api/upload-media', {
            method: 'POST',
            body: formData
        })
        .then(function (res) {
            return res.json().then(function (data) {
                if (!res.ok || !data.success) {
                    throw new Error(data.error || 'Fehler beim Upload.');
                }
                return data;
            });
        });
    }

    function openMarkdownMediaModal(type, editor, selectedText) {
        activeEditor = editor || getEditor();
        if (activeEditor && typeof activeEditor.selectionStart === 'number') {
            savedSelection = {
                start: activeEditor.selectionStart,
                end: activeEditor.selectionEnd
            };
        } else {
            savedSelection = null;
        }

        const modalEl = createMediaModal();
        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);

        const tabUpload = modalEl.querySelector('#wiki-tab-upload');
        const fileInput = modalEl.querySelector('#wikiMediaFileInput');
        const modalTitle = modalEl.querySelector('#wikiMediaModalTitle');
        const dropzoneTitle = modalEl.querySelector('#wikiUploadDropzoneTitle');
        const dropzoneDesc = modalEl.querySelector('#wikiUploadDropzoneDesc');

        // Fehlermeldung & Details zurücksetzen
        modalEl.querySelector('#wikiUploadAlert').classList.add('d-none');
        modalEl.querySelector('#wikiUploadFileDetails').style.display = 'none';
        modalEl.querySelector('#wikiUploadSubmitBtn').disabled = true;

        // Immer Upload-Tab standardmäßig aktivieren (bei Bildern und bei Videos)
        const trigger = new bootstrap.Tab(tabUpload);
        trigger.show();

        if (type === 'video') {
            fileInput.accept = 'video/*,image/*';
            if (modalTitle) modalTitle.textContent = 'Video oder Foto hinzufügen';
            if (dropzoneTitle) dropzoneTitle.textContent = 'Video oder Foto hierher ziehen';
            if (dropzoneDesc) dropzoneDesc.textContent = 'Unterstützt: MP4, WebM, OGG, MOV sowie JPEG, PNG, GIF, WebP, SVG';
            if (selectedText) {
                modalEl.querySelector('#wikiVideoCaptionInput').value = selectedText;
            }
        } else {
            fileInput.accept = 'image/*,video/*';
            if (modalTitle) modalTitle.textContent = 'Foto oder Video hinzufügen';
            if (dropzoneTitle) dropzoneTitle.textContent = 'Foto oder Video hierher ziehen';
            if (dropzoneDesc) dropzoneDesc.textContent = 'Unterstützt: JPEG, PNG, GIF, WebP, SVG sowie MP4, WebM, OGG, MOV';
            if (selectedText) {
                modalEl.querySelector('#wikiImageAltInput').value = selectedText;
            }
        }

        modal.show();
    }

    // Drag & Drop direkt auf den Editor
    function setupEditorDropAndPaste() {
        const dropZones = [
            document.querySelector('.markdown-editor-content'),
            document.querySelector('.wiki-editor-shell'),
            document.getElementById('wikiEditor')
        ].filter(Boolean);

        dropZones.forEach(function (zone) {
            if (!zone || zone.dataset.mediaDropConfigured === '1') return;
            zone.dataset.mediaDropConfigured = '1';

            zone.addEventListener('dragover', function (e) {
                e.preventDefault();
                zone.classList.add('wiki-editor-dragover');
            });

            zone.addEventListener('dragleave', function (e) {
                e.preventDefault();
                zone.classList.remove('wiki-editor-dragover');
            });

            zone.addEventListener('drop', function (e) {
                e.preventDefault();
                zone.classList.remove('wiki-editor-dragover');

                const files = e.dataTransfer && e.dataTransfer.files;
                if (!files || files.length === 0) return;

                const editor = getEditor();
                Array.from(files).forEach(function (file) {
                    if (file.type.startsWith('image/') || file.type.startsWith('video/')) {
                        const tempPlaceholder = `<!-- Lade ${file.name} hoch... -->`;
                        insertAtCursor(editor, tempPlaceholder);
                        uploadMediaFile(file)
                            .then(function (data) {
                                editor.value = editor.value.replace(tempPlaceholder, data.markdown);
                                editor.dispatchEvent(new Event('input', { bubbles: true }));
                                if (window.MarkdownToolbar && typeof window.MarkdownToolbar.syncVisual === 'function') {
                                    window.MarkdownToolbar.syncVisual();
                                }
                            })
                            .catch(function (err) {
                                editor.value = editor.value.replace(tempPlaceholder, `<!-- Upload fehlgeschlagen: ${err.message} -->`);
                                editor.dispatchEvent(new Event('input', { bubbles: true }));
                                console.error('Upload error:', err);
                            });
                    }
                });
            });
        });

        // Clipboard Paste (z.B. Screenshots)
        if (!document.body.dataset.wikiPasteConfigured) {
            document.body.dataset.wikiPasteConfigured = '1';
            document.addEventListener('paste', function (e) {
                const active = document.activeElement;
                const isEditorArea = active && (
                    active.classList.contains('markdown-editor-textarea') ||
                    active.classList.contains('md-segment-textarea') ||
                    active.closest('.markdown-editor-content') ||
                    active.closest('.wiki-editor-shell')
                );
                if (!isEditorArea) return;

                const items = e.clipboardData && e.clipboardData.items;
                if (!items) return;

                for (let i = 0; i < items.length; i++) {
                    const item = items[i];
                    if (item.type && item.type.indexOf('image') !== -1) {
                        const blob = item.getAsFile();
                        if (blob) {
                            e.preventDefault();
                            const editor = getEditor();
                            const tempPlaceholder = `<!-- Lade Screenshot hoch... -->`;
                            insertAtCursor(editor, tempPlaceholder);

                            uploadMediaFile(blob)
                                .then(function (data) {
                                    editor.value = editor.value.replace(tempPlaceholder, data.markdown);
                                    editor.dispatchEvent(new Event('input', { bubbles: true }));
                                    if (window.MarkdownToolbar && typeof window.MarkdownToolbar.syncVisual === 'function') {
                                        window.MarkdownToolbar.syncVisual();
                                    }
                                })
                                .catch(function (err) {
                                    editor.value = editor.value.replace(tempPlaceholder, `<!-- Screenshot-Upload fehlgeschlagen: ${err.message} -->`);
                                    editor.dispatchEvent(new Event('input', { bubbles: true }));
                                    console.error('Screenshot upload error:', err);
                                });
                            break;
                        }
                    }
                }
            });
        }
    }

    // Vorschau-Modal
    function createPreviewModal() {
        let modalEl = document.getElementById('wikiPreviewModal');
        if (modalEl) return modalEl;

        modalEl = document.createElement('div');
        modalEl.id = 'wikiPreviewModal';
        modalEl.className = 'modal fade';
        modalEl.setAttribute('tabindex', '-1');
        modalEl.setAttribute('aria-hidden', 'true');

        modalEl.innerHTML = `
            <div class="modal-dialog modal-xl modal-dialog-scrollable">
                <div class="modal-content mod-card">
                    <div class="modal-header border-bottom">
                        <h5 class="modal-title d-flex align-items-center gap-2">
                            <i class="bi bi-eye text-primary"></i>
                            <span id="wikiPreviewModalTitle">Vorschau</span>
                        </h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Schließen"></button>
                    </div>
                    <div class="modal-body p-4">
                        <div id="wikiPreviewLoading" class="text-center py-5">
                            <div class="spinner-border text-primary mb-2" role="status"></div>
                            <p class="text-muted small">Lade Vorschau...</p>
                        </div>
                        <div id="wikiPreviewContent" class="markdown-content" style="display:none;"></div>
                    </div>
                    <div class="modal-footer border-top">
                        <button type="button" class="btn btn-outline-secondary mod-pill-btn" data-bs-dismiss="modal">Schließen</button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(modalEl);
        return modalEl;
    }

    function openWikiPreviewModal(content) {
        const modalEl = createPreviewModal();
        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        const loading = modalEl.querySelector('#wikiPreviewLoading');
        const container = modalEl.querySelector('#wikiPreviewContent');
        const titleEl = modalEl.querySelector('#wikiPreviewModalTitle');

        const titleInput = document.getElementById('title');
        if (titleInput && titleInput.value.trim()) {
            titleEl.textContent = 'Vorschau: ' + titleInput.value.trim();
        } else {
            titleEl.textContent = 'Vorschau';
        }

        loading.style.display = 'block';
        container.style.display = 'none';
        container.innerHTML = '';
        modal.show();

        const headers = { 'Content-Type': 'application/json' };
        if (window.PrismateamsCsrf && typeof window.PrismateamsCsrf.getToken === 'function') {
            const token = window.PrismateamsCsrf.getToken();
            if (token) headers['X-CSRFToken'] = token;
        }

        fetch('/wiki/api/preview', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({ content: content })
        })
        .then(function (res) {
            return res.json();
        })
        .then(function (data) {
            loading.style.display = 'none';
            container.style.display = 'block';
            container.innerHTML = data.html || '';

            if (window.FilesMarkdownEnhance && typeof window.FilesMarkdownEnhance.enhance === 'function') {
                window.FilesMarkdownEnhance.enhance(container);
            }
        })
        .catch(function (err) {
            loading.style.display = 'none';
            container.style.display = 'block';
            container.innerHTML = `<div class="alert alert-danger">Fehler beim Laden der Vorschau: ${err.message}</div>`;
        });
    }

    // Initialisierung bei DOMContentLoaded
    document.addEventListener('DOMContentLoaded', function () {
        setupEditorDropAndPaste();
    });

    window.openMarkdownMediaModal = openMarkdownMediaModal;
    window.openWikiPreviewModal = openWikiPreviewModal;
    window.setupWikiEditorMedia = setupEditorDropAndPaste;

})(window);
