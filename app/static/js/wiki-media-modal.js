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
        if (activeEditor) return activeEditor;
        return document.getElementById('wikiEditor');
    }

    function insertAtCursor(textarea, text) {
        if (!textarea) return;
        textarea.focus();
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        const before = textarea.value.substring(0, start);
        const after = textarea.value.substring(end);
        
        // Füge bei Bedarf neue Zeilen hinzu
        const needsNewlineBefore = before.length > 0 && !before.endsWith('\n');
        const needsNewlineAfter = after.length > 0 && !after.startsWith('\n');
        const insertText = (needsNewlineBefore ? '\n' : '') + text + (needsNewlineAfter ? '\n' : '');

        textarea.value = before + insertText + after;
        const newPos = start + insertText.length;
        textarea.selectionStart = newPos;
        textarea.selectionEnd = newPos;

        // Triggere Input-Event für Autosave / Dirty Check
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
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
                            <!-- TAB 1: UPLOAD -->
                            <div class="tab-pane fade show active" id="wiki-pane-upload" role="tabpanel">
                                <div class="wiki-upload-dropzone p-4 text-center border rounded-3 mb-3" id="wikiUploadDropzone">
                                    <i class="bi bi-cloud-arrow-up display-5 text-muted mb-2 d-block"></i>
                                    <h6>Foto oder Video hierher ziehen</h6>
                                    <p class="text-muted small mb-2">Unterstützt: MP4, WebM, OGG, MOV sowie JPEG, PNG, GIF, WebP, SVG</p>
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
            // YouTube oder Vimeo
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
        const modalEl = createMediaModal();
        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);

        const tabUpload = modalEl.querySelector('#wiki-tab-upload');
        const tabVideo = modalEl.querySelector('#wiki-tab-video');
        const tabImage = modalEl.querySelector('#wiki-tab-image');

        if (type === 'video') {
            const trigger = new bootstrap.Tab(tabVideo);
            trigger.show();
            if (selectedText) {
                modalEl.querySelector('#wikiVideoCaptionInput').value = selectedText;
            }
        } else if (type === 'image') {
            const trigger = new bootstrap.Tab(tabUpload);
            trigger.show();
            if (selectedText) {
                modalEl.querySelector('#wikiImageAltInput').value = selectedText;
            }
        }

        modal.show();
    }

    // Drag & Drop direkt auf den Editor
    function setupEditorDropAndPaste(editor) {
        if (!editor || editor.dataset.mediaDropConfigured === '1') return;
        editor.dataset.mediaDropConfigured = '1';

        editor.addEventListener('dragover', function (e) {
            e.preventDefault();
            editor.classList.add('wiki-editor-dragover');
        });

        editor.addEventListener('dragleave', function (e) {
            e.preventDefault();
            editor.classList.remove('wiki-editor-dragover');
        });

        editor.addEventListener('drop', function (e) {
            e.preventDefault();
            editor.classList.remove('wiki-editor-dragover');

            const files = e.dataTransfer && e.dataTransfer.files;
            if (!files || files.length === 0) return;

            Array.from(files).forEach(function (file) {
                if (file.type.startsWith('image/') || file.type.startsWith('video/')) {
                    insertAtCursor(editor, `<!-- Lade ${file.name} hoch... -->`);
                    uploadMediaFile(file)
                        .then(function (data) {
                            editor.value = editor.value.replace(`<!-- Lade ${file.name} hoch... -->`, data.markdown);
                            editor.dispatchEvent(new Event('input', { bubbles: true }));
                        })
                        .catch(function (err) {
                            editor.value = editor.value.replace(`<!-- Lade ${file.name} hoch... -->`, `<!-- Upload fehlgeschlagen: ${err.message} -->`);
                            console.error('Upload error:', err);
                        });
                }
            });
        });

        // Clipboard Paste (z.B. Screenshots)
        editor.addEventListener('paste', function (e) {
            const items = e.clipboardData && e.clipboardData.items;
            if (!items) return;

            for (let i = 0; i < items.length; i++) {
                const item = items[i];
                if (item.type.indexOf('image') !== -1) {
                    const blob = item.getAsFile();
                    if (blob) {
                        e.preventDefault();
                        const tempPlaceholder = `<!-- Lade Screenshot hoch... -->`;
                        insertAtCursor(editor, tempPlaceholder);

                        uploadMediaFile(blob)
                            .then(function (data) {
                                editor.value = editor.value.replace(tempPlaceholder, data.markdown);
                                editor.dispatchEvent(new Event('input', { bubbles: true }));
                            })
                            .catch(function (err) {
                                editor.value = editor.value.replace(tempPlaceholder, `<!-- Screenshot-Upload fehlgeschlagen: ${err.message} -->`);
                                console.error('Screenshot upload error:', err);
                            });
                        break;
                    }
                }
            }
        });
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

        fetch('/wiki/api/preview', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
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
        const editor = document.getElementById('wikiEditor');
        if (editor) {
            setupEditorDropAndPaste(editor);
        }
    });

    window.openMarkdownMediaModal = openMarkdownMediaModal;
    window.openWikiPreviewModal = openWikiPreviewModal;
    window.setupWikiEditorMedia = setupEditorDropAndPaste;

})(window);
