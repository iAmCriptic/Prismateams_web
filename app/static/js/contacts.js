/**
 * Kontakt-Chip-Komponente für E-Mail-Empfänger-Felder
 * Unterstützt Autovervollständigung mit Chips/Bubbles
 */

class ContactChipInput {
    constructor(containerId, hiddenInputId, searchUrl) {
        this.container = document.getElementById(containerId);
        this.hiddenInput = document.getElementById(hiddenInputId);
        this.searchUrl = searchUrl;
        this.chips = [];
        this.searchTimeout = null;
        this.autocompleteDropdown = null;
        this.selectedIndex = -1;
        
        if (!this.container || !this.hiddenInput) {
            console.error('ContactChipInput: Container oder Hidden Input nicht gefunden');
            return;
        }
        
        this.init();
    }
    
    init() {
        // Erstelle Input-Feld
        this.input = document.createElement('input');
        this.input.type = 'text';
        this.input.className = 'contact-chip-input';
        this.input.placeholder = this.container.getAttribute('data-placeholder') || 'E-Mail-Adresse eingeben...';
        this.input.autocomplete = 'off';
        
        // Erstelle Container für Chips
        this.chipsContainer = document.createElement('div');
        this.chipsContainer.className = 'contact-chips-container';
        
        // Erstelle Autocomplete-Dropdown
        this.autocompleteDropdown = document.createElement('div');
        this.autocompleteDropdown.className = 'contact-autocomplete-dropdown';
        this.autocompleteDropdown.style.display = 'none';
        
        // Struktur aufbauen - Input zuerst (links), dann Chips (rechts)
        this.container.appendChild(this.input);
        this.container.appendChild(this.chipsContainer);
        this.container.appendChild(this.autocompleteDropdown);
        
        // Event Listeners
        this.input.addEventListener('input', (e) => this.handleInput(e));
        this.input.addEventListener('keydown', (e) => this.handleKeyDown(e));
        this.input.addEventListener('focus', () => this.showAutocomplete());
        this.input.addEventListener('blur', () => {
            // Delay um Click-Events auf Dropdown zu ermöglichen
            setTimeout(() => this.hideAutocomplete(), 200);
        });
        
        // Lade initiale Werte falls vorhanden
        this.loadInitialValues();
    }
    
    loadInitialValues() {
        const initialValue = this.hiddenInput.value;
        if (initialValue) {
            const emails = initialValue.split(',').map(e => e.trim()).filter(e => e);
            emails.forEach(email => {
                this.addChip(email, email);
            });
        }
    }
    
    handleInput(e) {
        const value = e.target.value.trim();
        
        if (value.length === 0) {
            this.hideAutocomplete();
            return;
        }
        
        // Debounce Suche
        clearTimeout(this.searchTimeout);
        this.searchTimeout = setTimeout(() => {
            this.searchContacts(value);
        }, 300);
    }
    
    handleKeyDown(e) {
        const dropdownItems = this.autocompleteDropdown.querySelectorAll('.autocomplete-item');
        
        if (e.key === 'Enter') {
            e.preventDefault();
            if (this.selectedIndex >= 0 && dropdownItems[this.selectedIndex]) {
                const item = dropdownItems[this.selectedIndex];
                const email = item.getAttribute('data-email');
                const name = item.getAttribute('data-name') || email;
                this.addChip(email, name);
                this.input.value = '';
                this.hideAutocomplete();
            } else if (this.input.value.trim()) {
                // Direkte E-Mail-Eingabe
                const email = this.input.value.trim();
                if (this.isValidEmail(email)) {
                    this.addChip(email, email);
                    this.input.value = '';
                    this.hideAutocomplete();
                }
            }
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            this.selectedIndex = Math.min(this.selectedIndex + 1, dropdownItems.length - 1);
            this.updateSelectedItem(dropdownItems);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            this.selectedIndex = Math.max(this.selectedIndex - 1, -1);
            this.updateSelectedItem(dropdownItems);
        } else if (e.key === 'Escape') {
            this.hideAutocomplete();
        } else if (e.key === 'Backspace' && this.input.value === '' && this.chips.length > 0) {
            // Entferne letzten Chip bei Backspace
            this.removeChip(this.chips.length - 1);
        }
    }
    
    updateSelectedItem(items) {
        items.forEach((item, index) => {
            if (index === this.selectedIndex) {
                item.classList.add('selected');
                item.scrollIntoView({ block: 'nearest' });
            } else {
                item.classList.remove('selected');
            }
        });
    }
    
