/**
 * Chat navigation: pin + full chat actions (desktop context menu + mobile long-press sheet).
 */
(function () {
    'use strict';

    const LONG_PRESS_MS = 520;
    const MOVE_CANCEL_PX = 12;

    function config() {
        return window.ChatNavConfig || {};
    }

    function i18n() {
        return config().i18n || {};
    }

    function pinUrl(chatId) {
        const tpl = config().pinUrlTemplate || '/chat/api/pin/0';
        return String(tpl).replace(/\/0(?=\/?$)/, '/' + chatId);
    }

    function showError(msg) {
        if (window.showAppBanner) {
            window.showAppBanner(msg, 'warning');
            return;
        }
        alert(msg);
    }

    function isMuted(chatId) {
        return localStorage.getItem('chat_' + chatId + '_notifications_muted') === 'true';
    }

    function currentOpenNavId() {
        if (!window.ChatPageConfig || window.ChatPageConfig.chatId == null) return null;
        return String(window.ChatPageConfig.chatId);
    }

    function syncMuteLabels(root) {
        const scope = root || document;
        scope.querySelectorAll('[data-chat-nav-action="mute"]').forEach(function (el) {
            const chatId = el.getAttribute('data-chat-id');
            if (!chatId) return;
            const muted = isMuted(chatId);
            const icon = el.querySelector('.chat-nav-mute-icon');
            const label = el.querySelector('.chat-nav-mute-label');
            if (icon) icon.className = 'bi ' + (muted ? 'bi-bell-slash' : 'bi-bell') + ' me-2 chat-nav-mute-icon';
            if (label) {
                label.textContent = muted
                    ? (i18n().unmute || 'Benachrichtigungen aktivieren')
                    : (i18n().mute || 'Benachrichtigungen stummschalten');
            }
        });
    }

    function updatePinUi(chatId, pinned) {
        const wraps = document.querySelectorAll('.chat-nav-item-wrap[data-chat-id="' + chatId + '"]');
        wraps.forEach(function (wrap) {
            wrap.setAttribute('data-pinned', pinned ? '1' : '0');
            const item = wrap.querySelector('.chat-nav-item');
            if (item) {
                item.classList.toggle('chat-nav-item--pinned', !!pinned);
            }

            let badge = wrap.querySelector('.chat-nav-pin-badge');
            const avatarWrap = wrap.querySelector('.chat-nav-avatar-wrap');
            if (pinned && !badge && avatarWrap) {
                badge = document.createElement('span');
                badge.className = 'chat-nav-pin-badge';
                badge.setAttribute('aria-hidden', 'true');
                badge.innerHTML = '<i class="bi bi-pin-angle-fill"></i>';
                avatarWrap.insertBefore(badge, avatarWrap.firstChild);
            } else if (!pinned && badge) {
                badge.remove();
            }

            const toggle = wrap.querySelector('.chat-nav-pin-toggle');
            if (toggle) {
                const icon = toggle.querySelector('i');
                const span = toggle.querySelector('span');
                if (icon) {
                    icon.className = 'bi bi-pin-angle' + (pinned ? '-fill' : '') + ' me-2';
                }
                if (span) {
                    span.textContent = pinned ? (i18n().unpin || 'Lösen') : (i18n().pin || 'Anpinnen');
                }
            }
        });
    }

    async function togglePin(chatId) {
        if (!chatId) return;
        try {
            const res = await fetch(pinUrl(chatId), {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin',
            });
            const data = await res.json().catch(function () { return {}; });
            if (!res.ok || !data.success) {
                showError(data.error || i18n().pinError || i18n().pinLimit || 'Pin fehlgeschlagen.');
                return;
            }
            updatePinUi(chatId, !!data.pinned);
            window.location.reload();
        } catch (err) {
            showError(i18n().pinError || 'Pin fehlgeschlagen.');
        }
    }

    window.toggleChatPin = togglePin;

    async function toggleMute(chatId, navId) {
        if (!chatId) return;
        const openId = currentOpenNavId();
        if (openId && String(navId || chatId) === openId && typeof window.toggleNotifications === 'function') {
            window.toggleNotifications();
            syncMuteLabels();
            return;
        }

        const nextMuted = !isMuted(chatId);
        localStorage.setItem('chat_' + chatId + '_notifications_muted', nextMuted ? 'true' : 'false');
        try {
            await fetch('/api/notifications/chat/' + chatId, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: JSON.stringify({ enabled: !nextMuted }),
            });
        } catch (e) {
            console.error(e);
        }
        syncMuteLabels();
    }

    function openChatAction(viewUrl, action) {
        if (!viewUrl) return;
        const url = new URL(viewUrl, window.location.origin);
        url.searchParams.set('action', action);
        window.location.href = url.pathname + url.search + url.hash;
    }

    function runInfoOrMembers(action, navId, viewUrl) {
        const openId = currentOpenNavId();
        if (openId && String(navId) === openId) {
            if (action === 'info' && typeof window.showChatInfoModal === 'function') {
                window.showChatInfoModal();
                return;
            }
            if (action === 'members' && typeof window.showAllMembersModal === 'function') {
                window.showAllMembersModal();
                return;
            }
        }
        openChatAction(viewUrl, action);
    }

    async function deleteChatNav(chatId) {
        if (!chatId) return;
        if (typeof window.deleteChat === 'function') {
            window.deleteChat(chatId);
            return;
        }
        if (!confirm(i18n().deleteConfirm || 'Möchten Sie diesen Chat wirklich löschen?')) return;
        try {
            const response = await fetch('/chat/' + chatId + '/delete', {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            });
            if (response.ok) window.location.href = '/chat/';
        } catch (e) {
            showError(i18n().pinError || 'Löschen fehlgeschlagen.');
        }
    }

    function handleNavAction(el) {
        const action = el.getAttribute('data-chat-nav-action');
        const chatId = el.getAttribute('data-chat-id');
        const navId = el.getAttribute('data-nav-id');
        const viewUrl = el.getAttribute('data-view-url');
        if (action === 'mute') {
            toggleMute(chatId, navId);
            return;
        }
        if (action === 'info' || action === 'members') {
            runInfoOrMembers(action, navId, viewUrl);
            return;
        }
        if (action === 'delete') {
            deleteChatNav(chatId);
        }
    }

    function onMenuClick(e) {
        const pinToggle = e.target.closest('.chat-nav-pin-toggle');
        if (pinToggle) {
            e.preventDefault();
            e.stopPropagation();
            togglePin(pinToggle.getAttribute('data-chat-id'));
            closeMobileSheet();
            return;
        }

        const actionEl = e.target.closest('.chat-nav-action');
        if (actionEl) {
            e.preventDefault();
            e.stopPropagation();
            handleNavAction(actionEl);
            closeMobileSheet();
        }
    }

    let mobileSheet = null;

    function closeMobileSheet() {
        if (mobileSheet) {
            mobileSheet.remove();
            mobileSheet = null;
        }
    }

    function showMobileActionSheet(wrap) {
        if (!wrap) return;
        closeMobileSheet();
        syncMuteLabels(wrap);

        const source = wrap.querySelector('.context-menu-source .dropdown-menu');
        if (!source) return;

        const backdrop = document.createElement('div');
        backdrop.className = 'chat-nav-sheet-backdrop';
        const sheet = document.createElement('div');
        sheet.className = 'chat-nav-sheet';
        sheet.setAttribute('role', 'menu');

        const menu = source.cloneNode(true);
        menu.classList.add('show');
        menu.classList.remove('dropdown-menu-end');
        menu.style.position = 'static';
        menu.style.display = 'block';
        menu.style.transform = 'none';
        menu.style.minWidth = '100%';
        menu.style.boxShadow = 'none';
        menu.style.border = 'none';
        menu.style.background = 'transparent';

        sheet.appendChild(menu);
        backdrop.appendChild(sheet);
        document.body.appendChild(backdrop);
        mobileSheet = backdrop;
        syncMuteLabels(sheet);

        backdrop.addEventListener('click', function (ev) {
            if (ev.target === backdrop) closeMobileSheet();
        });
    }

    function bindLongPress() {
        let timer = null;
        let startX = 0;
        let startY = 0;
        let activeWrap = null;
        let suppressClickUntil = 0;

        function clearTimer() {
            if (timer) {
                clearTimeout(timer);
                timer = null;
            }
            activeWrap = null;
        }

        document.addEventListener('touchstart', function (e) {
            const wrap = e.target.closest('.chat-nav-item-wrap');
            if (!wrap) return;
            if (window.matchMedia('(pointer: fine) and (min-width: 768px)').matches) return;
            const touch = e.touches[0];
            if (!touch) return;
            activeWrap = wrap;
            startX = touch.clientX;
            startY = touch.clientY;
            timer = setTimeout(function () {
                const target = activeWrap;
                clearTimer();
                suppressClickUntil = Date.now() + 800;
                showMobileActionSheet(target);
            }, LONG_PRESS_MS);
        }, { passive: true });

        document.addEventListener('touchmove', function (e) {
            if (!timer || !activeWrap) return;
            const touch = e.touches[0];
            if (!touch) return;
            if (Math.abs(touch.clientX - startX) > MOVE_CANCEL_PX || Math.abs(touch.clientY - startY) > MOVE_CANCEL_PX) {
                clearTimer();
            }
        }, { passive: true });

        document.addEventListener('touchend', clearTimer, { passive: true });
        document.addEventListener('touchcancel', clearTimer, { passive: true });

        document.addEventListener('click', function (e) {
            if (Date.now() < suppressClickUntil && e.target.closest('.chat-nav-item')) {
                e.preventDefault();
                e.stopPropagation();
            }
        }, true);
    }

    function handlePendingAction() {
        const params = new URLSearchParams(window.location.search);
        const action = params.get('action');
        if (!action) return;

        var tries = 0;
        function run() {
            tries += 1;
            var ready =
                (action === 'info' && typeof window.showChatInfoModal === 'function') ||
                (action === 'members' && typeof window.showAllMembersModal === 'function') ||
                (action === 'mute' && typeof window.toggleNotifications === 'function');

            if (!ready && tries < 40) {
                setTimeout(run, 50);
                return;
            }

            if (action === 'info' && typeof window.showChatInfoModal === 'function') {
                window.showChatInfoModal();
            } else if (action === 'members' && typeof window.showAllMembersModal === 'function') {
                window.showAllMembersModal();
            } else if (action === 'mute' && typeof window.toggleNotifications === 'function') {
                window.toggleNotifications();
            }
            params.delete('action');
            const next = params.toString();
            const clean = window.location.pathname + (next ? '?' + next : '') + window.location.hash;
            window.history.replaceState({}, '', clean);
        }

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', function () {
                setTimeout(run, 50);
            });
        } else {
            setTimeout(run, 50);
        }
    }

    // Keep mute labels fresh when context menu opens (cloned after right-click)
    document.addEventListener('contextmenu', function (e) {
        const wrap = e.target.closest('.chat-nav-item-wrap');
        if (wrap) syncMuteLabels(wrap);
        setTimeout(function () {
            const floating = document.getElementById('prismateams-context-menu');
            if (floating) syncMuteLabels(floating);
        }, 0);
    }, true);

    document.addEventListener('click', onMenuClick);
    bindLongPress();
    syncMuteLabels();
    handlePendingAction();
})();
