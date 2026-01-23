/**
 * Drag & Drop File Upload Component
 * Wiederverwendbare Komponente für Drag & Drop Datei-Uploads
 */

class FileUploadDnD {
    constructor(options = {}) {
        this.dropZone = options.dropZone || null;
        this.fileInput = options.fileInput || null;
        this.onFilesSelected = options.onFilesSelected || null;
        this.onDragOver = options.onDragOver || null;
        this.onDragLeave = options.onDragLeave || null;
        this.accept = options.accept || null;
        this.multiple = options.multiple !== false;
        this.directory = options.directory || false;
        this.maxSize = options.maxSize || null; // in bytes
        this.showPreview = options.showPreview !== false;
        
        this.init();
    }
    
    init() {
        if (!this.dropZone || !this.fileInput) {
            console.warn('FileUploadDnD: dropZone oder fileInput nicht gefunden');
            return;
        }
        
        // Erstelle Drop-Zone falls nicht vorhanden
        if (!this.dropZone.classList.contains('dnd-drop-zone')) {
            this.dropZone.classList.add('dnd-drop-zone');
        }
        
        // Event Listener
        this.dropZone.addEventListener('dragover', this.handleDragOver.bind(this));
        this.dropZone.addEventListener('dragleave', this.handleDragLeave.bind(this));
        this.dropZone.addEventListener('drop', this.handleDrop.bind(this));
        this.dropZone.addEventListener('click', this.handleClick.bind(this));
        
        // File Input Change Event
        if (this.fileInput) {
            this.fileInput.addEventListener('change', this.handleFileInputChange.bind(this));
        }
    }
    
    handleDragOver(e) {
        e.preventDefault();
        e.stopPropagation();
        
        this.dropZone.classList.add('dnd-drag-over');
        
        if (this.onDragOver) {
            this.onDragOver(e);
        }
    }
    
    handleDragLeave(e) {
        e.preventDefault();
        e.stopPropagation();
        
        // Nur entfernen wenn wirklich außerhalb
        if (!this.dropZone.contains(e.relatedTarget)) {
            this.dropZone.classList.remove('dnd-drag-over');
        }
        
        if (this.onDragLeave) {
            this.onDragLeave(e);
        }
    }
    
    handleDrop(e) {
        e.preventDefault();
        e.stopPropagation();
        
        this.dropZone.classList.remove('dnd-drag-over');
        
        const files = Array.from(e.dataTransfer.files);
        
        if (files.length === 0) {
            return;
        }
        
        // Prüfe Dateitypen und Größe
        const validFiles = this.validateFiles(files);
        
        if (validFiles.length > 0) {
            this.processFiles(validFiles);
        }
    }
    
    handleClick(e) {
        // Öffne Datei-Dialog wenn auf Drop-Zone geklickt wird
        if (e.target === this.dropZone || this.dropZone.contains(e.target)) {
            // Prüfe ob nicht auf einen Button oder Link geklickt wurde
            if (!e.target.closest('button') && !e.target.closest('a') && !e.target.closest('input')) {
                this.fileInput.click();
            }
        }
    }
    
    handleFileInputChange(e) {
        const files = Array.from(e.target.files);
        
        if (files.length > 0) {
            const validFiles = this.validateFiles(files);
            
            if (validFiles.length > 0) {
                this.processFiles(validFiles);
            }
        }
    }
    
    validateFiles(files) {
        const validFiles = [];
        
        for (const file of files) {
            // Prüfe Dateigröße
            if (this.maxSize && file.size > this.maxSize) {
                this.showError(`Die Datei "${file.name}" ist zu groß. Maximale Größe: ${this.formatFileSize(this.maxSize)}`);
                continue;
            }
            
            // Prüfe Dateityp (wenn accept angegeben)
            if (this.accept && !this.isFileTypeAccepted(file)) {
                this.showError(`Die Datei "${file.name}" hat einen nicht erlaubten Typ.`);
                continue;
            }
            
            validFiles.push(file);
        }
        
        return validFiles;
    }
    
    isFileTypeAccepted(file) {
        if (!this.accept) {
            return true;
        }
        
        const acceptTypes = this.accept.split(',').map(type => type.trim());
        
        for (const acceptType of acceptTypes) {
            if (acceptType.startsWith('.')) {
                // Dateiendung
                if (file.name.toLowerCase().endsWith(acceptType.toLowerCase())) {
                    return true;
                }
            } else if (acceptType.includes('/*')) {
                // MIME-Type mit Wildcard (z.B. image/*)
                const baseType = acceptType.split('/')[0];
                if (file.type.startsWith(baseType + '/')) {
                    return true;
                }
            } else {
                // Exakter MIME-Type
                if (file.type === acceptType) {
                    return true;
                }
            }
        }
        
        return false;
    }
    
    processFiles(files) {
        // Setze Files in Input
        if (this.fileInput) {
            const dataTransfer = new DataTransfer();
            files.forEach(file => dataTransfer.items.add(file));
            this.fileInput.files = dataTransfer.files;
            
            // Trigger change event
            const event = new Event('change', { bubbles: true });
            this.fileInput.dispatchEvent(event);
        }
        
        // Callback aufrufen
        if (this.onFilesSelected) {
            this.onFilesSelected(files);
        }
        
        // Zeige Vorschau falls aktiviert
        if (this.showPreview) {
            this.showPreview(files);
        }
    }
    
    showError(message) {
        // Zeige Fehlermeldung (kann überschrieben werden)
        console.error('FileUploadDnD:', message);
        
        // Versuche Toast oder Alert zu zeigen
        if (typeof showToast === 'function') {
            showToast(message, 'error');
        } else if (typeof alert === 'function') {
            alert(message);
        }
    }
    
    showPreview(files) {
        // Kann überschrieben werden für spezifische Preview-Logik
        console.log('FileUploadDnD: Preview für', files.length, 'Dateien');
    }
    
    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        
        return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
    }
    
    destroy() {
        if (this.dropZone) {
            this.dropZone.removeEventListener('dragover', this.handleDragOver);
            this.dropZone.removeEventListener('dragleave', this.handleDragLeave);
            this.dropZone.removeEventListener('drop', this.handleDrop);
            this.dropZone.removeEventListener('click', this.handleClick);
            this.dropZone.classList.remove('dnd-drop-zone', 'dnd-drag-over');
        }
    }
}

// CSS für Drag & Drop (wird automatisch injiziert)
if (typeof document !== 'undefined') {
    const style = document.createElement('style');
    style.textContent = `
        .dnd-drop-zone {
            position: relative;
            transition: all 0.3s ease;
        }
        
        .dnd-drop-zone.dnd-drag-over {
            background-color: rgba(0, 123, 255, 0.1);
            border-color: #007bff;
            border-style: dashed;
            border-width: 2px;
        }
        
        .dnd-drop-zone.dnd-drag-over::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 123, 255, 0.05);
            pointer-events: none;
            z-index: 1;
        }
        
        .dnd-drop-zone.dnd-drag-over::after {
            content: '📁 Dateien hier ablegen';
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 1.2rem;
            font-weight: bold;
            color: #007bff;
            pointer-events: none;
            z-index: 2;
            background: white;
            padding: 10px 20px;
            border-radius: 5px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
    `;
    document.head.appendChild(style);
}

// Export für Module-Systeme
if (typeof module !== 'undefined' && module.exports) {
    module.exports = FileUploadDnD;
}
