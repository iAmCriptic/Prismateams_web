/**
 * Desktop: Rechtsklick-Kontextmenü (fine pointer + ≥768px).
 * Mobile: ⋮-Kebab als Bottom-Sheet (Action Sheet) überall.
 */
(function () {
    'use strict';

    const DESKTOP_MQ = window.matchMedia('(pointer: fine) and (min-width: 768px)');
    /* Bis lg: Grid hat ≥2 Spalten — Sheet statt In-Card-Dropdown (sonst überdecken Nachbarn) */
    const MOBILE_MQ = window.matchMedia('(max-width: 991.98px)');

    function i18n() {
        const c = (window.PRISMATEAMS_I18N && window.PRISMATEAMS_I18N.context_menu) || {};
        return {
            copy_info: c.copy_info || 'Infos kopieren',
            copied: c.copied || 'Kopiert',
            copy_error: c.copy_error || 'Kopieren fehlgeschlagen.',
            dashboard_remove_widget: c.dashboard_remove_widget || 'Widget entfernen',
            dashboard_manage_widgets: c.dashboard_manage_widgets || 'Widgets verwalten',
            format: Object.assign(
                {
                    bold: 'Fett',
                    italic: 'Kursiv',
                    underline: 'Unterstrichen',
                    strike: 'Durchgestrichen',
                    color: 'Textfarbe'
                },
                c.format || {}
            )
        };
    }

    function notifyCopy(message, category) {
        if (typeof window.showAppBanner === 'function') {
            window.showAppBanner(String(message || ''), category || 'success', { timeout: 2500 });
        }
    }

    let activeMenu = null;
    let activeBackdrop = null;
    let quillInstance = null;
    const dynamicMatchers = [];
    let sheetScrollY = 0;
    let sheetTouchMoved = false;

    function isEnabled() {
        return DESKTOP_MQ.matches;
    }

    function isMobileSheetEnabled() {
        return MOBILE_MQ.matches;
    }

    function unlockBodyScroll() {
        if (!document.body.classList.contains('pt-action-sheet-open')) return;
        document.body.classList.remove('pt-action-sheet-open');
        document.body.style.removeProperty('top');
        document.body.style.removeProperty('position');
        document.body.style.removeProperty('width');
        window.scrollTo(0, sheetScrollY);
        sheetScrollY = 0;
    }

    function lockBodyScroll() {
        sheetScrollY = window.scrollY || window.pageYOffset || 0;
        document.body.classList.add('pt-action-sheet-open');
        document.body.style.position = 'fixed';
        document.body.style.top = '-' + sheetScrollY + 'px';
        document.body.style.width = '100%';
    }

    function closeMenu() {
        if (activeMenu) {
            activeMenu.remove();
            activeMenu = null;
        }
        if (activeBackdrop) {
            activeBackdrop.remove();
            activeBackdrop = null;
        }
        unlockBodyScroll();
        sheetTouchMoved = false;
    }

    /** Shift/Ctrl/Cmd + Rechtsklick → natives Browser-Menü (kein Custom-Menü). */
    function isNativeBrowserMenuShortcut(e) {
        return e.shiftKey || e.ctrlKey || e.metaKey;
    }

    function shouldIgnoreTarget(target) {
        if (!target || !target.closest) return true;
        if (target.closest('[data-context-menu="none"]')) return true;
        if (target.closest('.files-dnd-handle')) return true;
        if (target.closest('.pt-context-menu')) return true;

        const editable = target.closest('[contenteditable="true"]');
        if (editable && !editable.classList.contains('ql-editor')) return true;

        const tag = target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
            const zone = target.closest('[data-context-zone]');
            if (!zone || zone.getAttribute('data-context-menu') !== 'quill') return true;
        }
        return false;
    }

    function findZone(target) {
        return target.closest('[data-context-zone]');
    }

    function resolveSourceMenu(zone, menuType) {
        if (menuType === 'dropdown') {
            return zone.querySelector('.dropdown .dropdown-menu') || zone.querySelector('.dropdown-menu');
        }
        if (menuType === 'template') {
            const id = zone.getAttribute('data-context-menu-id');
            let source = id ? document.getElementById(id) : null;
            if (!source) source = zone.querySelector('.context-menu-source');
            if (!source) return null;
            return source.querySelector('.dropdown-menu') || (source.classList.contains('dropdown-menu') ? source : null);
        }
        return null;
    }

    function prepareClonedMenu(sourceMenu) {
        const menu = sourceMenu.cloneNode(true);
        menu.classList.add('show');
        menu.classList.remove('dropdown-menu-end');
        menu.removeAttribute('data-bs-popper');
        menu.removeAttribute('style');
        menu.style.position = 'static';
        menu.style.display = 'block';
        menu.style.transform = 'none';
        menu.style.left = 'auto';
        menu.style.right = 'auto';
        menu.style.inset = 'auto';
        menu.style.width = '100%';
        menu.style.maxWidth = 'none';
        menu.style.minWidth = '0';
        menu.style.margin = '0';
        menu.querySelectorAll('[data-bs-toggle="dropdown"]').forEach((el) => {
            el.removeAttribute('data-bs-toggle');
            el.removeAttribute('data-bs-auto-close');
        });
        menu.querySelectorAll('li').forEach((li) => {
            if (li.classList.contains('disabled')) li.remove();
        });
        return menu;
    }

    function buildMenuFromActions(actions) {
        const menu = document.createElement('ul');
        menu.className = 'dropdown-menu show';
        actions.forEach((action) => {
            if (action.divider) {
                const li = document.createElement('li');
                li.innerHTML = '<hr class="dropdown-divider">';
                menu.appendChild(li);
                return;
            }
            const li = document.createElement('li');
            let el;
            if (action.href) {
                el = document.createElement('a');
                el.href = action.href;
                el.className = 'dropdown-item' + (action.danger ? ' text-danger' : '');
            } else {
                el = document.createElement('button');
                el.type = 'button';
                el.className = 'dropdown-item' + (action.danger ? ' text-danger' : '');
            }
            el.innerHTML =
                (action.icon ? '<i class="bi ' + action.icon + ' me-2"></i>' : '') + (action.label || '');
            el.addEventListener('click', (ev) => {
                ev.stopPropagation();
                closeMenu();
                if (action.href) {
                    window.location.assign(action.href);
                    return;
                }
                ev.preventDefault();
                if (action.triggerClick) {
                    const trigger = document.querySelector(action.triggerClick);
                    if (trigger) trigger.click();
                    return;
                }
                if (action.onClick) action.onClick(ev);
            });
            li.appendChild(el);
            menu.appendChild(li);
        });
        return menu;
    }

    function buildDashboardWidgetMenu(widgetId) {
        const labels = i18n();
        return buildMenuFromActions([
            {
                label: labels.dashboard_remove_widget,
                icon: 'bi-x-circle',
                danger: true,
                onClick: () => removeDashboardWidget(widgetId)
            },
            { divider: true },
            {
                label: labels.dashboard_manage_widgets,
                icon: 'bi-grid',
                href:
                    (document.querySelector('.dashboard-page') &&
                        document.querySelector('.dashboard-page').dataset.dashboardEditUrl) ||
                    '/dashboard/edit'
            }
        ]);
    }

    async function removeDashboardWidget(widgetId) {
        if (!widgetId) return;
        try {
            const res = await fetch('/api/dashboard/config');
            if (!res.ok) throw new Error('load failed');
            const config = await res.json();
            const save = await fetch('/api/dashboard/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    widgets: config.widgets || [],
                    remove_widget_id: widgetId,
                    quick_access_links: config.quick_access_links || [],
                    mobile_nav_slots: config.mobile_nav_slots || undefined
                })
            });
            if (!save.ok) throw new Error('save failed');
            window.location.reload();
        } catch (err) {
            console.error('Widget entfernen fehlgeschlagen:', err);
            const editUrl =
                (document.querySelector('.dashboard-page') &&
                    document.querySelector('.dashboard-page').dataset.dashboardEditUrl) ||
                '/dashboard/edit';
            window.location.href = editUrl;
        }
    }

    function closeSheetFlyout(container) {
        if (!container) return;
        container.classList.remove('pt-context-menu--sheet-subopen');
        container.querySelectorAll(':scope > .pt-sheet-flyout').forEach((el) => el.remove());
        container.querySelectorAll('.dropdown-submenu').forEach((li) => {
            li.classList.remove('is-open');
            const t = li.querySelector(':scope > .dropdown-toggle');
            if (t) t.setAttribute('aria-expanded', 'false');
            const m = li.querySelector(':scope > .dropdown-menu.show');
            if (m) m.classList.remove('show');
        });
    }

    function openSheetFlyout(container, parent, sub) {
        closeSheetFlyout(container);

        const flyout = document.createElement('div');
        flyout.className = 'pt-sheet-flyout';
        flyout.setAttribute('role', 'menu');

        const back = document.createElement('button');
        back.type = 'button';
        back.className = 'pt-sheet-flyout-back';
        back.setAttribute('aria-label', 'Zurück');
        back.innerHTML =
            '<i class="bi bi-chevron-left" aria-hidden="true"></i><span>Zurück</span>';
        back.addEventListener('click', (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            closeSheetFlyout(container);
        });

        const list = sub.cloneNode(true);
        list.classList.add('show');
        list.classList.remove('dropdown-menu-end');
        list.style.position = 'static';
        list.style.display = 'block';
        list.style.transform = 'none';

        flyout.appendChild(back);
        flyout.appendChild(list);
        container.appendChild(flyout);
        container.classList.add('pt-context-menu--sheet-subopen');
        parent.classList.add('is-open');
        const toggle = parent.querySelector(':scope > .dropdown-toggle');
        if (toggle) toggle.setAttribute('aria-expanded', 'true');
    }

    function wireMenuInteractions(menu, container) {
        // data-confirm-delete is handled globally by app.js (ptConfirm modal)

        menu.querySelectorAll('[data-pt-trigger-click]').forEach((button) => {
            button.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const sel = button.getAttribute('data-pt-trigger-click');
                const trigger = sel ? document.querySelector(sel) : null;
                closeMenu();
                if (trigger) trigger.click();
            });
        });

        container.addEventListener('click', (e) => {
            const isSheet = container.classList.contains('pt-context-menu--sheet');

            const toggle = e.target.closest('.dropdown-submenu > .dropdown-toggle');
            if (toggle && container.contains(toggle)) {
                e.preventDefault();
                e.stopPropagation();
                const parent = toggle.closest('.dropdown-submenu');
                const sub = parent && parent.querySelector(':scope > .dropdown-menu');
                if (!sub) return;

                if (isSheet) {
                    if (parent.classList.contains('is-open') && container.classList.contains('pt-context-menu--sheet-subopen')) {
                        closeSheetFlyout(container);
                    } else {
                        openSheetFlyout(container, parent, sub);
                    }
                    return;
                }

                container.querySelectorAll('.dropdown-submenu').forEach((li) => {
                    if (li === parent) return;
                    li.classList.remove('is-open');
                    const m = li.querySelector(':scope > .dropdown-menu.show');
                    if (m) m.classList.remove('show');
                });
                const open = !sub.classList.contains('show');
                sub.classList.toggle('show', open);
                if (parent) parent.classList.toggle('is-open', open);
                return;
            }

            if (e.target.closest('.email-color-swatch')) {
                setTimeout(closeMenu, 0);
                return;
            }

            const item = e.target.closest('a.dropdown-item, button.dropdown-item');
            if (!item) return;
            if (item.classList.contains('dropdown-toggle') && item.closest('.dropdown-submenu')) return;

            const copyText = item.getAttribute('data-copy-text');
            if (copyText) {
                e.preventDefault();
                const successMsg = item.getAttribute('data-copy-success') || i18n().copied;
                navigator.clipboard.writeText(copyText).then(() => {
                    notifyCopy(successMsg, 'success');
                }).catch(() => {
                    notifyCopy(i18n().copy_error, 'danger');
                });
            }
            // Confirm-Dialog braucht den Button noch im DOM (app.js re-click)
            if (
                item.hasAttribute('data-confirm-delete') ||
                item.hasAttribute('data-pt-confirm') ||
                item.hasAttribute('data-pt-trigger-click')
            ) {
                return;
            }
            setTimeout(closeMenu, 0);
        });
    }

    function createMenuContainer(menu, extraClass) {
        const container = document.createElement(String.fromCharCode(100, 105, 118));
        container.id = 'prismateams-context-menu';
        container.className = 'pt-context-menu' + (extraClass ? ' ' + extraClass : '');
        container.setAttribute('role', 'menu');
        container.appendChild(menu);
        document.body.appendChild(container);
        wireMenuInteractions(menu, container);
        return container;
    }

    function showFloatingMenu(clientX, clientY, menu) {
        closeMenu();

        const container = createMenuContainer(menu);
        const maxW = container.offsetWidth;
        const maxH = container.offsetHeight;
        let left = clientX;
        let top = clientY;
        if (left + maxW > window.innerWidth - 8) left = window.innerWidth - maxW - 8;
        if (top + maxH > window.innerHeight - 8) top = window.innerHeight - maxH - 8;
        if (left < 8) left = 8;
        if (top < 8) top = 8;
        container.style.left = left + 'px';
        container.style.top = top + 'px';

        activeMenu = container;
    }

    function showMobileActionSheet(sourceMenu) {
        closeMenu();

        const backdrop = document.createElement(String.fromCharCode(100, 105, 118));
        backdrop.className = 'pt-action-sheet-backdrop';
        sheetTouchMoved = false;

        backdrop.addEventListener(
            'touchstart',
            () => {
                sheetTouchMoved = false;
            },
            { passive: true }
        );
        backdrop.addEventListener(
            'touchmove',
            (e) => {
                sheetTouchMoved = true;
                e.preventDefault();
            },
            { passive: false }
        );
        backdrop.addEventListener('wheel', (e) => e.preventDefault(), { passive: false });
        backdrop.addEventListener('click', () => {
            if (sheetTouchMoved) {
                sheetTouchMoved = false;
                return;
            }
            closeMenu();
        });

        document.body.appendChild(backdrop);
        activeBackdrop = backdrop;

        const menu = prepareClonedMenu(sourceMenu);
        const container = createMenuContainer(menu, 'pt-context-menu--sheet');
        lockBodyScroll();
        activeMenu = container;
    }

    function isKebabToggle(toggle) {
        if (!toggle || !toggle.closest) return false;
        if (toggle.closest('[data-pt-no-action-sheet]')) return false;
        if (toggle.hasAttribute('data-mobile-modal') || toggle.closest('[data-mobile-modal]')) return false;
        if (toggle.closest('.dropdown-submenu')) return false;
        if (toggle.closest('#mobileNav, #desktopSidebar, .navbar')) return false;
        // Offcanvas-Inhalte: Ordner-⋮ sind Edit-Buttons ohne Dropdown — nicht abfangen
        if (toggle.closest('.offcanvas') && !toggle.closest('.dropdown')) return false;
        if (
            toggle.closest(
                '#newDropdown, #newButtonDropdownSidebar, #newButtonDropdownMobile, .files-sidebar-new-menu, .files-mobile-new-menu, .mod-sidebar-new-wrap, .credentials-sidebar-new-menu, .manuals-sidebar-new-menu'
            )
        ) {
            return false;
        }
        if (toggle.id === 'newButton' || toggle.closest('#newButton')) return false;
        if (!toggle.querySelector('.bi-three-dots-vertical, .bi-three-dots')) return false;
        const label = (toggle.textContent || '').replace(/\s+/g, ' ').trim();
        return label.length <= 2;
    }

    function findKebabSourceMenu(toggle) {
        // Template-Quellen (Kontakte / Passwörter / Anleitungen / Inventar) bevorzugen
        const zone = toggle.closest('[data-context-zone][data-context-menu="template"]');
        if (zone) {
            const id = zone.getAttribute('data-context-menu-id');
            let source = id ? document.getElementById(id) : null;
            if (!source) source = zone.querySelector('.context-menu-source');
            if (source) {
                const tmpl =
                    source.querySelector('.dropdown-menu') ||
                    (source.classList.contains('dropdown-menu') ? source : null);
                if (tmpl && tmpl.children.length) return tmpl;
            }
        }

        const dropdown = toggle.closest('.dropdown');
        if (!dropdown) return null;
        const menu =
            dropdown.querySelector(':scope > .dropdown-menu') || dropdown.querySelector('.dropdown-menu');
        return menu && menu.children.length ? menu : null;
    }

    function openKebabActionSheet(toggle, e) {
        const sourceMenu = findKebabSourceMenu(toggle);
        if (!sourceMenu) return false;

        if (e) {
            e.preventDefault();
            e.stopPropagation();
            if (typeof e.stopImmediatePropagation === 'function') e.stopImmediatePropagation();
        }

        toggle.setAttribute('aria-expanded', 'false');
        const dropWrap = toggle.closest('.dropdown');
        if (dropWrap) {
            dropWrap.classList.remove('show');
            const localMenu = dropWrap.querySelector('.dropdown-menu');
            if (localMenu) localMenu.classList.remove('show');
        }

        showMobileActionSheet(sourceMenu);
        return true;
    }

    function onMobileKebabClick(e) {
        if (!isMobileSheetEnabled()) return;
        if (e.button != null && e.button !== 0) return;

        const toggle = e.target.closest(
            '[data-bs-toggle="dropdown"], button.dropdown-toggle, .dropdown > [data-bs-toggle="dropdown"]'
        );
        if (!toggle || !isKebabToggle(toggle)) return;

        openKebabActionSheet(toggle, e);
    }

    /** Fallback: wenn Bootstrap trotzdem öffnen will → Sheet statt In-Card-Dropdown */
    function onBootstrapDropdownShow(e) {
        if (!isMobileSheetEnabled()) return;
        const toggle = e.relatedTarget || e.target;
        if (!toggle || !isKebabToggle(toggle)) return;
        if (!findKebabSourceMenu(toggle)) return;
        e.preventDefault();
        openKebabActionSheet(toggle, null);
    }

    function buildQuillMenu() {
        const menu = document.createElement('ul');
        menu.className = 'dropdown-menu show';
        const labels = i18n().format;
        const items = [
            { key: 'bold', icon: 'bi-type-bold' },
            { key: 'italic', icon: 'bi-type-italic' },
            { key: 'underline', icon: 'bi-type-underline' },
            { key: 'strike', icon: 'bi-type-strikethrough' },
            { key: 'color', icon: 'bi-palette' }
        ];
        items.forEach(({ key, icon }) => {
            const li = document.createElement('li');
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'dropdown-item';
            btn.innerHTML = '<i class="bi ' + icon + ' me-2"></i>' + (labels[key] || key);
            btn.addEventListener('click', (ev) => {
                ev.preventDefault();
                if (!quillInstance) return;
                closeMenu();
                if (key === 'color') {
                    const picker = document.querySelector('#toolbar-container .ql-color .ql-picker-label');
                    if (picker) picker.click();
                    return;
                }
                const current = quillInstance.getFormat();
                quillInstance.format(key, !current[key]);
            });
            li.appendChild(btn);
            menu.appendChild(li);
        });
        return menu;
    }

    function tryDynamicMenu(target, e) {
        for (let i = 0; i < dynamicMatchers.length; i++) {
            const { match, build } = dynamicMatchers[i];
            const el = match(target, e);
            if (!el) continue;
            const actions = build(e, el);
            if (actions && actions.length) {
                return { menu: buildMenuFromActions(actions), zone: el };
            }
        }
        return null;
    }

    function onContextMenu(e) {
        if (!isEnabled()) return;

        if (isNativeBrowserMenuShortcut(e)) return;

        if (shouldIgnoreTarget(e.target)) return;

        const dynamic = tryDynamicMenu(e.target, e);
        if (dynamic) {
            e.preventDefault();
            e.stopPropagation();
            showFloatingMenu(e.clientX, e.clientY, dynamic.menu);
            return;
        }

        const zone = findZone(e.target);
        if (!zone) return;

        const menuType = zone.getAttribute('data-context-menu');
        if (!menuType || menuType === 'none') return;

        if (menuType === 'quill') {
            if (!quillInstance) return;
            e.preventDefault();
            e.stopPropagation();
            showFloatingMenu(e.clientX, e.clientY, buildQuillMenu());
            return;
        }

        if (menuType === 'dashboard-widget') {
            const widgetId = zone.getAttribute('data-widget-id');
            if (!widgetId) return;
            e.preventDefault();
            e.stopPropagation();
            showFloatingMenu(e.clientX, e.clientY, buildDashboardWidgetMenu(widgetId));
            return;
        }

        const sourceMenu = resolveSourceMenu(zone, menuType);
        if (!sourceMenu || !sourceMenu.children.length) return;

        e.preventDefault();
        e.stopPropagation();
        const menu = prepareClonedMenu(sourceMenu);
        showFloatingMenu(e.clientX, e.clientY, menu);
    }

    document.addEventListener('contextmenu', onContextMenu, true);
    // Capture: vor Bootstrap, kein touchend+click-Doppel-Toggle
    document.addEventListener('click', onMobileKebabClick, true);
    document.addEventListener('show.bs.dropdown', onBootstrapDropdownShow, true);

    document.addEventListener('click', (e) => {
        if (!activeMenu) return;
        if (activeMenu.contains(e.target)) return;
        if (activeBackdrop && activeBackdrop.contains(e.target)) return;
        if (activeMenu.classList.contains('pt-context-menu--sheet')) return;
        closeMenu();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeMenu();
    });

    window.addEventListener('resize', closeMenu);
    document.addEventListener(
        'scroll',
        () => {
            if (activeMenu && activeMenu.classList.contains('pt-context-menu--sheet')) return;
            closeMenu();
        },
        true
    );

    DESKTOP_MQ.addEventListener('change', () => closeMenu());
    MOBILE_MQ.addEventListener('change', () => closeMenu());

    window.PrismateamsContextMenu = {
        setQuill(q) {
            quillInstance = q;
        },
        close: closeMenu,
        isEnabled,
        isMobileSheetEnabled,
        showMobileActionSheet,
        registerMatcher(matchFn, buildMenuFn) {
            if (typeof matchFn === 'function' && typeof buildMenuFn === 'function') {
                dynamicMatchers.push({ match: matchFn, build: buildMenuFn });
            }
        }
    };
})();
