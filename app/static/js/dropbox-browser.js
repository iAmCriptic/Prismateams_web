document.addEventListener('DOMContentLoaded', () => {
    const fileInput = document.getElementById('file');
    const folderInput = document.getElementById('folder_upload');
    const chooseFilesBtn = document.getElementById('chooseFilesBtn');
    const chooseFolderBtn = document.getElementById('chooseFolderBtn');
    const uploadForm = document.getElementById('uploadForm');
    const uploadProgress = document.getElementById('uploadProgress');
    const selectionInfo = document.getElementById('selectionInfo');
    const maxSize = 100 * 1024 * 1024;

    const listViewBtn = document.getElementById('dropboxListViewBtn');
    const gridViewBtn = document.getElementById('dropboxGridViewBtn');
    const gridViewContainer = document.getElementById('dropboxGridViewContainer');
    const listViewContainer = document.getElementById('dropboxListViewContainer');
    const viewStorageKey = 'dropboxViewMode';

    function setView(mode) {
        if (!listViewBtn || !gridViewBtn || !gridViewContainer || !listViewContainer) {
            return;
        }
        if (mode === 'list') {
            listViewBtn.classList.add('active');
            gridViewBtn.classList.remove('active');
            listViewContainer.classList.remove('d-none');
            gridViewContainer.classList.add('d-none');
        } else {
            gridViewBtn.classList.add('active');
            listViewBtn.classList.remove('active');
            gridViewContainer.classList.remove('d-none');
            listViewContainer.classList.add('d-none');
        }
        window.localStorage.setItem(viewStorageKey, mode);
    }

    if (listViewBtn && gridViewBtn) {
        listViewBtn.addEventListener('click', () => setView('list'));
        gridViewBtn.addEventListener('click', () => setView('grid'));
        const savedMode = window.localStorage.getItem(viewStorageKey) || 'grid';
        setView(savedMode === 'list' ? 'list' : 'grid');
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
                window.alert(`Die Datei "${file.name}" ist zu groß. Maximale Größe: 100MB pro Datei.`);
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
                window.alert('Bitte wählen Sie Dateien oder einen Ordner aus.');
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
