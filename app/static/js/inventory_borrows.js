/** Ausleih-Übersicht. */
/* global fetchInventoryApi */

// Borrows Manager - Verwaltet die Ausleih-Übersicht
class BorrowsManager {
    constructor() {
        this.borrows = [];
        this.filteredBorrows = [];
    }

    getFilterEls(key) {
        return Array.from(document.querySelectorAll(`[data-inv-filter="${key}"]`));
    }

    getFilterValue(key) {
        const els = this.getFilterEls(key);
        if (!els.length) return '';
        if (els[0].type === 'checkbox') {
            return els.some((el) => el.checked);
        }
        return els[0]?.value || '';
    }

    setFilterValue(key, value) {
        this.getFilterEls(key).forEach((el) => {
            if (el.type === 'checkbox') {
                el.checked = !!value;
            } else {
                el.value = value;
                if (window.InventoryPillSelect) {
                    window.InventoryPillSelect.sync(el);
                }
            }
        });
    }
    
    async init() {
        this.setupFilterListeners();
        if (window.InventoryPillSelect) {
            window.InventoryPillSelect.enhanceAll(document);
        }
        await this.loadBorrows();
        this.renderBorrows();
        setInterval(() => this.loadBorrows(), 30000);
    }

    setupFilterListeners() {
        const textKeys = ['filterBorrower', 'filterEvent', 'filterProduct', 'filterDateFrom', 'filterDateTo'];
        textKeys.forEach((key) => {
            this.getFilterEls(key).forEach((el) => {
                el.addEventListener('input', () => {
                    this.getFilterEls(key).forEach((other) => {
                        if (other !== el) other.value = el.value;
                    });
                    this.applyFilters();
                });
            });
        });

        this.getFilterEls('filterStatus').forEach((el) => {
            el.addEventListener('change', () => {
                this.setFilterValue('filterStatus', el.value || 'all');
                this.applyFilters();
            });
        });

        this.getFilterEls('filterMine').forEach((el) => {
            el.addEventListener('change', () => {
                this.setFilterValue('filterMine', el.checked);
                this.applyFilters();
            });
        });
    }
    
    async loadBorrows() {
        try {
            const response = await fetchInventoryApi('/borrows?status=all');
            if (response.ok) {
                this.borrows = await response.json();
                this.applyFilters();
            } else {
                console.error('Fehler beim Laden der Ausleihen');
            }
        } catch (error) {
            console.error('Fehler beim Laden der Ausleihen:', error);
        }
    }
    
    applyFilters() {
        const borrowerFilter = (this.getFilterValue('filterBorrower') || '').toLowerCase();
        const eventFilter = (this.getFilterValue('filterEvent') || '').toLowerCase();
        const productFilter = (this.getFilterValue('filterProduct') || '').toLowerCase();
        const statusFilter = this.getFilterValue('filterStatus') || 'all';
        const mineOnly = !!this.getFilterValue('filterMine');
        const dateFrom = this.getFilterValue('filterDateFrom') || '';
        const dateTo = this.getFilterValue('filterDateTo') || '';
        const uid = window.currentUserId;
        
        this.filteredBorrows = this.borrows.filter(b => {
            const matchesBorrower = !borrowerFilter ||
                (b.borrower_name && b.borrower_name.toLowerCase().includes(borrowerFilter)) ||
                (b.contact_email && b.contact_email.toLowerCase().includes(borrowerFilter));
            const matchesEvent = !eventFilter ||
                (b.event_name && b.event_name.toLowerCase().includes(eventFilter));
            const matchesProduct = !productFilter ||
                (b.product_name && b.product_name.toLowerCase().includes(productFilter));

            let matchesStatus = true;
            if (statusFilter === 'active') {
                matchesStatus = b.status !== 'returned' && !b.is_overdue;
            } else if (statusFilter === 'overdue') {
                matchesStatus = !!b.is_overdue;
            } else if (statusFilter === 'returned') {
                matchesStatus = b.status === 'returned';
            }

            const matchesMine = !mineOnly || b.borrower_id === uid || b.created_by === uid;

            let matchesDate = true;
            if (dateFrom || dateTo) {
                const d = b.borrow_date ? b.borrow_date.substring(0, 10) : '';
                if (dateFrom && d && d < dateFrom) matchesDate = false;
                if (dateTo && d && d > dateTo) matchesDate = false;
            }

            return matchesBorrower && matchesEvent && matchesProduct && matchesStatus && matchesMine && matchesDate;
        });
        
        this.renderBorrows();
    }
    
