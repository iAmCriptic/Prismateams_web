/**
 * Desktop custom context menu – mirrors ⋮ dropdowns and page-specific actions.
 */
(function () {
    'use strict';

    const DESKTOP_MQ = window.matchMedia('(pointer: fine) and (min-width: 768px)');

    function i18n() {
        const c = (window.PRISMATEAMS_I18N && window.PRISMATEAMS_I18N.context_menu) || {};
        return {
            copy_info: c.copy_info || 'Infos kopieren',
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

    let activeMenu = null;
    let quillInstance = null;
    const dynamicMatchers = [];

    function isEnabled() {
        return DESKTOP_MQ.matches;
    }

    function closeMenu() {
        if (activeMenu) {
            activeMenu.remove();
            activeMenu = null;
        }
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
        menu.style.position = 'static';
        menu.style.display = 'block';
        menu.style.transform = 'none';
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
            const widgets = (config.enabled_widgets || []).filter((w) => w !== widgetId);
            const save = await fetch('/api/dashboard/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    enabled_widgets: widgets,
                    quick_access_links: config.quick_access_links || []
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

    function wireMenuInteractions(menu, container) {
        menu.querySelectorAll('[data-confirm-delete]').forEach((button) => {
            button.addEventListener('click', function (e) {
                const message =
                    this.getAttribute('data-confirm-delete') ||
                    'Möchten Sie dieses Element wirklich löschen?';
                if (!confirm(message)) e.preventDefault();
            });
        });

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
            const toggle = e.target.closest('.dropdown-submenu > .dropdown-toggle');
            if (toggle) {
                e.preventDefault();
                e.stopPropagation();
                const sub = toggle.parentElement.querySelector(':scope > .dropdown-menu');
                if (sub) {
                    container.querySelectorAll('.dropdown-submenu > .dropdown-menu.show').forEach((m) => {
                        if (m !== sub) m.classList.remove('show');
                    });
                    sub.classList.toggle('show');
                }
                return;
            }
            const item = e.target.closest('a.dropdown-item, button.dropdown-item');
            if (!item) return;
            const copyText = item.getAttribute('data-copy-text');
            if (copyText) {
                e.preventDefault();
                navigator.clipboard.writeText(copyText).catch(() => {});
            }
            if (!item.hasAttribute('data-pt-trigger-click')) {
                setTimeout(closeMenu, 0);
            }
        });
    }

    function showFloatingMenu(clientX, clientY, menu) {
        closeMenu();

        const container = document.createElement(String.fromCharCode(100, 105, 118));
        container.id = 'prismateams-context-menu';
        container.className = 'pt-context-menu';
        container.setAttribute('role', 'menu');
        container.appendChild(menu);
        document.body.appendChild(container);

        wireMenuInteractions(menu, container);

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

        e.preventDefault();
        e.stopPropagation();

        if (menuType === 'quill') {
            if (!quillInstance) return;
            showFloatingMenu(e.clientX, e.clientY, buildQuillMenu());
            return;
        }

        if (menuType === 'dashboard-widget') {
            const widgetId = zone.getAttribute('data-widget-id');
            if (!widgetId) return;
            showFloatingMenu(e.clientX, e.clientY, buildDashboardWidgetMenu(widgetId));
            return;
        }

        const sourceMenu = resolveSourceMenu(zone, menuType);
        if (!sourceMenu || !sourceMenu.children.length) return;

        const menu = prepareClonedMenu(sourceMenu);
        showFloatingMenu(e.clientX, e.clientY, menu);
    }

    document.addEventListener('contextmenu', onContextMenu, true);

    document.addEventListener('click', (e) => {
        if (activeMenu && !activeMenu.contains(e.target)) closeMenu();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeMenu();
    });

    window.addEventListener('resize', closeMenu);
    document.addEventListener('scroll', closeMenu, true);

    DESKTOP_MQ.addEventListener('change', () => closeMenu());

    window.PrismateamsContextMenu = {
        setQuill(q) {
            quillInstance = q;
        },
        close: closeMenu,
        isEnabled,
        registerMatcher(matchFn, buildMenuFn) {
            if (typeof matchFn === 'function' && typeof buildMenuFn === 'function') {
                dynamicMatchers.push({ match: matchFn, build: buildMenuFn });
            }
        }
    };
})();
