/**
 * Pill-Select: ersetzt native <select>-Popups durch Pill-Dropdowns.
 * Native <select> bleibt im DOM (Form-Submit / Change-Events).
 */
(function (global) {
    const CLOSE_ATTR = 'data-inv-pill-select-close';

    function selectedLabel(select) {
        const opt = select.options[select.selectedIndex];
        if (!opt) return '';
        return (opt.textContent || '').trim();
    }

    function isPlaceholderSelected(select) {
        const opt = select.options[select.selectedIndex];
        return !opt || opt.value === '';
    }

    function rebuildMenu(wrap) {
        const select = wrap._invSelect;
        const menu = wrap._invMenu;
        if (!select || !menu) return;
        menu.innerHTML = '';
        Array.from(select.options).forEach((opt, index) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'inv-pill-select__option';
            btn.textContent = (opt.textContent || '').trim();
            btn.dataset.index = String(index);
            if (opt.disabled) {
                btn.disabled = true;
                btn.style.opacity = '0.55';
            }
            if (index === select.selectedIndex) {
                btn.classList.add('is-selected');
            }
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
        const select = wrap._invSelect;
        const label = wrap._invLabel;
        if (!select || !label) return;
        label.textContent = selectedLabel(select) || '—';
        label.classList.toggle('is-placeholder', isPlaceholderSelected(select));
        rebuildMenu(wrap);
    }

    function closeMenu(wrap) {
        if (!wrap) return;
        wrap.classList.remove('is-open');
        if (wrap._invMenu) wrap._invMenu.hidden = true;
    }

    function closeAll(except) {
        document.querySelectorAll('.inv-pill-select.is-open').forEach((wrap) => {
            if (wrap !== except) closeMenu(wrap);
        });
    }

    function openMenu(wrap) {
        closeAll(wrap);
        rebuildMenu(wrap);
        wrap.classList.add('is-open');
        if (wrap._invMenu) wrap._invMenu.hidden = false;
    }

    function enhanceSelect(select) {
        if (!select || select.dataset.pillEnhanced === '1') return select.closest('.inv-pill-select');
        if (select.multiple || select.size > 1) return null;

        select.dataset.pillEnhanced = '1';

        const wrap = document.createElement('div');
        wrap.className = 'inv-pill-select';
        wrap.dataset.invPillSelect = '1';

        const trigger = document.createElement('button');
        trigger.type = 'button';
        trigger.className = 'inv-pill-select__trigger';
        trigger.setAttribute('aria-haspopup', 'listbox');
        trigger.setAttribute('aria-expanded', 'false');

        const label = document.createElement('span');
        label.className = 'inv-pill-select__label';

        const chevron = document.createElement('i');
        chevron.className = 'bi bi-chevron-down inv-pill-select__chevron';
        chevron.setAttribute('aria-hidden', 'true');

        trigger.appendChild(label);
        trigger.appendChild(chevron);

        const menu = document.createElement('div');
        menu.className = 'inv-pill-select__menu';
        menu.setAttribute('role', 'listbox');
        menu.hidden = true;

        const parent = select.parentNode;
        parent.insertBefore(wrap, select);
        wrap.appendChild(select);
        wrap.appendChild(trigger);
        wrap.appendChild(menu);

        wrap._invSelect = select;
        wrap._invTrigger = trigger;
        wrap._invLabel = label;
        wrap._invMenu = menu;

        trigger.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            if (select.disabled) return;
            const open = wrap.classList.contains('is-open');
            if (open) closeMenu(wrap);
            else openMenu(wrap);
            trigger.setAttribute('aria-expanded', open ? 'false' : 'true');
        });

        select.addEventListener('change', () => syncTrigger(wrap));

        // Wenn Optionen per JS ersetzt werden
        const mo = new MutationObserver(() => syncTrigger(wrap));
        mo.observe(select, { childList: true, subtree: true, characterData: true, attributes: true });
        wrap._invObserver = mo;

        syncTrigger(wrap);
        return wrap;
    }

    function enhanceAll(root) {
        const scope = root || document;
        scope.querySelectorAll('select.form-select').forEach((select) => {
            if (select.closest('.inv-pill-select')) {
                const wrap = select.closest('.inv-pill-select');
                if (wrap && wrap._invSelect) syncTrigger(wrap);
                return;
            }
            enhanceSelect(select);
        });
    }

    if (!document[CLOSE_ATTR]) {
        document[CLOSE_ATTR] = true;
        document.addEventListener('click', (event) => {
            if (event.target.closest('.inv-pill-select')) return;
            closeAll();
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') closeAll();
        });
    }

    global.InventoryPillSelect = {
        enhance: enhanceSelect,
        enhanceAll,
        sync: (select) => {
            const wrap = select && select.closest('.inv-pill-select');
            if (wrap) syncTrigger(wrap);
        },
    };
})(window);