    renderBorrows() {
        const tbody = document.getElementById('borrowsTableBody');
        const countBadge = document.getElementById('borrowsCount');
        
        if (countBadge) {
            countBadge.textContent = this.filteredBorrows.length;
        }
        
        if (!tbody) return;
        
        if (this.filteredBorrows.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="8">
                        <div class="mod-empty-state py-5 text-center">
                            <i class="bi bi-clock-history d-block mb-2 fs-3 text-muted" aria-hidden="true"></i>
                            <p class="text-muted mb-0">Keine Ausleihen gefunden</p>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }
        
        tbody.innerHTML = this.filteredBorrows.map(borrow => {
            let statusBadge = '<span class="badge bg-warning text-dark">Aktiv</span>';
            if (borrow.status === 'returned') {
                statusBadge = '<span class="badge bg-secondary">Zurückgegeben</span>';
            } else if (borrow.is_overdue) {
                statusBadge = '<span class="badge bg-danger">Überfällig</span>';
            }
            const checkoutId = borrow.checkout_id || borrow.id;
            const isReturned = borrow.status === 'returned';
            const borrowPdf = resolveInventoryApiUrl(`/borrow/${checkoutId}/pdf`);
            const returnPdf = resolveInventoryApiUrl(`/borrow/${borrow.id}/return-pdf`);
            const returnHref = `/inventory/checkout?transaction_number=${encodeURIComponent(borrow.transaction_number)}`;

            const hoverReturn = isReturned
                ? `<a class="btn btn-sm btn-link" href="${returnPdf}" title="Rückgabeschein" onclick="event.stopPropagation()">
                        <i class="bi bi-file-earmark-check"></i>
                   </a>`
                : `<a class="btn btn-sm btn-link" href="${returnHref}" title="Zurückgeben" onclick="event.stopPropagation()">
                        <i class="bi bi-arrow-return-left"></i>
                   </a>`;

            const menuReturn = isReturned
                ? `<li><a class="dropdown-item" href="${returnPdf}"><i class="bi bi-file-earmark-check me-2"></i>Rückgabeschein</a></li>`
                : `<li><a class="dropdown-item" href="${returnHref}"><i class="bi bi-arrow-return-left me-2"></i>Zurückgeben</a></li>`;

            const setBadge = borrow.source_set_name
                ? `<span class="badge inventory-set-badge" title="Aus Produktset"><i class="bi bi-collection" aria-hidden="true"></i> Set</span>`
                : '';
            const setDropdown = this.buildBorrowSetDropdown(borrow);
            const isExternal = !borrow.borrower_id;
            const contactEmail = (borrow.contact_email || '').trim();
            let externalBadge = '';
            if (isExternal) {
                const emailEscaped = this.escapeHtml(contactEmail);
                const composeHref = contactEmail
                    ? `/email/compose?to=${encodeURIComponent(contactEmail)}`
                    : '';
                const menuWidthStyle = contactEmail
                    ? `style="min-width: ${Math.max(contactEmail.length + 4, 18)}ch"`
                    : '';
                const dropdownBody = contactEmail
                    ? `<li class="px-3 py-2">
                            <div class="small text-muted mb-1">Kontakt-E-Mail</div>
                            <div class="fw-semibold text-nowrap">${emailEscaped}</div>
                       </li>
                       <li><hr class="dropdown-divider"></li>
                       <li>
                            <a class="dropdown-item" href="${composeHref}">
                                <i class="bi bi-envelope me-2" aria-hidden="true"></i>E-Mail schreiben
                            </a>
                       </li>`
                    : `<li class="px-3 py-2 small text-muted text-nowrap">Keine E-Mail hinterlegt</li>`;
                externalBadge = `
                    <div class="dropdown d-inline-block">
                        <button type="button"
                                class="badge inventory-extern-badge border-0"
                                data-bs-toggle="dropdown"
                                aria-expanded="false"
                                title="Externe Person"
                                onclick="event.stopPropagation()">
                            Extern
                        </button>
                        <ul class="dropdown-menu inventory-actions-menu" ${menuWidthStyle} onclick="event.stopPropagation()">
                            ${dropdownBody}
                        </ul>
                    </div>`;
            }

            return `
            <tr class="mod-list-row ${borrow.is_overdue ? 'table-danger' : ''}">
                <td><code>${this.escapeHtml(borrow.transaction_number || '')}</code></td>
                <td class="d-none d-md-table-cell">${this.escapeHtml(borrow.event_name || '—')}</td>
                <td>
                    <div class="d-flex flex-wrap align-items-center gap-2">
                        <strong>${this.escapeHtml(borrow.product_name || '')}</strong>
                        ${setBadge}
                    </div>
                    ${setDropdown}
                </td>
                <td class="d-none d-md-table-cell">
                    <div class="d-flex flex-wrap align-items-center gap-2">
                        <span>${this.escapeHtml(borrow.borrower_name || 'Unbekannt')}</span>
                        ${externalBadge}
                    </div>
                </td>
                <td class="d-none d-lg-table-cell">${borrow.borrow_date ? new Date(borrow.borrow_date).toLocaleDateString('de-DE') : '—'}</td>
                <td class="d-none d-md-table-cell">${borrow.expected_return_date ? new Date(borrow.expected_return_date).toLocaleDateString('de-DE') : '—'}</td>
                <td>${statusBadge}</td>
                <td class="text-end">
                    <div class="mod-list-actions">
                        <div class="mod-list-hover-actions">
                            ${hoverReturn}
                            <a class="btn btn-sm btn-link" href="${borrowPdf}" title="Ausleihschein" onclick="event.stopPropagation()">
                                <i class="bi bi-file-pdf"></i>
                            </a>
                        </div>
                        <div class="dropdown d-inline-block">
                            <button class="btn btn-sm btn-link" type="button" data-bs-toggle="dropdown" aria-expanded="false" onclick="event.stopPropagation()">
                                <i class="bi bi-three-dots-vertical"></i>
                            </button>
                            <ul class="dropdown-menu dropdown-menu-end inventory-actions-menu">
                                ${menuReturn}
                                <li><a class="dropdown-item" href="${borrowPdf}"><i class="bi bi-file-pdf me-2"></i>Ausleihschein</a></li>
                            </ul>
                        </div>
                    </div>
                </td>
            </tr>`;
        }).join('');
    }

    buildBorrowSetDropdown(borrow) {
        const members = Array.isArray(borrow.source_set_members) ? borrow.source_set_members : [];
        if (!borrow.source_set_name || !members.length) return '';
        const setName = this.escapeHtml(borrow.source_set_name);
        const memberHtml = members.map((member) => {
            const qty = member.quantity && member.quantity > 1
                ? ` <span class="badge bg-secondary">×${this.escapeHtml(String(member.quantity))}</span>`
                : '';
            return `<li><i class="bi bi-box-seam text-muted" aria-hidden="true"></i><span>${this.escapeHtml(member.name || '—')}</span>${qty}</li>`;
        }).join('');
        return `
            <details class="inventory-set-members mt-1">
                <summary class="inventory-set-members-summary">${setName} · Bestandteile</summary>
                <ul class="inventory-set-members-list">${memberHtml}</ul>
            </details>
        `;
    }

    escapeHtml(text) {
        if (text == null) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }
}

window.BorrowsManager = BorrowsManager;