    async searchContacts(query) {
        if (query.length < 2) {
            this.hideAutocomplete();
            return;
        }
        
        try {
            const response = await fetch(`${this.searchUrl}?q=${encodeURIComponent(query)}`);
            const data = await response.json();
            
            if (data.results && data.results.length > 0) {
                this.showAutocomplete(data.results);
            } else {
                this.hideAutocomplete();
            }
        } catch (error) {
            console.error('Fehler bei Kontakt-Suche:', error);
            this.hideAutocomplete();
        }
    }
    
    showAutocomplete(results) {
        if (!results) {
            return;
        }
        
        this.autocompleteDropdown.innerHTML = '';
        this.selectedIndex = -1;
        
        results.forEach((result, index) => {
            const item = document.createElement('div');
            item.className = 'autocomplete-item';
            item.setAttribute('data-email', result.email);
            item.setAttribute('data-name', result.name || '');
            
            if (result.type === 'contact' && result.name) {
                item.innerHTML = `
                    <div class="autocomplete-item-content">
                        <div class="autocomplete-avatar">${result.name[0].toUpperCase()}</div>
                        <div class="autocomplete-info">
                            <div class="autocomplete-name">${this.escapeHtml(result.name)}</div>
                            <div class="autocomplete-email">${this.escapeHtml(result.email)}</div>
                        </div>
                    </div>
                `;
            } else {
                item.innerHTML = `
                    <div class="autocomplete-item-content">
                        <div class="autocomplete-avatar">${result.email[0].toUpperCase()}</div>
                        <div class="autocomplete-info">
                            <div class="autocomplete-email">${this.escapeHtml(result.email)}</div>
                        </div>
                    </div>
                `;
            }
            
            item.addEventListener('click', () => {
                this.addChip(result.email, result.name || result.email);
                this.input.value = '';
                this.hideAutocomplete();
            });
            
            this.autocompleteDropdown.appendChild(item);
        });
        
        this.autocompleteDropdown.style.display = 'block';
    }
    
    hideAutocomplete() {
        this.autocompleteDropdown.style.display = 'none';
        this.selectedIndex = -1;
    }
    
    addChip(email, name) {
        // Prüfe auf Duplikate
        if (this.chips.some(chip => chip.email.toLowerCase() === email.toLowerCase())) {
            return;
        }
        
        // Validiere E-Mail
        if (!this.isValidEmail(email)) {
            return;
        }
        
        const chip = {
            email: email,
            name: name || email
        };
        
        this.chips.push(chip);
        this.renderChips();
        this.updateHiddenInput();
    }
    
    removeChip(index) {
        if (index >= 0 && index < this.chips.length) {
            this.chips.splice(index, 1);
            this.renderChips();
            this.updateHiddenInput();
        }
    }
    
    renderChips() {
        this.chipsContainer.innerHTML = '';
        
        this.chips.forEach((chip, index) => {
            const chipElement = document.createElement('div');
            chipElement.className = 'contact-chip';
            
            const initial = chip.name[0].toUpperCase();
            
            chipElement.innerHTML = `
                <div class="chip-avatar">${initial}</div>
                <span class="chip-text">${this.escapeHtml(chip.name !== chip.email ? `${chip.name} <${chip.email}>` : chip.email)}</span>
                <button type="button" class="chip-remove" aria-label="Entfernen">
                    <i class="bi bi-x"></i>
                </button>
            `;
            
            const removeBtn = chipElement.querySelector('.chip-remove');
            removeBtn.addEventListener('click', () => {
                this.removeChip(index);
                this.input.focus();
            });
            
            this.chipsContainer.appendChild(chipElement);
        });
    }
    
    updateHiddenInput() {
        const emails = this.chips.map(chip => chip.email);
        this.hiddenInput.value = emails.join(', ');
    }
    
    isValidEmail(email) {
        const pattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return pattern.test(email);
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialisiere Chip-Inputs wenn DOM bereit ist
document.addEventListener('DOMContentLoaded', function() {
    // To-Feld
    const toContainer = document.getElementById('toChipContainer');
    const toHidden = document.getElementById('toHidden');
    if (toContainer && toHidden) {
        const searchUrl = toContainer.getAttribute('data-search-url') || '/contacts/api/search';
        new ContactChipInput('toChipContainer', 'toHidden', searchUrl);
    }
    
    // CC-Feld
    const ccContainer = document.getElementById('ccChipContainer');
    const ccHidden = document.getElementById('ccHidden');
    if (ccContainer && ccHidden) {
        const searchUrl = ccContainer.getAttribute('data-search-url') || '/contacts/api/search';
        new ContactChipInput('ccChipContainer', 'ccHidden', searchUrl);
    }
});
