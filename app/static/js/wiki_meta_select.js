/**
 * Wiki meta category select: pill-dropdown inside .wiki-meta-chip.
 * Native <select> stays for form submit / change handlers.
 */
(function (global) {
    const CLOSE_ATTR = 'data-wiki-meta-select-close';

    function optionLabel(opt) {
        return ((opt && opt.textContent) || '').replace(/^[➕+\s]+/, '').trim();
    }

    function rebuildMenu(wrap) {
        const select = wrap._wikiSelect;
        const menu = wrap._wikiMenu;
        if (!select || !menu) return;
        menu.innerHTML = '';

        Array.from(select.options).forEach((opt, index) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'wiki-meta-menu__option';
            btn.dataset.index = String(index);
            if (opt.value === '__new__') {
                btn.classList.add('wiki-meta-menu__option--new');
            }
            if (index === select.selectedIndex) {
                btn.classList.add('is-selected');
            }

            const iconName = opt.dataset.icon || (opt.value === '__new__' ? 'bi-folder-plus' : '');
            if (iconName) {
                const icon = document.createElement('i');
                icon.className = `bi ${iconName}`;
                icon.setAttribute('aria-hidden', 'true');
                btn.appendChild(icon);
            }

            const text = document.createElement('span');
            text.textContent = optionLabel(opt);
            btn.appendChild(text);

            btn.addEventListener('click', (event) => {
                event.preventDefault();
                event.stopPropagation();
                select.selectedIndex = index;
                select.dispatchEvent(new Event('change', { bubbles: true }));
                syncTrigger(wrap);
                closeMenu(wrap);
            });
            menu.appendChild(btn);
        });
    }

    function syncTrigger(wrap) {
        const select = wrap._wikiSelect;
        const valueEl = wrap._wikiValue;
        if (!select || !valueEl) return;
        const opt = select.options[select.selectedIndex];
        valueEl.textContent = optionLabel(opt) || '—';
        valueEl.classList.toggle('is-placeholder', !opt || opt.value === '');
        rebuildMenu(wrap);
    }

    function closeMenu(wrap) {
        if (!wrap) return;
        wrap.classList.remove('is-open');
        if (wrap._wikiMenu) wrap._wikiMenu.hidden = true;
        if (wrap._wikiTrigger) wrap._wikiTrigger.setAttribute('aria-expanded', 'false');
    }

    function closeAll(except) {
        document.querySelectorAll('.wiki-meta-chip--category.is-open').forEach((wrap) => {
            if (wrap !== except) closeMenu(wrap);
        });
    }

    function openMenu(wrap) {
        closeAll(wrap);
        rebuildMenu(wrap);
        wrap.classList.add('is-open');
        if (wrap._wikiMenu) wrap._wikiMenu.hidden = false;
        if (wrap._wikiTrigger) wrap._wikiTrigger.setAttribute('aria-expanded', 'true');
    }

    function enhance(select) {
        if (!select || select.dataset.wikiPillEnhanced === '1') {
            return select && select.closest('.wiki-meta-chip--category');
        }

        const chip = select.closest('.wiki-meta-chip--category');
        if (!chip) return null;

        select.dataset.wikiPillEnhanced = '1';
        select.classList.add('wiki-meta-select--native');
        chip.classList.add('wiki-meta-chip--select');

        let valueEl = chip.querySelector('.wiki-meta-chip-value');
        if (!valueEl) {
            valueEl = document.createElement('span');
            valueEl.className = 'wiki-meta-chip-value';
            const body = chip.querySelector('.wiki-meta-chip-body');
            if (body) body.appendChild(valueEl);
        }

        let chevron = chip.querySelector('.wiki-meta-chip-chevron');
        if (!chevron) {
            chevron = document.createElement('i');
            chevron.className = 'bi bi-chevron-down wiki-meta-chip-chevron';
            chevron.setAttribute('aria-hidden', 'true');
            chip.appendChild(chevron);
        }

        let menu = chip.querySelector('.wiki-meta-menu');
        if (!menu) {
            menu = document.createElement('div');
            menu.className = 'wiki-meta-menu';
            menu.setAttribute('role', 'listbox');
            menu.hidden = true;
            chip.appendChild(menu);
        }

        chip._wikiSelect = select;
        chip._wikiValue = valueEl;
        chip._wikiMenu = menu;
        chip._wikiTrigger = chip;

        chip.setAttribute('role', 'button');
        chip.setAttribute('tabindex', '0');
        chip.setAttribute('aria-haspopup', 'listbox');
        chip.setAttribute('aria-expanded', 'false');

        const toggle = (event) => {
            if (event.target.closest('.wiki-meta-menu')) return;
            event.preventDefault();
            event.stopPropagation();
            if (select.disabled) return;
            if (chip.classList.contains('is-open')) closeMenu(chip);
            else openMenu(chip);
        };

        chip.addEventListener('click', toggle);
        chip.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') toggle(event);
        });

        select.addEventListener('change', () => syncTrigger(chip));
        syncTrigger(chip);
        return chip;
    }

    function enhanceAll(root) {
        const scope = root || document;
        scope.querySelectorAll('select.wiki-meta-select, select#category_id').forEach(enhance);
    }

    if (!document[CLOSE_ATTR]) {
        document[CLOSE_ATTR] = true;
        document.addEventListener('click', (event) => {
            if (event.target.closest('.wiki-meta-chip--category')) return;
            closeAll();
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') closeAll();
        });
    }

    global.WikiMetaSelect = { enhance, enhanceAll, sync: (select) => {
        const wrap = select && select.closest('.wiki-meta-chip--category');
        if (wrap) syncTrigger(wrap);
    }};

    document.addEventListener('DOMContentLoaded', () => enhanceAll());
})(window);
