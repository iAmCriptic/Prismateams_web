/**
 * Pill-Select: ersetzt native <select>-Popups durch Pill-Dropdowns.
 * Native <select> bleibt im DOM (Form-Submit / Change-Events).
 *
 * Optionale data-Attribute pro <option>:
 *   data-badge="98%"   — Badge-Text
 *   data-percent="98"  — 0–100 für rot→grün Hintergrund
 *   data-grade="full"  — Fallback-Stufe (full|high|mid|low)
 */
(function (global) {
    const CLOSE_ATTR = 'data-mod-pill-select-close';

    function optionBaseLabel(opt) {
        if (!opt) return '';
        const raw = (opt.textContent || '').trim();
        if (opt.dataset && opt.dataset.badge) {
            return raw.replace(/\s*\([^)]*\)\s*$/, '').trim() || raw;
        }
        return raw;
    }

    function badgeHue(percent) {
        const p = Math.max(0, Math.min(100, Number(percent) || 0));
        // 0% → rot (0), 100% → grün (120)
        return Math.round(p * 1.2);
    }

    function applyBadgeColor(el, opt) {
        if (!el || !opt || !opt.dataset) return;
        const percentRaw = opt.dataset.percent;
        if (percentRaw !== undefined && percentRaw !== '') {
            const percent = Number(percentRaw);
            if (!Number.isNaN(percent)) {
                el.style.setProperty('--pill-badge-hue', String(badgeHue(percent)));
                el.removeAttribute('data-grade');
                return;
            }
        }
        if (opt.dataset.grade) {
            el.dataset.grade = opt.dataset.grade;
        }
    }

    function buildLabelContent(container, opt) {
        container.textContent = '';
        if (!opt) {
            container.textContent = '—';
            return;
        }

        const name = document.createElement('span');
        name.className = 'mod-pill-select__option-label';
        name.textContent = optionBaseLabel(opt) || '—';
        container.appendChild(name);

        const badgeText = opt.dataset && opt.dataset.badge;
        if (badgeText) {
            const badge = document.createElement('span');
            badge.className = 'mod-pill-select__badge';
            badge.textContent = badgeText;
            applyBadgeColor(badge, opt);
            container.appendChild(badge);
        }
    }

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
            btn.className = 'mod-pill-select__option';
            btn.dataset.index = String(index);
            buildLabelContent(btn, opt);
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
        const opt = select.options[select.selectedIndex];
        if (opt && opt.dataset && opt.dataset.badge) {
            buildLabelContent(label, opt);
        } else {
            label.textContent = selectedLabel(select) || '—';
        }
        label.classList.toggle('is-placeholder', isPlaceholderSelected(select));
        if (wrap.classList.contains('is-open')) {
            rebuildMenu(wrap);
            positionMenu(wrap);
        }
    }

    function positionMenu(wrap) {
        const trigger = wrap._invTrigger;
        const menu = wrap._invMenu;
        if (!trigger || !menu) return;

        const rect = trigger.getBoundingClientRect();
        const menuHeight = Math.min(menu.scrollHeight || 260, window.innerHeight * 0.5);
        const spaceBelow = window.innerHeight - rect.bottom - 8;
        const openUp = spaceBelow < Math.min(menuHeight, 160) && rect.top > spaceBelow;

        menu.style.position = 'fixed';
        menu.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - rect.width - 8)) + 'px';
        menu.style.width = Math.max(rect.width, 10) + 'px';
        menu.style.right = 'auto';
        menu.style.zIndex = '2000';

        if (openUp) {
            menu.style.top = 'auto';
            menu.style.bottom = (window.innerHeight - rect.top + 6) + 'px';
            menu.style.maxHeight = Math.min(16 * 16, rect.top - 12) + 'px';
        } else {
            menu.style.bottom = 'auto';
            menu.style.top = (rect.bottom + 6) + 'px';
            menu.style.maxHeight = Math.min(16 * 16, spaceBelow - 4) + 'px';
        }
    }

    function onViewportChange() {
        document.querySelectorAll('.mod-pill-select.is-open').forEach(positionMenu);
    }

    function closeMenu(wrap) {
        if (!wrap) return;
        wrap.classList.remove('is-open');
        const menu = wrap._invMenu;
        const trigger = wrap._invTrigger;
        if (trigger) trigger.setAttribute('aria-expanded', 'false');
        if (!menu) return;
        menu.hidden = true;
        // Zurück in den Wrap, damit Soft-Reload/Cleanup sauber bleibt
        if (menu.parentElement !== wrap && wrap.isConnected) {
            wrap.appendChild(menu);
        }
        menu.style.position = '';
        menu.style.top = '';
        menu.style.bottom = '';
        menu.style.left = '';
        menu.style.right = '';
        menu.style.width = '';
        menu.style.maxHeight = '';
        menu.style.zIndex = '';
    }

    function closeAll(except) {
        document.querySelectorAll('.mod-pill-select.is-open').forEach((wrap) => {
            if (wrap !== except) closeMenu(wrap);
        });
    }

    function openMenu(wrap) {
        closeAll(wrap);
        rebuildMenu(wrap);
        wrap.classList.add('is-open');
        const menu = wrap._invMenu;
        const trigger = wrap._invTrigger;
        if (trigger) trigger.setAttribute('aria-expanded', 'true');
        if (!menu) return;
        // Ans body hängen, damit overflow:hidden Eltern das Menü nicht abschneiden
        document.body.appendChild(menu);
        menu.hidden = false;
        positionMenu(wrap);
    }

    function enhanceSelect(select) {
        if (!select || select.dataset.pillEnhanced === '1') return select.closest('.mod-pill-select');
        if (select.multiple || select.size > 1) return null;

        select.dataset.pillEnhanced = '1';

        const wrap = document.createElement('div');
        wrap.className = 'mod-pill-select';
        wrap.dataset.invPillSelect = '1';

        const trigger = document.createElement('button');
        trigger.type = 'button';
        trigger.className = 'mod-pill-select__trigger';
        trigger.setAttribute('aria-haspopup', 'listbox');
        trigger.setAttribute('aria-expanded', 'false');

        const label = document.createElement('span');
        label.className = 'mod-pill-select__label';

        const chevron = document.createElement('i');
        chevron.className = 'bi bi-chevron-down mod-pill-select__chevron';
        chevron.setAttribute('aria-hidden', 'true');

        trigger.appendChild(label);
        trigger.appendChild(chevron);

        const menu = document.createElement('div');
        menu.className = 'mod-pill-select__menu';
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
            if (wrap.classList.contains('is-open')) closeMenu(wrap);
            else openMenu(wrap);
        });

        select.addEventListener('change', () => syncTrigger(wrap));

        const mo = new MutationObserver(() => syncTrigger(wrap));
        mo.observe(select, { childList: true, subtree: true, characterData: true, attributes: true });
        wrap._invObserver = mo;

        syncTrigger(wrap);
        return wrap;
    }

    function enhanceAll(root) {
        const scope = root || document;
        scope.querySelectorAll('select.form-select').forEach((select) => {
            if (select.closest('.mod-pill-select')) {
                const wrap = select.closest('.mod-pill-select');
                if (wrap && wrap._invSelect) syncTrigger(wrap);
                return;
            }
            enhanceSelect(select);
        });
    }

    function enhanceMarked(root) {
        const scope = root || document;
        scope.querySelectorAll('select[data-mod-pill-select]').forEach((select) => {
            if (select.closest('.mod-pill-select')) {
                const wrap = select.closest('.mod-pill-select');
                if (wrap && wrap._invSelect) syncTrigger(wrap);
                return;
            }
            enhanceSelect(select);
        });
    }

    if (!document[CLOSE_ATTR]) {
        document[CLOSE_ATTR] = true;
        document.addEventListener('click', (event) => {
            const t = event.target;
            if (t.closest && t.closest('.mod-pill-select')) return;
            if (t.closest && t.closest('.mod-pill-select__menu')) return;
            closeAll();
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') closeAll();
        });
        window.addEventListener('resize', onViewportChange, { passive: true });
        window.addEventListener('scroll', onViewportChange, { passive: true, capture: true });
    }

    global.InventoryPillSelect = {
        enhance: enhanceSelect,
        enhanceAll,
        enhanceMarked,
        sync: (select) => {
            const wrap = select && select.closest('.mod-pill-select');
            if (wrap) syncTrigger(wrap);
        },
    };
})(window);
