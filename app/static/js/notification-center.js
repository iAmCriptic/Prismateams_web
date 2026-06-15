/**
 * In-App-Benachrichtigungszentrum (Overlay)
 */
class NotificationCenter {
    constructor() {
        this.panel = document.getElementById('notificationCenterPanel');
        this.backdrop = document.getElementById('notificationCenterBackdrop');
        this.listEl = document.getElementById('notificationCenterList');
        this.badgeEls = document.querySelectorAll('.notification-bell-btn .notification-badge');
        this.pollIntervalMs = 45000;
        this.pollTimer = null;
        this.isOpen = false;

        if (!this.panel || !this.listEl) {
            return;
        }

        this.bindEvents();
        this.refreshBadge();
        this.pollTimer = setInterval(() => this.refreshBadge(), this.pollIntervalMs);
    }

    bindEvents() {
        document.querySelectorAll('.notification-bell-btn').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.toggle();
            });
        });

        document.getElementById('notificationCenterClose')?.addEventListener('click', () => this.close());
        this.backdrop?.addEventListener('click', () => this.close());

        document.getElementById('notificationMarkAllRead')?.addEventListener('click', () => this.markAllRead());
        document.getElementById('notificationDeleteAll')?.addEventListener('click', () => this.deleteAll());

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) {
                this.close();
            }
        });
    }

    async apiFetch(url, options = {}) {
        const response = await fetch(url, {
            credentials: 'include',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                ...(options.headers || {}),
            },
            ...options,
        });
        return response;
    }

    updateBadge(count) {
        this.badgeEls.forEach((el) => {
            if (count > 0) {
                el.textContent = count > 99 ? '99+' : String(count);
                el.classList.remove('d-none');
            } else {
                el.classList.add('d-none');
            }
        });
    }

    async refreshBadge() {
        try {
            const res = await this.apiFetch('/api/notifications/pending?limit=1');
            if (!res.ok) return;
            const data = await res.json();
            if (data.success) {
                this.updateBadge(data.unread_count || 0);
            }
        } catch (e) {
            console.warn('Benachrichtigungs-Badge konnte nicht geladen werden:', e);
        }
    }

    async loadList() {
        this.listEl.innerHTML = `
            <div class="text-center text-muted py-4">
                <span class="spinner-border spinner-border-sm me-2" role="status"></span>
                Laden...
            </div>`;

        try {
            const res = await this.apiFetch('/api/notifications/pending?limit=50');
            const data = await res.json();
            if (!data.success) {
                throw new Error(data.error || 'Laden fehlgeschlagen');
            }
            this.updateBadge(data.unread_count || 0);
            this.renderList(data.items || []);
        } catch (e) {
            this.listEl.innerHTML = `<div class="notification-center-empty text-danger">${e.message}</div>`;
        }
    }

    formatTime(iso) {
        if (!iso) return '';
        try {
            const d = new Date(iso);
            const now = new Date();
            const diffMs = now - d;
            const diffMin = Math.floor(diffMs / 60000);
            if (diffMin < 1) return 'Gerade eben';
            if (diffMin < 60) return `vor ${diffMin} Min.`;
            const diffH = Math.floor(diffMin / 60);
            if (diffH < 24) return `vor ${diffH} Std.`;
            return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
        } catch {
            return '';
        }
    }

    renderList(items) {
        if (!items.length) {
            this.listEl.innerHTML = '<div class="notification-center-empty"><i class="bi bi-bell-slash fs-3 d-block mb-2"></i>Keine neuen Benachrichtigungen</div>';
            return;
        }

        this.listEl.innerHTML = items.map((item) => `
            <div class="notification-item unread" data-id="${item.id}" data-url="${this.escapeAttr(item.url || '/')}">
                <div class="notification-item-icon">
                    <i class="bi ${item.icon_class || 'bi-bell'}"></i>
                </div>
                <div class="notification-item-content">
                    <div class="notification-item-title">${this.escapeHtml(item.title)}</div>
                    <div class="notification-item-body">${this.escapeHtml(item.body)}</div>
                    <div class="notification-item-time">${this.formatTime(item.sent_at)}</div>
                </div>
                <div class="notification-item-actions">
                    <button type="button" class="btn btn-sm btn-outline-secondary" data-action="read" data-id="${item.id}" title="Als gelesen markieren">
                        <i class="bi bi-check2"></i>
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-danger" data-action="delete" data-id="${item.id}" title="Löschen">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </div>
        `).join('');

        this.listEl.querySelectorAll('.notification-item').forEach((row) => {
            row.addEventListener('click', (e) => {
                if (e.target.closest('[data-action]')) return;
                const url = row.dataset.url;
                const id = row.dataset.id;
                this.markRead(id, false).then(() => {
                    if (url) window.location.href = url;
                });
            });
        });

        this.listEl.querySelectorAll('[data-action="read"]').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.markRead(btn.dataset.id);
            });
        });

        this.listEl.querySelectorAll('[data-action="delete"]').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.deleteOne(btn.dataset.id);
            });
        });
    }

    escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = str || '';
        return d.innerHTML;
    }

    escapeAttr(str) {
        return String(str || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    open() {
        this.isOpen = true;
        this.panel.classList.remove('d-none');
        this.backdrop?.classList.remove('d-none');
        document.body.style.overflow = 'hidden';
        this.loadList();
    }

    close() {
        this.isOpen = false;
        this.panel.classList.add('d-none');
        this.backdrop?.classList.add('d-none');
        document.body.style.overflow = '';
    }

    toggle() {
        if (this.isOpen) {
            this.close();
        } else {
            this.open();
        }
    }

    async markRead(id, reload = true) {
        const res = await this.apiFetch(`/api/notifications/mark-read/${id}`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            this.updateBadge(data.unread_count ?? 0);
            if (reload) await this.loadList();
        }
    }

    async markAllRead() {
        const res = await this.apiFetch('/api/notifications/mark-all-read', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            this.updateBadge(0);
            await this.loadList();
        }
    }

    async deleteOne(id) {
        const res = await this.apiFetch(`/api/notifications/${id}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.success) {
            this.updateBadge(data.unread_count ?? 0);
            await this.loadList();
        }
    }

    async deleteAll() {
        if (!confirm('Alle Benachrichtigungen wirklich löschen?')) return;
        const res = await this.apiFetch('/api/notifications/delete-all', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            this.updateBadge(0);
            await this.loadList();
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('notificationCenterPanel')) {
        window.notificationCenter = new NotificationCenter();
    }
});
