document.addEventListener('DOMContentLoaded', () => {
    const fileInput = document.getElementById('file');
    const folderInput = document.getElementById('folder_upload');
    const chooseFilesBtn = document.getElementById('chooseFilesBtn');
    const chooseFolderBtn = document.getElementById('chooseFolderBtn');
    const uploadForm = document.getElementById('uploadForm');
    const uploadProgress = document.getElementById('uploadProgress');
    const selectionInfo = document.getElementById('selectionInfo');
    const maxSize = Number(window.FILES_MAX_UPLOAD_BYTES) || (100 * 1024 * 1024);

    function notify(msg, category) {
        if (typeof window.ptAlert === 'function') {
            window.ptAlert(msg, category || 'warning');
            return;
        }
        window.alert(msg);
    }

    if (typeof window.initFilesViewToggle === 'function') {
        window.initFilesViewToggle({
            toggleEl: document.querySelector('.files-ext-toolbar .files-view-toggle'),
            listBtn: document.getElementById('dropboxListViewBtn'),
            gridBtn: document.getElementById('dropboxGridViewBtn'),
            listPane: document.getElementById('dropboxListViewContainer'),
            gridPane: document.getElementById('dropboxGridViewContainer'),
            stageEl: document.getElementById('dropboxViewStage'),
            storageKey: 'dropboxViewMode',
            defaultMode: 'grid',
        });
    }

    function updateSelectionInfo(text) {
        if (selectionInfo) {
            selectionInfo.textContent = text;
        }
    }

    function clearOtherInput(activeInput) {
        if (activeInput === 'file' && folderInput) {
            folderInput.value = '';
        }
        if (activeInput === 'folder' && fileInput) {
            fileInput.value = '';
        }
    }

    function validateUpload() {
        let selectedFiles = [];
        let source = '';

        if (fileInput && fileInput.files.length > 0) {
            selectedFiles = Array.from(fileInput.files);
            source = 'Dateien';
        } else if (folderInput && folderInput.files.length > 0) {
            selectedFiles = Array.from(folderInput.files);
            source = 'Ordner';
        }

        if (!selectedFiles.length) {
            updateSelectionInfo('Wählen Sie Dateien oder einen Ordner aus. Upload startet automatisch.');
            return false;
        }

        for (const file of selectedFiles) {
            if (file.size > maxSize) {
                const maxLabel = (typeof window.FILES_MAX_UPLOAD_LABEL === 'string' && window.FILES_MAX_UPLOAD_LABEL)
                    ? window.FILES_MAX_UPLOAD_LABEL
                    : (Math.round(maxSize / (1024 * 1024)) + 'MB');
                notify(`Die Datei "${file.name}" ist zu groß. Maximale Größe: ${maxLabel} pro Datei.`, 'warning');
                if (source === 'Dateien' && fileInput) fileInput.value = '';
                if (source === 'Ordner' && folderInput) folderInput.value = '';
                updateSelectionInfo('Wählen Sie Dateien oder einen Ordner aus. Upload startet automatisch.');
                return false;
            }
        }

        updateSelectionInfo(`${selectedFiles.length} Datei(en) aus ${source.toLowerCase()} ausgewählt. Upload startet...`);
        return true;
    }

    function submitUploadForm() {
        if (!uploadForm) return;
        if (!validateUpload()) return;
        if (uploadProgress) {
            uploadProgress.style.display = 'block';
        }
        updateSelectionInfo('Upload läuft...');
        uploadForm.submit();
    }

    if (chooseFilesBtn && fileInput) {
        chooseFilesBtn.addEventListener('click', () => fileInput.click());
    }
    if (chooseFolderBtn && folderInput) {
        chooseFolderBtn.addEventListener('click', () => folderInput.click());
    }

    if (fileInput) {
        fileInput.addEventListener('change', () => {
            clearOtherInput('file');
            submitUploadForm();
        });
    }

    if (folderInput) {
        folderInput.addEventListener('change', () => {
            clearOtherInput('folder');
            submitUploadForm();
        });
    }

    if (uploadForm) {
        uploadForm.addEventListener('submit', (event) => {
            const hasFile = fileInput && fileInput.files.length > 0;
            const hasFolder = folderInput && folderInput.files.length > 0;
            if (!hasFile && !hasFolder) {
                event.preventDefault();
                notify('Bitte wählen Sie Dateien oder einen Ordner aus.', 'warning');
                return;
            }

            if (uploadProgress) {
                uploadProgress.style.display = 'block';
            }
            let progress = 0;
            const progressBar = uploadProgress ? uploadProgress.querySelector('.progress-bar') : null;
            const interval = setInterval(() => {
                progress += Math.random() * 15;
                if (progress >= 100) {
                    progress = 100;
                    clearInterval(interval);
                }
                if (progressBar) {
                    progressBar.style.width = `${progress}%`;
                }
            }, 200);
        });
    }
});
