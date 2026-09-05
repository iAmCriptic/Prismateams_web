(function () {
  const app = document.getElementById('kanbanBoardApp');
  if (!app || !window.KANBAN_BOARD) return;

  const board = window.KANBAN_BOARD;
  board.lists = board.lists || [];
  board.labels = board.labels || [];
  board.custom_fields = board.custom_fields || [];

  const canEdit = app.dataset.canEdit === '1';
  const canManage = app.dataset.canManage === '1';
  const shareToken = (app.dataset.shareToken || board.share_token || '').trim();
  const isShare = app.dataset.isShare === '1' || Boolean(shareToken);
  const boardId = board.id;
  const i18n = window.KANBAN_I18N || {};
  let currentCardId = null;
  let currentCardDetail = null;
  let checklistItemDueTarget = null;
  let checklistItemAssigneeTarget = null;
  let commentSystem = null;
  let ignoreSSE = false;
  let cardModal = null;
  const sortableInstances = [];

  board.custom_field_categories = board.custom_field_categories || [];

  const listsEl = document.getElementById('kanbanLists');

  function avatarHtml(user, title) {
    if (!user) return '';
    const name = title || user.name || '';
    const url = user.avatar_url || user.profile_picture;
    if (url) {
      return `<img class="kanban-avatar kanban-avatar--img" src="${esc(url)}" alt="" title="${esc(name)}">`;
    }
    return `<span class="kanban-avatar" title="${esc(name)}">${esc(user.initials || '?')}</span>`;
  }

  function labelChipHtml(lb, large) {
    return `<span class="kanban-label-chip${large ? ' kanban-label-chip--lg' : ''}" style="background:${esc(lb.color)}" title="${esc(lb.name || '')}">${esc(lb.name || '')}</span>`;
  }

  function formatDueDisplay(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso).slice(0, 16).replace('T', ' ');
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}, ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function toDatetimeLocalValue(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function renderBoardMembers() {
    const el = document.getElementById('kanbanBoardMembers');
    if (!el) return;
    const members = board.members || [];
    el.innerHTML = members.map((m) => avatarHtml(m)).join('');
  }

  function getModal(elOrId) {
    const el = typeof elOrId === 'string' ? document.getElementById(elOrId) : elOrId;
    if (!el || !window.bootstrap || !bootstrap.Modal) return null;
    return bootstrap.Modal.getOrCreateInstance(el);
  }

  function ensureCardModal() {
    if (!cardModal) cardModal = getModal('kanbanCardModal');
    return cardModal;
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function notify(message, category) {
    const msg = String(message || '');
    if (typeof window.showAppBanner === 'function') {
      window.showAppBanner(msg, category || 'danger');
    } else {
      window.alert(msg);
    }
  }

  async function askConfirm(message, options) {
    if (typeof window.ptConfirm === 'function') {
      return window.ptConfirm(message, options || {});
    }
    return window.confirm(String(message || ''));
  }

  async function askPrompt(message, defaultValue, options) {
    if (typeof window.ptPrompt === 'function') {
      return window.ptPrompt(message, Object.assign({ defaultValue: defaultValue || '' }, options || {}));
    }
    return window.prompt(String(message || ''), defaultValue != null ? String(defaultValue) : '');
  }

  async function api(url, opts) {
    const headers = {
      'Content-Type': 'application/json',
      'X-Requested-With': 'XMLHttpRequest',
      ...((opts && opts.headers) || {}),
    };
    if (shareToken) headers['X-Share-Token'] = shareToken;
    const res = await fetch(url, {
      headers,
      ...opts,
      body: opts && opts.body && typeof opts.body !== 'string'
        ? JSON.stringify(opts.body)
        : (opts && opts.body),
    });
    let data = {};
    try {
      data = await res.json();
    } catch (_) {
      data = {};
    }
    if (!res.ok) {
      const err = new Error((data && data.error) || ('HTTP ' + res.status));
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  function findList(id) {
    return (board.lists || []).find((l) => l.id === id);
  }

  function findCard(id) {
    for (const l of board.lists || []) {
      const c = (l.cards || []).find((x) => x.id === id);
      if (c) return c;
    }
    return null;
  }

  function fieldTypeIcon(type) {
    if (type === 'select') return 'bi-list-ul';
    if (type === 'date') return 'bi-calendar3';
    if (type === 'time') return 'bi-clock';
    if (type === 'checkbox') return 'bi-check2-square';
    return 'bi-fonts';
  }

  function fieldTypeLabel(type) {
    const map = {
      text: i18n.typeText || 'Freitext',
      select: i18n.typeSelect || 'Dropdown',
      date: i18n.typeDate || 'Datum',
      time: i18n.typeTime || 'Uhrzeit',
      checkbox: i18n.typeCheckbox || 'Haken',
    };
    return map[type] || type;
  }

  function customFieldInputHtml(field, value, readonly) {
    const val = value == null ? '' : String(value);
    const ph = esc(field.placeholder || '');
    const disabled = readonly ? 'disabled' : '';
    const data = `data-field-id="${field.id}" data-field-type="${esc(field.field_type)}"`;
    if (field.field_type === 'select') {
      const opts = (field.options || []).map((o) =>
        `<option value="${esc(o)}" ${o === val ? 'selected' : ''}>${esc(o)}</option>`
      ).join('');
      return `<select class="form-select form-select-sm kanban-pill-input" ${data} ${disabled}>
        <option value="">${esc(i18n.customFieldSelect || 'Auswählen …')}</option>
        ${opts}
      </select>`;
    }
    if (field.field_type === 'date') {
      return `<input type="date" class="form-control form-control-sm kanban-pill-input" ${data} value="${esc(val)}" ${disabled}>`;
    }
    if (field.field_type === 'time') {
      return `<input type="time" class="form-control form-control-sm kanban-pill-input" ${data} value="${esc(val)}" ${disabled}>`;
    }
    if (field.field_type === 'checkbox') {
      const checked = val === 'true' || val === '1' ? 'checked' : '';
      return `<input type="checkbox" class="form-check-input" ${data} ${checked} ${disabled}>`;
    }
    return `<input type="text" class="form-control form-control-sm kanban-pill-input" ${data} value="${esc(val)}" placeholder="${ph}" ${disabled} autocomplete="off">`;
  }

  function renderCardCustomFields(card) {
    const section = document.getElementById('cardCustomFields');
    const grid = document.getElementById('cardCustomFieldsGrid');
    const fields = (card && card.custom_fields) || [];
    if (!section || !grid) return;
    section.hidden = false;
    const values = (card && card.custom_field_values) || {};
    const fieldsHtml = fields.length
      ? fields.map((f) => {
          const v = values[String(f.id)] ?? values[f.id] ?? '';
          return `<div class="kanban-custom-field" data-cf-id="${f.id}">
            <label class="kanban-custom-field__label">
              <i class="bi ${fieldTypeIcon(f.field_type)}"></i> ${esc(f.label)}
              ${f.card_id ? `<span class="kanban-cf-local-badge">${esc(i18n.customFieldLocal || 'Nur diese Karte')}</span>` : ''}
            </label>
            <div class="kanban-custom-field__row">
              ${customFieldInputHtml(f, v, !canEdit)}
              ${canEdit ? `<button type="button" class="btn btn-sm kanban-pill-btn kanban-pill-btn--ghost" data-remove-cf="${f.id}" title="${esc(i18n.delete || 'Löschen')}"><i class="bi bi-x-lg"></i></button>` : ''}
            </div>
          </div>`;
        }).join('')
      : `<p class="text-muted small mb-2">${esc(i18n.customFieldCardEmpty || 'Noch keine Felder auf dieser Karte.')}</p>`;
    const actions = canEdit
      ? `<div class="d-flex flex-wrap gap-2 mb-2">
          <button type="button" class="btn btn-sm kanban-pill-btn" id="cardInsertFieldsBtn"><i class="bi bi-plus-lg me-1"></i>${esc(i18n.customFieldInsert || 'Felder einfügen')}</button>
          <button type="button" class="btn btn-sm kanban-pill-btn kanban-pill-btn--ghost" id="cardLocalFieldBtn"><i class="bi bi-input-cursor-text me-1"></i>${esc(i18n.customFieldCreateLocal || 'Feld für diese Karte')}</button>
        </div>`
      : '';
    grid.innerHTML = actions + fieldsHtml;
    if (!canEdit) return;
    grid.querySelectorAll('[data-field-id]').forEach((el) => {
      el.addEventListener('change', () => saveCustomFieldValue(el));
    });
    grid.querySelectorAll('[data-remove-cf]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const fieldId = Number(btn.getAttribute('data-remove-cf'));
        const field = fields.find((f) => f.id === fieldId);
        if (!field) return;
        if (!(await askConfirm(i18n.customFieldRemoveConfirm || 'Feld von Karte entfernen?'))) return;
        try {
          if (field.card_id) {
            const r = await api(`/kanban/api/custom-fields/${fieldId}`, { method: 'DELETE' });
            if (r.card) {
              currentCardDetail = r.card;
              openCard(currentCardId);
            } else {
              openCard(currentCardId);
            }
          } else {
            const r = await api(`/kanban/api/cards/${currentCardId}/custom-fields/enable/${fieldId}`, { method: 'DELETE' });
            if (r.card) {
              currentCardDetail = r.card;
              renderCardCustomFields(r.card);
            }
          }
        } catch (err) {
          notify(err.message || 'Fehler');
        }
      });
    });
    document.getElementById('cardInsertFieldsBtn')?.addEventListener('click', () => openInsertFieldsModal(card));
    document.getElementById('cardLocalFieldBtn')?.addEventListener('click', () => openLocalFieldForm());
  }

  function openInsertFieldsModal(card) {
    const enabled = new Set((card.enabled_field_ids || (card.custom_fields || []).filter((f) => !f.card_id).map((f) => f.id)));
    const cats = board.custom_field_categories || [];
    const fields = board.custom_fields || [];
    const root = document.getElementById('kanbanInsertFieldsList');
    if (!root) return;
    if (!fields.length) {
      root.innerHTML = `<p class="text-muted small">${esc(i18n.customFieldEmpty || 'Noch keine Felder.')}</p>`;
    } else {
      const uncategorized = fields.filter((f) => !f.category_id);
      const blocks = [];
      cats.forEach((cat) => {
        const catFields = fields.filter((f) => f.category_id === cat.id);
        if (!catFields.length) return;
        blocks.push(`<div class="kanban-cf-insert-cat"><div class="kanban-cf-insert-cat__title">${esc(cat.name)}</div>
          ${catFields.map((f) => insertFieldRow(f, enabled.has(f.id))).join('')}</div>`);
      });
      if (uncategorized.length) {
        blocks.push(`<div class="kanban-cf-insert-cat"><div class="kanban-cf-insert-cat__title">${esc(i18n.customFieldUncategorized || 'Ohne Kategorie')}</div>
          ${uncategorized.map((f) => insertFieldRow(f, enabled.has(f.id))).join('')}</div>`);
      }
      root.innerHTML = blocks.join('') || `<p class="text-muted small">${esc(i18n.customFieldEmpty || 'Noch keine Felder.')}</p>`;
    }
    root.querySelectorAll('[data-enable-cf]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        try {
          const r = await api(`/kanban/api/cards/${currentCardId}/custom-fields/enable`, {
            method: 'POST',
            body: { field_id: Number(btn.getAttribute('data-enable-cf')) },
          });
          if (r.card) {
            currentCardDetail = r.card;
            getModal('kanbanInsertFieldsModal')?.hide();
            renderCardCustomFields(r.card);
          }
        } catch (err) {
          notify(err.message || 'Fehler');
        }
      });
    });
    getModal('kanbanInsertFieldsModal')?.show();
  }

  function insertFieldRow(f, already) {
    return `<div class="kanban-cf-insert-row">
      <i class="bi ${fieldTypeIcon(f.field_type)}"></i>
      <span>${esc(f.label)}</span>
      ${already
        ? `<span class="small text-muted">${esc(i18n.customFieldAlready || 'Bereits eingefügt')}</span>`
        : `<button type="button" class="btn btn-sm kanban-pill-btn" data-enable-cf="${f.id}">${esc(i18n.customFieldInsert || 'Einfügen')}</button>`}
    </div>`;
  }

  async function openLocalFieldForm() {
    const label = await askPrompt(i18n.customFieldsLabel || 'Feldname', '', { title: i18n.customFieldCreateLocal || 'Feld für diese Karte' });
    if (label == null || !String(label).trim()) return;
    try {
      const r = await api(`/kanban/api/cards/${currentCardId}/custom-fields`, {
        method: 'POST',
        body: { label: String(label).trim(), field_type: 'text' },
      });
      if (r.card) {
        currentCardDetail = r.card;
        renderCardCustomFields(r.card);
      }
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  }

  async function saveCustomFieldValue(el) {
    if (!currentCardId) return;
    const fieldId = Number(el.getAttribute('data-field-id'));
    const value = el.type === 'checkbox' ? (el.checked ? 'true' : 'false') : el.value;
    try {
      const r = await api(`/kanban/api/cards/${currentCardId}/custom-field-values`, {
        method: 'PUT',
        body: { field_id: fieldId, value },
      });
      if (r.card) {
        currentCardDetail = r.card;
        upsertCardLocal(r.card);
      }
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  }

  function showNewChecklistForm() {
    const clRoot = document.getElementById('cardChecklists');
    if (!clRoot || !currentCardId) return;
    let form = clRoot.querySelector('.kanban-new-checklist-form');
    if (!form) {
      form = document.createElement('form');
      form.className = 'kanban-new-checklist-form kanban-checklist';
      form.innerHTML = `
        <input class="form-control form-control-sm kanban-pill-input" name="title" maxlength="200"
               placeholder="${esc(i18n.checklistName || 'Checklistenname')}" autocomplete="off" required>
        <div class="d-flex gap-2 mt-2">
          <button type="submit" class="btn btn-sm btn-accent kanban-pill-btn">${esc(i18n.add || 'Hinzufügen')}</button>
          <button type="button" class="btn btn-sm kanban-pill-btn kanban-pill-btn--ghost" data-cancel-new-cl>${esc(i18n.cancel || 'Abbrechen')}</button>
        </div>`;
      clRoot.prepend(form);
      form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const titleInput = form.querySelector('input[name=title]');
        const title = (titleInput && titleInput.value || '').trim();
        if (!title) return;
        try {
          await api(`/kanban/api/cards/${currentCardId}/checklists`, { method: 'POST', body: { title } });
          openCard(currentCardId);
        } catch (err) {
          notify(err.message || 'Fehler');
        }
      });
      form.querySelector('[data-cancel-new-cl]')?.addEventListener('click', () => form.remove());
    }
    const input = form.querySelector('input[name=title]');
    if (input) {
      input.focus();
      input.select();
    }
  }

  function setCustomFields(fields) {
    board.custom_fields = fields || [];
    if (currentCardDetail) renderCardCustomFields(currentCardDetail);
  }

  function setCustomFieldCategories(cats) {
    board.custom_field_categories = cats || [];
  }

  function renderCustomFieldsManageList() {
    const root = document.getElementById('kanbanCustomFieldsList');
    const catRoot = document.getElementById('kanbanCfCategoriesList');
    if (catRoot) {
      const cats = board.custom_field_categories || [];
      catRoot.innerHTML = cats.map((c) => `
        <div class="kanban-cf-cat-row" data-cat-id="${c.id}">
          <span class="fw-semibold">${esc(c.name)}</span>
          <button type="button" class="btn btn-sm kanban-pill-btn kanban-pill-btn--ghost" data-del-cat="${c.id}"><i class="bi bi-trash"></i></button>
        </div>`).join('') || `<p class="text-muted small mb-0">${esc(i18n.customFieldNoCategories || 'Noch keine Kategorien.')}</p>`;
      catRoot.querySelectorAll('[data-del-cat]').forEach((btn) => {
        btn.addEventListener('click', async () => {
          if (!(await askConfirm(i18n.customFieldDeleteCategory || 'Kategorie löschen?'))) return;
          try {
            await api(`/kanban/api/custom-field-categories/${btn.getAttribute('data-del-cat')}`, { method: 'DELETE' });
            const r = await api(`/kanban/api/boards/${boardId}/custom-field-categories`);
            setCustomFieldCategories(r.categories || []);
            fillCategorySelect();
            renderCustomFieldsManageList();
          } catch (err) {
            notify(err.message || 'Fehler');
          }
        });
      });
    }
    if (!root) return;
    const fields = board.custom_fields || [];
    const cats = board.custom_field_categories || [];
    const catName = (id) => {
      const c = cats.find((x) => x.id === id);
      return c ? c.name : (i18n.customFieldUncategorized || 'Ohne Kategorie');
    };
    if (!fields.length) {
      root.innerHTML = `<p class="text-muted small mb-0">${esc(i18n.customFieldEmpty || 'Noch keine Felder.')}</p>`;
      return;
    }
    root.innerHTML = fields.map((f) => `
      <div class="kanban-cf-manage-row" data-field-id="${f.id}">
        <i class="bi ${fieldTypeIcon(f.field_type)}"></i>
        <div class="kanban-cf-manage-row__meta">
          <div class="fw-semibold">${esc(f.label)}</div>
          <div class="kanban-cf-manage-row__type">${esc(fieldTypeLabel(f.field_type))} · ${esc(catName(f.category_id))}</div>
        </div>
        <div class="kanban-cf-manage-row__actions">
          <button type="button" class="btn btn-sm kanban-pill-btn" data-edit-cf="${f.id}">${esc(i18n.rename || 'Bearbeiten')}</button>
          <button type="button" class="btn btn-sm kanban-pill-btn kanban-pill-btn--ghost" data-del-cf="${f.id}">${esc(i18n.delete || 'Löschen')}</button>
        </div>
      </div>`).join('');
    root.querySelectorAll('[data-edit-cf]').forEach((btn) => {
      btn.addEventListener('click', () => startCustomFieldEdit(Number(btn.getAttribute('data-edit-cf'))));
    });
    root.querySelectorAll('[data-del-cf]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!(await askConfirm(i18n.customFieldDeleteConfirm || 'Feld löschen?'))) return;
        try {
          const r = await api(`/kanban/api/custom-fields/${btn.getAttribute('data-del-cf')}`, { method: 'DELETE' });
          setCustomFields(r.custom_fields);
          renderCustomFieldsManageList();
        } catch (err) {
          notify(err.message || 'Fehler');
        }
      });
    });
  }

  function fillCategorySelect() {
    const sel = document.getElementById('kanbanCfCategory');
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = `<option value="">${esc(i18n.customFieldUncategorized || 'Ohne Kategorie')}</option>`
      + (board.custom_field_categories || []).map((c) =>
        `<option value="${c.id}">${esc(c.name)}</option>`
      ).join('');
    if (cur) sel.value = cur;
  }

  function resetCustomFieldForm() {
    const form = document.getElementById('kanbanCustomFieldForm');
    if (form) form.reset();
    const idEl = document.getElementById('kanbanCfEditId');
    if (idEl) idEl.value = '';
    const submit = document.getElementById('kanbanCfSubmit');
    if (submit) submit.textContent = i18n.customFieldAdd || 'Hinzufügen';
    document.getElementById('kanbanCfCancelEdit')?.toggleAttribute('hidden', true);
    fillCategorySelect();
    syncCustomFieldOptionsVisibility();
  }

  function startCustomFieldEdit(fieldId) {
    const field = (board.custom_fields || []).find((f) => f.id === fieldId);
    if (!field) return;
    document.getElementById('kanbanCfEditId').value = String(field.id);
    document.getElementById('kanbanCfLabel').value = field.label || '';
    document.getElementById('kanbanCfType').value = field.field_type || 'text';
    document.getElementById('kanbanCfOptions').value = (field.options || []).join('\n');
    fillCategorySelect();
    const catSel = document.getElementById('kanbanCfCategory');
    if (catSel) catSel.value = field.category_id ? String(field.category_id) : '';
    const submit = document.getElementById('kanbanCfSubmit');
    if (submit) submit.textContent = i18n.customFieldSave || 'Speichern';
    document.getElementById('kanbanCfCancelEdit')?.toggleAttribute('hidden', false);
    syncCustomFieldOptionsVisibility();
    document.getElementById('kanbanCfLabel')?.focus();
  }

  function syncCustomFieldOptionsVisibility() {
    const type = document.getElementById('kanbanCfType')?.value;
    const wrap = document.getElementById('kanbanCfOptionsWrap');
    if (wrap) wrap.hidden = type !== 'select';
  }

  function openCustomFieldsModal() {
    renderCustomFieldsManageList();
    resetCustomFieldForm();
    getModal('kanbanCustomFieldsModal')?.show();
  }

  function destroySortables() {
    while (sortableInstances.length) {
      try { sortableInstances.pop().destroy(); } catch (_) { /* ignore */ }
    }
  }

  function cardHtml(card) {
    const labels = (card.labels || []).map((lb) => labelChipHtml(lb)).join('');
    const cover = card.cover && card.cover.is_image
      ? `<div class="kanban-card__cover"><img src="${esc(card.cover.preview_url || card.cover.url)}" alt=""></div>`
      : '';
    const cl = card.checklist || {};
    const meta = [];
    if (card.due_date) meta.push(`<span><i class="bi bi-calendar"></i> ${esc(formatDueDisplay(card.due_date))}</span>`);
    if (cl.total) meta.push(`<span><i class="bi bi-check2-square"></i> ${cl.done}/${cl.total}</span>`);
    if (card.comment_count) meta.push(`<span><i class="bi bi-chat"></i> ${card.comment_count}</span>`);
    if (card.attachment_count) meta.push(`<span><i class="bi bi-paperclip"></i> ${card.attachment_count}</span>`);
    if (card.poll_text || card.vote_count) meta.push(`<span><i class="bi bi-hand-thumbs-up"></i> ${card.vote_count || 0}</span>`);
    const avatars = (card.assignees || []).map((a) => avatarHtml(a)).join('');
    return `<div class="kanban-card${card.completed ? ' is-completed' : ''}" data-card-id="${card.id}" draggable="false">
      ${cover}
      ${labels ? `<div class="kanban-card__labels">${labels}</div>` : ''}
      <div class="kanban-card__title-row">
        <span class="kanban-card__complete-icon" aria-hidden="true"><i class="bi ${card.completed ? 'bi-check-circle-fill' : 'bi-circle'}"></i></span>
        <div class="kanban-card__title">${esc(card.title)}</div>
      </div>
      ${card.poll_text ? `<div class="kanban-card__poll-preview">${esc(card.poll_text)}</div>` : ''}
      <div class="kanban-card__footer">${meta.join('')}<div class="kanban-card__avatars">${avatars}</div></div>
    </div>`;
  }

  function listHtml(list) {
    const cards = (list.cards || []).map(cardHtml).join('');
    const menu = canEdit
      ? `<div class="dropdown kanban-list-menu">
          <button type="button" class="btn btn-sm kanban-pill-btn kanban-pill-btn--ghost" data-bs-toggle="dropdown" data-bs-popper-config='{"strategy":"fixed"}' aria-label="Listenaktionen">
            <i class="bi bi-three-dots"></i>
          </button>
          <ul class="dropdown-menu dropdown-menu-end">
            <li><button type="button" class="dropdown-item" data-list-rename="${list.id}">${esc(i18n.rename || 'Umbenennen')}</button></li>
            <li><button type="button" class="dropdown-item text-danger" data-list-delete="${list.id}">${esc(i18n.delete || 'Löschen')}</button></li>
          </ul>
        </div>`
      : '';
    const footer = canEdit
      ? `<div class="kanban-list-col__footer">
          <button type="button" class="btn kanban-pill-btn w-100 text-start kanban-add-card-btn" data-list-id="${list.id}">
            <i class="bi bi-plus-lg me-1"></i>${esc(i18n.addCard || 'Karte hinzufügen')}
          </button>
          <form class="kanban-add-card-form mt-2" data-list-id="${list.id}" hidden>
            <input class="form-control form-control-sm kanban-pill-input mb-2" name="title" placeholder="${esc(i18n.cardTitle || 'Kartentitel')}" autocomplete="off">
            <div class="d-flex gap-2">
              <button type="submit" class="btn btn-sm btn-accent kanban-pill-btn">${esc(i18n.addCard || 'Hinzufügen')}</button>
              <button type="button" class="btn btn-sm kanban-pill-btn kanban-pill-btn--ghost kanban-cancel-add-card"><i class="bi bi-x-lg"></i></button>
            </div>
          </form>
        </div>`
      : '';
    return `<div class="kanban-list-col" data-list-id="${list.id}">
      <div class="kanban-list-col__head">
        <span class="kanban-list-col__title" data-list-title="${list.id}">${esc(list.title)}</span>
        <span class="kanban-list-col__count">${(list.cards || []).length}</span>
        ${menu}
      </div>
      <div class="kanban-list-col__cards" data-list-cards="${list.id}">${cards}</div>
      ${footer}
    </div>`;
  }

  function addListColumnHtml() {
    if (!canEdit) return '';
    return `<div class="kanban-add-list-wrap" id="kanbanAddListWrap">
      <button type="button" class="btn kanban-add-list-btn" id="kanbanShowAddList">
        <i class="bi bi-plus-lg me-1"></i>${esc(i18n.addList || 'Liste hinzufügen')}
      </button>
      <form class="kanban-add-list-form" id="kanbanAddListForm" hidden>
        <input class="form-control kanban-pill-input" id="kanbanListName" name="title" placeholder="${esc(i18n.listName || 'Listenname')}" autocomplete="off">
        <div class="d-flex gap-2 mt-2">
          <button type="submit" class="btn btn-accent kanban-pill-btn">${esc(i18n.addList || 'Liste hinzufügen')}</button>
          <button type="button" class="btn kanban-pill-btn kanban-pill-btn--ghost" id="kanbanCancelAddList"><i class="bi bi-x-lg"></i></button>
        </div>
      </form>
    </div>`;
  }

  function renderBoard() {
    destroySortables();
    listsEl.innerHTML = (board.lists || []).map(listHtml).join('') + addListColumnHtml();
    bindListInteractions();
    if (typeof applyFilters === 'function') {
      applyFilters();
    }
  }

  function bindListInteractions() {
    if (!canEdit || !window.Sortable) return;
    listsEl.querySelectorAll('[data-list-cards]').forEach((container) => {
      sortableInstances.push(Sortable.create(container, {
        group: 'kanban-cards',
        animation: 200,
        ghostClass: 'opacity-50',
        onEnd: async (evt) => {
          const cardId = Number(evt.item.dataset.cardId);
          const listId = Number(evt.to.dataset.listCards);
          const position = evt.newIndex;
          ignoreSSE = true;
          try {
            const data = await api(`/kanban/api/boards/${boardId}/cards/move`, {
              method: 'POST',
              body: { card_id: cardId, list_id: listId, position },
            });
            if (data.card) upsertCardLocal(data.card);
          } catch (err) {
            notify(err.message || 'Verschieben fehlgeschlagen');
            refreshBoard();
          }
          ignoreSSE = false;
        },
      }));
    });
    sortableInstances.push(Sortable.create(listsEl, {
      animation: 200,
      handle: '.kanban-list-col__head',
      draggable: '.kanban-list-col',
      filter: '.kanban-add-list-wrap',
      onEnd: async () => {
        const order = Array.from(listsEl.querySelectorAll('.kanban-list-col')).map((el) => Number(el.dataset.listId));
        ignoreSSE = true;
        try {
          await api(`/kanban/api/boards/${boardId}/lists/reorder`, { method: 'POST', body: { order } });
          board.lists.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
        } catch (err) {
          notify(err.message || 'Sortieren fehlgeschlagen');
          refreshBoard();
        }
        ignoreSSE = false;
      },
    }));
  }

  function upsertCardLocal(card) {
    for (const l of board.lists) {
      l.cards = (l.cards || []).filter((c) => c.id !== card.id);
    }
    const list = findList(card.list_id);
    if (list) {
      list.cards = list.cards || [];
      const summary = {
        id: card.id,
        list_id: card.list_id,
        title: card.title,
        description: card.description,
        poll_text: card.poll_text,
        due_date: card.due_date,
        position: card.position,
        archived: card.archived,
        completed: !!card.completed,
        cover: card.cover,
        labels: card.labels || [],
        assignees: card.assignees || [],
        checklist: card.checklist || { done: 0, total: 0 },
        attachment_count: card.attachment_count != null ? card.attachment_count : (card.attachments || []).length,
        comment_count: card.comment_count || 0,
        vote_count: card.vote_count || 0,
        voted_by_me: !!card.voted_by_me,
      };
      list.cards.splice(Math.min(card.position || 0, list.cards.length), 0, summary);
    }
    if (currentCardId === card.id) currentCardDetail = Object.assign({}, currentCardDetail || {}, card);
  }

  function showAddListForm() {
    const showAdd = document.getElementById('kanbanShowAddList');
    const addForm = document.getElementById('kanbanAddListForm');
    if (!showAdd || !addForm) return;
    showAdd.hidden = true;
    addForm.hidden = false;
    const input = document.getElementById('kanbanListName');
    if (input) {
      input.value = '';
      setTimeout(() => input.focus(), 0);
    }
  }

  function hideAddListForm() {
    const showAdd = document.getElementById('kanbanShowAddList');
    const addForm = document.getElementById('kanbanAddListForm');
    if (showAdd) showAdd.hidden = false;
    if (addForm) addForm.hidden = true;
  }

  async function submitAddList(title) {
    ignoreSSE = true;
    try {
      const data = await api(`/kanban/api/boards/${boardId}/lists`, {
        method: 'POST',
        body: { title },
      });
      if (data.list) {
        board.lists.push(data.list);
        renderBoard();
      } else {
        notify('Liste konnte nicht erstellt werden');
      }
    } catch (err) {
      notify(err.message || 'Liste konnte nicht erstellt werden');
    }
    ignoreSSE = false;
  }

  async function submitAddCard(listId, title) {
    ignoreSSE = true;
    try {
      const data = await api(`/kanban/api/lists/${listId}/cards`, {
        method: 'POST',
        body: { title },
      });
      if (data.card) {
        const list = findList(listId);
        if (list) {
          list.cards = list.cards || [];
          list.cards.push(data.card);
        }
        renderBoard();
      } else {
        notify('Karte konnte nicht erstellt werden');
      }
    } catch (err) {
      notify(err.message || 'Karte konnte nicht erstellt werden');
    }
    ignoreSSE = false;
  }

  // Delegated clicks / submits on the board
  app.addEventListener('click', async (e) => {
    const card = e.target.closest('.kanban-card');
    if (card && listsEl.contains(card) && !e.target.closest('button, a, input, form')) {
      openCard(Number(card.dataset.cardId));
      return;
    }

    if (e.target.closest('#kanbanShowAddList')) {
      e.preventDefault();
      showAddListForm();
      return;
    }
    if (e.target.closest('#kanbanCancelAddList')) {
      e.preventDefault();
      hideAddListForm();
      return;
    }

    const addCardBtn = e.target.closest('.kanban-add-card-btn');
    if (addCardBtn) {
      e.preventDefault();
      const footer = addCardBtn.closest('.kanban-list-col__footer');
      const form = footer && footer.querySelector('.kanban-add-card-form');
      if (form) {
        addCardBtn.hidden = true;
        form.hidden = false;
        const input = form.querySelector('input[name="title"]');
        if (input) {
          input.value = '';
          setTimeout(() => input.focus(), 0);
        }
      }
      return;
    }

    if (e.target.closest('.kanban-cancel-add-card')) {
      e.preventDefault();
      const form = e.target.closest('.kanban-add-card-form');
      const footer = form && form.closest('.kanban-list-col__footer');
      const btn = footer && footer.querySelector('.kanban-add-card-btn');
      if (form) form.hidden = true;
      if (btn) btn.hidden = false;
      return;
    }

    const renameListBtn = e.target.closest('[data-list-rename]');
    if (renameListBtn) {
      e.preventDefault();
      const listId = Number(renameListBtn.getAttribute('data-list-rename'));
      const list = findList(listId);
      if (!list) return;
      const name = await askPrompt(i18n.listName || 'Listenname', list.title || '', {
        title: i18n.listName || 'Listenname',
      });
      if (name == null) return;
      const title = name.trim();
      if (!title) return;
      try {
        const data = await api(`/kanban/api/lists/${listId}`, { method: 'PATCH', body: { title } });
        if (data.list) {
          list.title = data.list.title;
          renderBoard();
        }
      } catch (err) {
        notify(err.message || 'Umbenennen fehlgeschlagen');
      }
      return;
    }

    const deleteListBtn = e.target.closest('[data-list-delete]');
    if (deleteListBtn) {
      e.preventDefault();
      const listId = Number(deleteListBtn.getAttribute('data-list-delete'));
      if (!(await askConfirm('Liste und alle Karten löschen?'))) return;
      try {
        await api(`/kanban/api/lists/${listId}`, { method: 'DELETE' });
        board.lists = board.lists.filter((l) => l.id !== listId);
        renderBoard();
      } catch (err) {
        notify(err.message || 'Löschen fehlgeschlagen');
      }
    }
  });

  app.addEventListener('submit', async (e) => {
    if (e.target.id === 'kanbanAddListForm') {
      e.preventDefault();
      const title = (document.getElementById('kanbanListName') || {}).value;
      const name = (title || '').trim();
      if (!name) return;
      await submitAddList(name);
      return;
    }
    const cardForm = e.target.closest('.kanban-add-card-form');
    if (cardForm && app.contains(cardForm)) {
      e.preventDefault();
      const title = (cardForm.querySelector('input[name="title"]') || {}).value;
      const name = (title || '').trim();
      if (!name) return;
      await submitAddCard(Number(cardForm.dataset.listId), name);
    }
  });

  async function openCard(cardId) {
    currentCardId = cardId;
    let card;
    try {
      card = await api(`/kanban/api/cards/${cardId}`);
    } catch (err) {
      notify(err.message || 'Karte konnte nicht geladen werden');
      return;
    }
    currentCardDetail = card;
    const titleEl = document.getElementById('cardModalTitle');
    const descEl = document.getElementById('cardModalDescription');
    const listHidden = document.getElementById('cardModalListSelect');
    const listBtn = document.getElementById('cardModalListBtn');
    const listMenu = document.getElementById('cardModalListMenu');
    const coverEl = document.getElementById('cardModalCover');
    titleEl.value = card.title || '';
    descEl.value = card.description || '';
    const currentList = findList(card.list_id);
    if (listHidden) listHidden.value = String(card.list_id || '');
    if (listBtn) listBtn.textContent = (currentList && currentList.title) || '—';
    if (listMenu) {
      listMenu.innerHTML = (board.lists || []).map((l) =>
        `<li><button type="button" class="dropdown-item${l.id === card.list_id ? ' active' : ''}" data-list-id="${l.id}">${esc(l.title)}</button></li>`
      ).join('');
      listMenu.querySelectorAll('[data-list-id]').forEach((btn) => {
        btn.addEventListener('click', async () => {
          if (!canEdit || !currentCardId) return;
          const listId = Number(btn.dataset.listId);
          if (!listId || listId === (currentCardDetail && currentCardDetail.list_id)) return;
          try {
            const r = await api(`/kanban/api/cards/${currentCardId}`, {
              method: 'PATCH',
              body: { list_id: listId },
            });
            if (r.card) {
              upsertCardLocal(r.card);
              renderBoard();
              openCard(currentCardId);
            }
          } catch (err) {
            notify(err.message || 'Verschieben fehlgeschlagen');
          }
        });
      });
    }
    coverEl.innerHTML = card.cover && card.cover.is_image
      ? `<img src="${esc(card.cover.preview_url || card.cover.url)}" alt="">`
      : '';
    updateCompleteBtn(!!card.completed);
    renderPollSection(card);
    document.getElementById('cardClearCoverBtn')?.toggleAttribute('disabled', !card.cover);
    const linkForm = document.getElementById('cardAttachLinkForm');
    if (linkForm) linkForm.hidden = true;

    const meta = document.getElementById('cardMetaRow');
    meta.innerHTML = `
      <div><strong>${esc(i18n.members || 'Mitglieder')}</strong><div class="d-flex gap-1 mt-1 flex-wrap">${
        (card.assignees || []).map((a) => avatarHtml(a)).join('') || '<span class="small text-muted">—</span>'
      }</div></div>
      <div><strong>Labels</strong><div class="d-flex gap-1 mt-1 flex-wrap">${
        (card.labels || []).map((lb) => labelChipHtml(lb, true)).join('') || '<span class="small text-muted">—</span>'
      }</div></div>
      ${card.due_date ? `<div><strong>Datum</strong><div>${esc(formatDueDisplay(card.due_date))}</div></div>` : ''}
    `;
    renderCardCustomFields(card);

    const clRoot = document.getElementById('cardChecklists');
    clRoot.innerHTML = (card.checklists || []).map((cl) => {
      const done = (cl.items || []).filter((it) => it.done).length;
      const total = (cl.items || []).length;
      const pct = total ? Math.round((done / total) * 100) : 0;
      return `
      <div class="kanban-checklist" data-checklist-id="${cl.id}">
        <div class="kanban-checklist-head">
          <input class="form-control form-control-sm kanban-pill-input kanban-checklist-title" data-checklist-id="${cl.id}" value="${esc(cl.title)}" maxlength="200" ${canEdit ? '' : 'readonly'}>
          ${canEdit ? `<button type="button" class="btn btn-sm kanban-pill-btn kanban-pill-btn--ghost" data-del-checklist="${cl.id}">${esc(i18n.delete || 'Löschen')}</button>` : ''}
        </div>
        <div class="kanban-checklist-progress">
          <span>${pct}%</span>
          <div class="kanban-checklist-progress__bar"><div style="width:${pct}%"></div></div>
        </div>
        ${(cl.items || []).map((it) => {
          const dueLabel = it.due_date ? formatDueDisplay(it.due_date) : '';
          return `
          <div class="kanban-checklist-item" data-item-id="${it.id}">
            <input type="checkbox" data-item-id="${it.id}" ${it.done ? 'checked' : ''} ${canEdit ? '' : 'disabled'}>
            <div class="kanban-checklist-item__body">
              <span class="kanban-checklist-item__text">${esc(it.text)}</span>
              <div class="kanban-checklist-item__meta">
                ${dueLabel ? `<span class="kanban-checklist-item__due"><i class="bi bi-clock"></i> ${esc(dueLabel)}</span>` : ''}
                ${it.assignee ? avatarHtml(it.assignee) : ''}
              </div>
            </div>
            ${canEdit ? `
            <div class="kanban-checklist-item__actions">
              <button type="button" class="btn btn-sm kanban-pill-btn kanban-pill-btn--icon" data-item-due="${it.id}" title="${esc(i18n.due || 'Zeit')}"><i class="bi bi-clock"></i></button>
              <button type="button" class="btn btn-sm kanban-pill-btn kanban-pill-btn--icon" data-item-assignee="${it.id}" title="${esc(i18n.members || 'Person')}"><i class="bi bi-person-plus"></i></button>
              <button type="button" class="btn btn-sm kanban-pill-btn kanban-pill-btn--icon kanban-pill-btn--ghost" data-item-del="${it.id}" title="${esc(i18n.delete || 'Löschen')}"><i class="bi bi-trash"></i></button>
            </div>` : ''}
          </div>`;
        }).join('')}
        ${canEdit ? `<form class="kanban-add-item-form mt-2" data-checklist-id="${cl.id}">
          <input class="form-control form-control-sm kanban-pill-input" name="text" placeholder="Item…" autocomplete="off">
        </form>` : ''}
      </div>`;
    }).join('');

    clRoot.querySelectorAll('input[type=checkbox][data-item-id]').forEach((cb) => {
      cb.addEventListener('change', async () => {
        try {
          const r = await api(`/kanban/api/checklist-items/${cb.dataset.itemId}`, {
            method: 'PATCH', body: { done: cb.checked },
          });
          if (r.card) upsertCardLocal(r.card);
        } catch (err) {
          notify(err.message || 'Fehler');
        }
      });
    });
    clRoot.querySelectorAll('[data-item-due]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const itemId = Number(btn.getAttribute('data-item-due'));
        let item = null;
        (card.checklists || []).forEach((cl) => {
          (cl.items || []).forEach((it) => { if (it.id === itemId) item = it; });
        });
        checklistItemDueTarget = itemId;
        const input = document.getElementById('kanbanDueInput');
        if (input) input.value = toDatetimeLocalValue(item && item.due_date);
        getModal('kanbanDueModal')?.show();
      });
    });
    clRoot.querySelectorAll('[data-item-assignee]').forEach((btn) => {
      btn.addEventListener('click', () => {
        checklistItemAssigneeTarget = Number(btn.getAttribute('data-item-assignee'));
        renderMembersPicker({ checklistItemId: checklistItemAssigneeTarget, card });
        getModal('kanbanMembersModal')?.show();
      });
    });
    clRoot.querySelectorAll('[data-item-del]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!(await askConfirm(i18n.delete || 'Löschen?'))) return;
        try {
          await api(`/kanban/api/checklist-items/${btn.getAttribute('data-item-del')}`, { method: 'DELETE' });
          openCard(cardId);
        } catch (err) {
          notify(err.message || 'Fehler');
        }
      });
    });
    clRoot.querySelectorAll('.kanban-add-item-form').forEach((f) => {
      f.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const text = f.text.value.trim();
        if (!text) return;
        try {
          await api(`/kanban/api/checklists/${f.dataset.checklistId}/items`, {
            method: 'POST', body: { text },
          });
          openCard(cardId);
        } catch (err) {
          notify(err.message || 'Fehler');
        }
      });
    });
    clRoot.querySelectorAll('.kanban-checklist-title').forEach((inp) => {
      inp.addEventListener('change', async () => {
        const title = inp.value.trim();
        if (!title) return;
        try {
          const r = await api(`/kanban/api/checklists/${inp.dataset.checklistId}`, {
            method: 'PATCH', body: { title },
          });
          if (r.card) upsertCardLocal(r.card);
        } catch (err) {
          notify(err.message || 'Fehler');
        }
      });
    });
    clRoot.querySelectorAll('[data-del-checklist]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!(await askConfirm(i18n.delete || 'Löschen?'))) return;
        try {
          await api(`/kanban/api/checklists/${btn.getAttribute('data-del-checklist')}`, { method: 'DELETE' });
          openCard(cardId);
        } catch (err) {
          notify(err.message || 'Fehler');
        }
      });
    });

    const attRoot = document.getElementById('cardAttachments');
    const atts = card.attachments || [];
    const coverId = card.cover_attachment_id || (card.cover && card.cover.id) || null;
    const links = atts.filter((a) => a.is_link);
    const files = atts.filter((a) => !a.is_link);

    function formatAddedAt(iso) {
      if (!iso) return '';
      return `${formatDueDisplay(iso)} ${esc(i18n.addedSuffix || 'hinzugefügt')}`;
    }

    function attachThumb(a) {
      if (a.is_link) return `<div class="kanban-attach-thumb kanban-attach-thumb--icon"><i class="bi bi-link-45deg"></i></div>`;
      if (a.is_image && a.preview_url) return `<img class="kanban-attach-thumb" src="${esc(a.preview_url)}" alt="">`;
      if (a.is_pdf) return `<div class="kanban-attach-thumb kanban-attach-thumb--badge">PDF</div>`;
      const ext = ((a.filename || '').split('.').pop() || '').toUpperCase().slice(0, 4);
      return `<div class="kanban-attach-thumb kanban-attach-thumb--badge">${esc(ext || 'FILE')}</div>`;
    }

    function attachRow(a) {
      const viewUrl = a.is_link ? a.url : (a.preview_url || a.url);
      const isCover = coverId && Number(coverId) === Number(a.id);
      return `<div class="kanban-attach-row${isCover ? ' is-cover' : ''}" data-att-id="${a.id}">
        ${attachThumb(a)}
        <div class="kanban-attach-row__info">
          <a class="kanban-attach-row__name" href="${esc(viewUrl)}" target="_blank" rel="noopener">${esc(a.filename)}</a>
          <div class="kanban-attach-row__meta">
            ${a.created_at ? `<span>${formatAddedAt(a.created_at)}</span>` : ''}
            ${isCover ? `<span class="kanban-attach-cover-mark" title="${esc(i18n.setCover || 'Titelbild')}"><i class="bi bi-image-fill"></i> ${esc(i18n.setCover || 'Titelbild')}</span>` : ''}
          </div>
        </div>
        <div class="kanban-attach-row__actions">
          <a class="btn btn-sm kanban-pill-btn kanban-pill-btn--icon" href="${esc(viewUrl)}" target="_blank" rel="noopener" title="${esc(i18n.view || 'Ansehen')}"><i class="bi bi-box-arrow-up-right"></i></a>
          ${canEdit && a.is_image && !isCover ? `<button type="button" class="btn btn-sm kanban-pill-btn kanban-pill-btn--icon" data-set-cover="${a.id}" title="${esc(i18n.setCover || 'Titelbild')}"><i class="bi bi-image"></i></button>` : ''}
          ${canEdit && isCover ? `<button type="button" class="btn btn-sm kanban-pill-btn kanban-pill-btn--icon" data-clear-cover="1" title="${esc(i18n.removeCover || 'Titelbild entfernen')}"><i class="bi bi-image-fill text-warning"></i></button>` : ''}
          ${canEdit ? `<button type="button" class="btn btn-sm kanban-pill-btn kanban-pill-btn--icon kanban-pill-btn--ghost" data-del-att="${a.id}" title="${esc(i18n.delete || 'Löschen')}"><i class="bi bi-trash"></i></button>` : ''}
        </div>
      </div>`;
    }

    let html = '';
    if (links.length) {
      html += `<div class="kanban-attach-section"><div class="kanban-attach-section__title">${esc(i18n.links || 'Links')}</div>
        <div class="kanban-attach-section__list">${links.map(attachRow).join('')}</div></div>`;
    }
    if (files.length) {
      html += `<div class="kanban-attach-section"><div class="kanban-attach-section__title">${esc(i18n.files || 'Dateien')}</div>
        <div class="kanban-attach-section__list">${files.map(attachRow).join('')}</div></div>`;
    }
    attRoot.innerHTML = html || '<p class="text-muted small">Keine Anhänge</p>';

    attRoot.querySelectorAll('[data-set-cover]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        try {
          const r = await api(`/kanban/api/cards/${cardId}`, {
            method: 'PATCH',
            body: { cover_attachment_id: Number(btn.getAttribute('data-set-cover')) },
          });
          if (r.card) {
            upsertCardLocal(r.card);
            openCard(cardId);
            renderBoard();
          }
        } catch (err) {
          notify(err.message || 'Fehler');
        }
      });
    });
    attRoot.querySelectorAll('[data-clear-cover]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        try {
          const r = await api(`/kanban/api/cards/${cardId}`, {
            method: 'PATCH',
            body: { cover_attachment_id: null },
          });
          if (r.card) {
            upsertCardLocal(r.card);
            openCard(cardId);
            renderBoard();
          }
        } catch (err) {
          notify(err.message || 'Fehler');
        }
      });
    });
    attRoot.querySelectorAll('[data-del-att]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!(await askConfirm('Anhang löschen?'))) return;
        try {
          await api(`/kanban/api/attachments/${btn.getAttribute('data-del-att')}`, { method: 'DELETE' });
          openCard(cardId);
          refreshBoard();
        } catch (err) {
          notify(err.message || 'Fehler');
        }
      });
    });

    // Comments – Form klonen, damit Listener nicht doppelt hängen
    const commentsRoot = document.getElementById('kanbanCardComments');
    if (commentsRoot) {
      if (isShare) {
        commentsRoot.hidden = true;
      } else {
        commentsRoot.hidden = false;
        const oldForm = commentsRoot.querySelector('.comment-form');
        if (oldForm) {
          const clone = oldForm.cloneNode(true);
          const ta = clone.querySelector('.comment-textarea');
          if (ta) ta.value = '';
          oldForm.replaceWith(clone);
        }
        const commentsList = commentsRoot.querySelector('.comments-list');
        if (commentsList) commentsList.innerHTML = '';
        if (window.CommentSystem) {
          commentSystem = new window.CommentSystem('kanban_card', cardId, 'kanbanCardComments');
          window.commentSystem = commentSystem;
        }
      }
    }

    try {
      const act = await api(`/kanban/api/boards/${boardId}/activity?card_id=${cardId}`);
      document.getElementById('kanbanCardActivity').innerHTML = (act.activities || []).map((a) => `
        <div class="kanban-activity-item">
          <div><strong>${esc(a.user && a.user.name || '?')}</strong> ${esc(a.action_label || a.action || '')}</div>
          ${a.detail ? `<div class="small">${esc(a.detail)}</div>` : ''}
          <div class="kanban-activity-item__meta">${esc(a.created_at_display || formatDueDisplay(a.created_at) || '')}</div>
        </div>`).join('') || '<p class="text-muted small">—</p>';
    } catch (_) {
      document.getElementById('kanbanCardActivity').innerHTML = '';
    }

    ensureCardModal()?.show();
  }

  function renderPollSection(card) {
    currentCardDetail = card;
    const section = document.getElementById('cardPollSection');
    const countEl = document.getElementById('cardVoteCount');
    const pollCount = document.getElementById('cardPollVoteCount');
    const pollText = document.getElementById('cardPollText');
    const pollVoteLabel = document.getElementById('cardPollVoteLabel');
    const topVoteBtn = document.getElementById('cardVoteBtn');
    const votes = card.vote_count || 0;
    if (countEl) countEl.textContent = votes;
    if (pollCount) pollCount.textContent = votes;
    if (pollVoteLabel) pollVoteLabel.textContent = card.voted_by_me ? 'Zurücknehmen' : 'Zustimmen';
    if (topVoteBtn) {
      topVoteBtn.classList.toggle('is-active', !!card.voted_by_me);
      topVoteBtn.title = card.poll_text
        ? (card.voted_by_me ? 'Stimme zurücknehmen' : 'Zustimmen')
        : (canEdit ? 'Abstimmung erstellen' : 'Keine Abstimmung');
    }
    if (!section) return;
    if (card.poll_text) {
      section.hidden = false;
      if (pollText) pollText.textContent = card.poll_text;
    } else {
      section.hidden = true;
      if (pollText) pollText.textContent = '';
    }
  }

  async function savePollText(text) {
    if (!currentCardId) return;
    const r = await api(`/kanban/api/cards/${currentCardId}`, {
      method: 'PATCH',
      body: { poll_text: text },
    });
    if (r.card) {
      upsertCardLocal(r.card);
      renderPollSection(r.card);
      renderBoard();
    }
  }

  async function toggleVote() {
    if (!currentCardId) return;
    const r = await api(`/kanban/api/cards/${currentCardId}/vote`, { method: 'POST', body: {} });
    if (r.card) {
      upsertCardLocal(r.card);
      renderPollSection(r.card);
      renderBoard();
    }
  }

  document.getElementById('cardVoteBtn')?.addEventListener('click', async () => {
    if (!currentCardId) return;
    try {
      const hasPoll = !!(currentCardDetail && currentCardDetail.poll_text);
      if (!hasPoll) {
        if (!canEdit) {
          notify('Keine Abstimmung vorhanden');
          return;
        }
        document.getElementById('kanbanPollInput').value = '';
        getModal('kanbanPollModal')?.show();
        return;
      }
      await toggleVote();
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  });

  document.getElementById('cardPollVoteBtn')?.addEventListener('click', async () => {
    try {
      await toggleVote();
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  });

  document.getElementById('cardPollEditBtn')?.addEventListener('click', () => {
    const text = document.getElementById('cardPollText')?.textContent || '';
    document.getElementById('kanbanPollInput').value = text;
    getModal('kanbanPollModal')?.show();
  });

  document.getElementById('cardPollClearBtn')?.addEventListener('click', async () => {
    if (!(await askConfirm('Abstimmung entfernen?'))) return;
    try {
      await savePollText('');
      getModal('kanbanPollModal')?.hide();
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  });

  document.getElementById('kanbanPollSave')?.addEventListener('click', async () => {
    const text = (document.getElementById('kanbanPollInput')?.value || '').trim();
    if (!text) {
      notify('Bitte Text eingeben');
      return;
    }
    try {
      await savePollText(text);
      getModal('kanbanPollModal')?.hide();
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  });

  function updateCompleteBtn(completed) {
    const btn = document.getElementById('cardCompleteBtn');
    if (!btn) return;
    btn.classList.toggle('is-completed', !!completed);
    btn.setAttribute('aria-pressed', completed ? 'true' : 'false');
    btn.innerHTML = completed
      ? '<i class="bi bi-check-circle-fill" aria-hidden="true"></i>'
      : '<i class="bi bi-circle" aria-hidden="true"></i>';
  }

  document.getElementById('cardCompleteBtn')?.addEventListener('click', async () => {
    if (!canEdit || !currentCardId) return;
    const next = !(currentCardDetail && currentCardDetail.completed);
    try {
      const r = await api(`/kanban/api/cards/${currentCardId}`, {
        method: 'PATCH',
        body: { completed: next },
      });
      if (r.card) {
        upsertCardLocal(r.card);
        updateCompleteBtn(!!r.card.completed);
        renderBoard();
      }
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  });

  document.getElementById('cardClearCoverBtn')?.addEventListener('click', async () => {
    if (!currentCardId) return;
    try {
      const r = await api(`/kanban/api/cards/${currentCardId}`, {
        method: 'PATCH',
        body: { cover_attachment_id: null },
      });
      if (r.card) {
        upsertCardLocal(r.card);
        openCard(currentCardId);
        renderBoard();
      }
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  });

  document.getElementById('cardAttachLinkBtn')?.addEventListener('click', () => {
    const form = document.getElementById('cardAttachLinkForm');
    if (!form) return;
    form.hidden = false;
    document.getElementById('cardAttachLinkUrl')?.focus();
  });

  document.getElementById('cardAttachLinkCancel')?.addEventListener('click', () => {
    const form = document.getElementById('cardAttachLinkForm');
    if (form) form.hidden = true;
  });

  document.getElementById('cardAttachLinkForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!currentCardId) return;
    const url = (document.getElementById('cardAttachLinkUrl')?.value || '').trim();
    const title = (document.getElementById('cardAttachLinkTitle')?.value || '').trim();
    if (!url) return;
    try {
      await api(`/kanban/api/cards/${currentCardId}/attachments`, {
        method: 'POST',
        body: { url, title },
      });
      e.target.hidden = true;
      document.getElementById('cardAttachLinkUrl').value = '';
      document.getElementById('cardAttachLinkTitle').value = '';
      openCard(currentCardId);
      refreshBoard();
    } catch (err) {
      notify(err.message || 'Link konnte nicht hinzugefügt werden');
    }
  });

  async function uploadCardFile(file, { asCover } = {}) {
    if (!file || !currentCardId) return;
    const fd = new FormData();
    fd.append('file', file);
    const headers = { 'X-Requested-With': 'XMLHttpRequest' };
    if (shareToken) headers['X-Share-Token'] = shareToken;
    const res = await fetch(`/kanban/api/cards/${currentCardId}/attachments`, {
      method: 'POST',
      headers,
      body: fd,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || 'Upload fehlgeschlagen');
    if (asCover && data.attachment && data.attachment.id) {
      await api(`/kanban/api/cards/${currentCardId}`, {
        method: 'PATCH',
        body: { cover_attachment_id: data.attachment.id },
      });
    }
    openCard(currentCardId);
    refreshBoard();
  }

  document.getElementById('cardCoverFile')?.addEventListener('change', async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = '';
    if (!file) return;
    try {
      await uploadCardFile(file, { asCover: true });
    } catch (err) {
      notify(err.message || 'Upload fehlgeschlagen');
    }
  });

  document.getElementById('cardAttachFile')?.addEventListener('change', async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = '';
    if (!file) return;
    try {
      await uploadCardFile(file, { asCover: false });
    } catch (err) {
      notify(err.message || 'Upload fehlgeschlagen');
    }
  });

  document.getElementById('cardDeleteBtn')?.addEventListener('click', async () => {
    if (!currentCardId || !(await askConfirm('Karte löschen?'))) return;
    try {
      await api(`/kanban/api/cards/${currentCardId}`, { method: 'DELETE' });
      ensureCardModal()?.hide();
      for (const l of board.lists) {
        l.cards = (l.cards || []).filter((c) => c.id !== currentCardId);
      }
      currentCardId = null;
      renderBoard();
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  });

  document.getElementById('cardModalTitle')?.addEventListener('change', async (e) => {
    if (!canEdit || !currentCardId) return;
    try {
      const r = await api(`/kanban/api/cards/${currentCardId}`, { method: 'PATCH', body: { title: e.target.value } });
      if (r.card) { upsertCardLocal(r.card); renderBoard(); }
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  });
  document.getElementById('cardModalDescription')?.addEventListener('change', async (e) => {
    if (!canEdit || !currentCardId) return;
    try {
      await api(`/kanban/api/cards/${currentCardId}`, { method: 'PATCH', body: { description: e.target.value } });
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  });

  document.getElementById('cardAddChecklist')?.addEventListener('click', () => {
    if (!currentCardId) return;
    showNewChecklistForm();
  });

  document.getElementById('cardAddDue')?.addEventListener('click', () => {
    if (!currentCardId) return;
    checklistItemDueTarget = null;
    const input = document.getElementById('kanbanDueInput');
    if (input) input.value = toDatetimeLocalValue(currentCardDetail && currentCardDetail.due_date);
    getModal('kanbanDueModal')?.show();
  });

  document.getElementById('kanbanDueForm')?.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!currentCardId) return;
    const val = document.getElementById('kanbanDueInput')?.value || '';
    try {
      if (checklistItemDueTarget) {
        await api(`/kanban/api/checklist-items/${checklistItemDueTarget}`, {
          method: 'PATCH',
          body: { due_date: val || null },
        });
        checklistItemDueTarget = null;
      } else {
        await api(`/kanban/api/cards/${currentCardId}`, {
          method: 'PATCH',
          body: { due_date: val || null },
        });
      }
      getModal('kanbanDueModal')?.hide();
      openCard(currentCardId);
      refreshBoard();
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  });

  document.getElementById('kanbanDueClear')?.addEventListener('click', async () => {
    if (!currentCardId) return;
    try {
      if (checklistItemDueTarget) {
        await api(`/kanban/api/checklist-items/${checklistItemDueTarget}`, {
          method: 'PATCH',
          body: { due_date: null },
        });
        checklistItemDueTarget = null;
      } else {
        await api(`/kanban/api/cards/${currentCardId}`, {
          method: 'PATCH',
          body: { due_date: null },
        });
      }
      getModal('kanbanDueModal')?.hide();
      openCard(currentCardId);
      refreshBoard();
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  });

  function renderMembersPicker(opts) {
    const options = opts || {};
    const list = document.getElementById('kanbanMembersList');
    if (!list) return;
    const itemId = options.checklistItemId || checklistItemAssigneeTarget;
    let assigned = new Set();
    if (itemId) {
      const card = options.card || currentCardDetail;
      (card && card.checklists || []).forEach((cl) => {
        (cl.items || []).forEach((it) => {
          if (it.id === itemId && it.assignee_id) assigned.add(it.assignee_id);
          if (it.id === itemId && it.assignee && it.assignee.id) assigned.add(it.assignee.id);
        });
      });
    } else {
      assigned = new Set((currentCardDetail && currentCardDetail.assignees || []).map((a) => a.id));
    }
    const members = board.members || [];
    list.innerHTML = members.map((m) =>
      `<button type="button" class="kanban-label-pick-btn${assigned.has(m.id) ? ' is-on' : ''}" data-user-id="${m.id}">
        ${avatarHtml(m)}
        <span>${esc(m.name || '')}</span>
      </button>`
    ).join('') || '<p class="text-muted small">Keine Mitglieder</p>';
    list.querySelectorAll('[data-user-id]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const userId = Number(btn.dataset.userId);
        try {
          if (itemId) {
            const nextId = assigned.has(userId) ? null : userId;
            const r = await api(`/kanban/api/checklist-items/${itemId}`, {
              method: 'PATCH',
              body: { assignee_id: nextId },
            });
            if (r.card) {
              currentCardDetail = r.card;
              checklistItemAssigneeTarget = null;
              getModal('kanbanMembersModal')?.hide();
              openCard(currentCardId);
            }
          } else {
            const r = await api(`/kanban/api/cards/${currentCardId}/assignees`, {
              method: 'POST',
              body: { user_id: userId },
            });
            if (r.card) {
              upsertCardLocal(r.card);
              currentCardDetail = { ...(currentCardDetail || {}), assignees: r.card.assignees || [] };
              const metaAssignees = document.querySelector('#cardMetaRow > div');
              if (metaAssignees) {
                metaAssignees.innerHTML = `<strong>${esc(i18n.members || 'Mitglieder')}</strong><div class="d-flex gap-1 mt-1 flex-wrap">${
                  (currentCardDetail.assignees || []).map((a) => avatarHtml(a)).join('') || '<span class="small text-muted">—</span>'
                }</div>`;
              }
              renderBoard();
              renderMembersPicker();
            }
          }
        } catch (err) {
          notify(err.message || 'Fehler');
        }
      });
    });
  }

  document.getElementById('cardAddMembers')?.addEventListener('click', () => {
    checklistItemAssigneeTarget = null;
    renderMembersPicker();
    getModal('kanbanMembersModal')?.show();
  });

  function renderLabelPicker() {
    const list = document.getElementById('kanbanLabelList');
    if (!list) return;
    const attached = new Set((currentCardDetail && currentCardDetail.labels || []).map((l) => l.id));
    list.innerHTML = (board.labels || []).map((lb) =>
      `<button type="button" class="kanban-label-pick-btn${attached.has(lb.id) ? ' is-on' : ''}" data-label-id="${lb.id}">
        <span class="kanban-label-swatch" style="background:${esc(lb.color)}"></span>
        <span>${esc(lb.name)}</span>
      </button>`
    ).join('') || '<p class="text-muted small mb-0">Keine Labels</p>';
    list.querySelectorAll('[data-label-id]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        try {
          const r = await api(`/kanban/api/cards/${currentCardId}/labels`, {
            method: 'POST',
            body: { label_id: Number(btn.dataset.labelId) },
          });
          if (r.card) upsertCardLocal(r.card);
          openCard(currentCardId);
          refreshBoard();
          renderLabelPicker();
        } catch (err) {
          notify(err.message || 'Fehler');
        }
      });
    });
  }

  document.getElementById('cardAddLabel')?.addEventListener('click', () => {
    renderLabelPicker();
    getModal('kanbanLabelModal')?.show();
  });

  document.getElementById('kanbanCreateLabelForm')?.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const name = (form.name.value || '').trim();
    const color = form.color.value || '#ef4444';
    if (!name) return;
    try {
      const r = await api(`/kanban/api/boards/${boardId}/labels`, {
        method: 'POST',
        body: { name, color },
      });
      if (r.label) {
        board.labels = board.labels || [];
        board.labels.push(r.label);
      }
      form.reset();
      form.color.value = '#ef4444';
      if (currentCardId && r.label) {
        await api(`/kanban/api/cards/${currentCardId}/labels`, {
          method: 'POST',
          body: { label_id: r.label.id },
        });
        openCard(currentCardId);
        refreshBoard();
      }
      renderLabelPicker();
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  });

  async function openShareModal() {
    const list = document.getElementById('kanbanShareList');
    if (!list) return;
    list.innerHTML = '<tr><td colspan="5" class="text-muted small">Lade…</td></tr>';
    getModal('kanbanShareModal')?.show();
    try {
      const data = await api(`/kanban/api/boards/${boardId}/shares`);
      renderShareRows(data.shares || []);
    } catch (err) {
      list.innerHTML = `<tr><td colspan="5" class="text-danger small">${esc(err.message || 'Freigaben konnten nicht geladen werden')}</td></tr>`;
    }
  }

  function sharePasswordValue(share) {
    if (share.password) return share.password;
    if (share.has_password) return '';
    return '';
  }

  function renderShareRows(shares) {
    const list = document.getElementById('kanbanShareList');
    if (!list) return;
    if (!shares.length) {
      list.innerHTML = '<tr><td colspan="5" class="text-muted small">Noch keine Freigabelinks.</td></tr>';
      return;
    }
    list.innerHTML = shares.map((s) => {
      const creator = s.created_by || {};
      const pw = sharePasswordValue(s);
      const pwDisplay = s.has_password
        ? `<div class="input-group input-group-sm kanban-share-pw-group">
             <input type="text" class="form-control form-control-sm kanban-pill-input" readonly value="${esc(pw || '••••••••')}" data-share-pw="${s.id}">
             ${pw ? `<button type="button" class="btn kanban-pill-btn btn-sm" data-copy-pw="${esc(pw)}" title="Passwort kopieren"><i class="bi bi-clipboard"></i></button>` : ''}
           </div>`
        : '<span class="text-muted">—</span>';
      return `<tr data-share-id="${s.id}">
        <td>
          <div class="d-flex align-items-center gap-2">
            ${avatarHtml(creator)}
            <div>
              <div class="fw-semibold">${esc(creator.name || '—')}</div>
              <div class="small text-muted">${esc(s.created_at_display || '')}</div>
            </div>
          </div>
        </td>
        <td>
          <div class="d-flex align-items-center gap-1 flex-wrap">
            <button type="button" class="btn btn-sm kanban-pill-btn" data-copy-share="${esc(s.share_url)}">
              <i class="bi bi-clipboard me-1"></i>Kopieren
            </button>
            <code class="kanban-share-url-mini" title="${esc(s.share_url)}">${esc((s.share_url || '').replace(/^https?:\/\//, '').slice(0, 28))}…</code>
          </div>
        </td>
        <td>${pwDisplay}</td>
        <td><span class="badge rounded-pill text-bg-secondary">${esc(s.mode_label || s.mode)}</span></td>
        <td class="text-end text-nowrap">
          <button type="button" class="btn btn-sm kanban-pill-btn kanban-pill-btn--ghost" data-edit-share="${s.id}" title="Bearbeiten"><i class="bi bi-pencil"></i></button>
          <button type="button" class="btn btn-sm kanban-pill-btn kanban-pill-btn--ghost text-danger" data-del-share="${s.id}" title="Löschen"><i class="bi bi-trash"></i></button>
        </td>
      </tr>`;
    }).join('');

    list.querySelectorAll('[data-copy-share]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(btn.getAttribute('data-copy-share'));
          const old = btn.innerHTML;
          btn.innerHTML = '<i class="bi bi-check2 me-1"></i>Kopiert';
          setTimeout(() => { btn.innerHTML = old; }, 1200);
        } catch (_) {
          notify(btn.getAttribute('data-copy-share'), 'info');
        }
      });
    });
    list.querySelectorAll('[data-copy-pw]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(btn.getAttribute('data-copy-pw'));
          btn.innerHTML = '<i class="bi bi-check2"></i>';
        } catch (_) { /* ignore */ }
      });
    });
    list.querySelectorAll('[data-edit-share]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = Number(btn.getAttribute('data-edit-share'));
        const share = shares.find((x) => x.id === id);
        if (!share) return;
        document.getElementById('kanbanShareEditId').value = String(share.id);
        document.getElementById('kanbanShareEditMode').value = share.mode || 'view';
        document.getElementById('kanbanShareEditPassword').value = '';
        document.getElementById('kanbanShareClearPassword').checked = false;
        getModal('kanbanShareEditModal')?.show();
      });
    });
    list.querySelectorAll('[data-del-share]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!(await askConfirm('Freigabelink löschen?'))) return;
        try {
          await api(`/kanban/api/boards/${boardId}/shares/${btn.getAttribute('data-del-share')}`, { method: 'DELETE' });
          openShareModal();
        } catch (err) {
          notify(err.message || 'Löschen fehlgeschlagen');
        }
      });
    });
  }

  document.getElementById('kanbanCustomFieldsBtn')?.addEventListener('click', (e) => {
    e.preventDefault();
    openCustomFieldsModal();
  });

  document.getElementById('kanbanCfType')?.addEventListener('change', syncCustomFieldOptionsVisibility);

  document.getElementById('kanbanCfCancelEdit')?.addEventListener('click', () => resetCustomFieldForm());

  document.getElementById('kanbanCustomFieldForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const editId = (document.getElementById('kanbanCfEditId')?.value || '').trim();
    const label = (document.getElementById('kanbanCfLabel')?.value || '').trim();
    const fieldType = document.getElementById('kanbanCfType')?.value || 'text';
    const options = document.getElementById('kanbanCfOptions')?.value || '';
    const categoryRaw = document.getElementById('kanbanCfCategory')?.value || '';
    if (!label) return;
    const body = {
      label,
      field_type: fieldType,
      options,
      category_id: categoryRaw ? Number(categoryRaw) : null,
    };
    try {
      const r = editId
        ? await api(`/kanban/api/custom-fields/${editId}`, { method: 'PATCH', body })
        : await api(`/kanban/api/boards/${boardId}/custom-fields`, { method: 'POST', body });
      setCustomFields(r.custom_fields);
      renderCustomFieldsManageList();
      resetCustomFieldForm();
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  });

  document.getElementById('kanbanCfCategoryForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = (document.getElementById('kanbanCfCategoryName')?.value || '').trim();
    if (!name) return;
    try {
      const r = await api(`/kanban/api/boards/${boardId}/custom-field-categories`, {
        method: 'POST',
        body: { name },
      });
      if (r.categories) setCustomFieldCategories(r.categories);
      else if (r.category) {
        board.custom_field_categories = [...(board.custom_field_categories || []), r.category];
      }
      document.getElementById('kanbanCfCategoryName').value = '';
      fillCategorySelect();
      renderCustomFieldsManageList();
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  });

  document.getElementById('kanbanShareBtn')?.addEventListener('click', (e) => {
    e.preventDefault();
    openShareModal();
  });

  function applyBoardPageBackground(boardPayload) {
    const css = (boardPayload && boardPayload.background_css) || app.style.getPropertyValue('--kanban-bg');
    const img = boardPayload && boardPayload.cover_path;
    if (css) app.style.setProperty('--kanban-bg', css);
    if (img) {
      app.style.setProperty('--kanban-bg-image', `url('${img}')`);
      app.classList.add('has-bg-image');
      app.dataset.bgImageUrl = img;
    } else {
      app.style.removeProperty('--kanban-bg-image');
      app.classList.remove('has-bg-image');
      app.dataset.bgImageUrl = '';
    }
    document.querySelectorAll('#kanbanBoardBgPicker .kanban-bg-swatch').forEach((btn) => {
      btn.classList.toggle('is-active', btn.dataset.bg === ((boardPayload && boardPayload.background) || board.background));
    });
  }

  let selectedBoardBg = board.background || 'teal';
  document.getElementById('kanbanBgBtn')?.addEventListener('click', (e) => {
    e.preventDefault();
    selectedBoardBg = board.background || 'teal';
    document.querySelectorAll('#kanbanBoardBgPicker .kanban-bg-swatch').forEach((btn) => {
      btn.classList.toggle('is-active', btn.dataset.bg === selectedBoardBg);
    });
    const input = document.getElementById('kanbanBoardBgImageInput');
    if (input) input.value = '';
    getModal('kanbanBoardBgModal')?.show();
  });

  document.querySelectorAll('#kanbanBoardBgPicker .kanban-bg-swatch').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#kanbanBoardBgPicker .kanban-bg-swatch').forEach((b) => b.classList.remove('is-active'));
      btn.classList.add('is-active');
      selectedBoardBg = btn.dataset.bg;
    });
  });

  document.getElementById('kanbanBoardBgSave')?.addEventListener('click', async () => {
    try {
      const data = await api(`/kanban/api/boards/${boardId}`, {
        method: 'PATCH',
        body: { background: selectedBoardBg },
      });
      if (data.board) {
        Object.assign(board, data.board);
        applyBoardPageBackground(data.board);
      }
      getModal('kanbanBoardBgModal')?.hide();
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  });

  document.getElementById('kanbanBoardBgImageUpload')?.addEventListener('click', async () => {
    const input = document.getElementById('kanbanBoardBgImageInput');
    if (!input || !input.files || !input.files[0]) return;
    const fd = new FormData();
    fd.append('file', input.files[0]);
    try {
      const headers = { 'X-Requested-With': 'XMLHttpRequest' };
      if (shareToken) headers['X-Share-Token'] = shareToken;
      const res = await fetch(`/kanban/api/boards/${boardId}/background`, {
        method: 'POST',
        body: fd,
        headers,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.success === false) throw new Error(data.error || 'Upload fehlgeschlagen');
      if (data.board) {
        Object.assign(board, data.board);
        applyBoardPageBackground(data.board);
      }
      input.value = '';
      notify(i18n.backgroundUpload || 'Hintergrund gespeichert', 'success');
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  });

  document.getElementById('kanbanBoardBgImageClear')?.addEventListener('click', async () => {
    try {
      const headers = { 'X-Requested-With': 'XMLHttpRequest' };
      if (shareToken) headers['X-Share-Token'] = shareToken;
      const res = await fetch(`/kanban/api/boards/${boardId}/background`, {
        method: 'DELETE',
        headers,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.success === false) throw new Error(data.error || 'Fehler');
      if (data.board) {
        Object.assign(board, data.board);
        applyBoardPageBackground(data.board);
      }
    } catch (err) {
      notify(err.message || 'Fehler');
    }
  });

  document.getElementById('kanbanShareForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await api(`/kanban/api/boards/${boardId}/shares`, {
        method: 'POST',
        body: Object.fromEntries(fd.entries()),
      });
      e.target.reset();
      openShareModal();
    } catch (err) {
      notify(err.message || 'Link konnte nicht erstellt werden');
    }
  });

  document.getElementById('kanbanShareEditForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const id = document.getElementById('kanbanShareEditId')?.value;
    if (!id) return;
    const body = {
      mode: document.getElementById('kanbanShareEditMode')?.value || 'view',
      clear_password: !!document.getElementById('kanbanShareClearPassword')?.checked,
    };
    const pw = (document.getElementById('kanbanShareEditPassword')?.value || '').trim();
    if (pw && !body.clear_password) body.password = pw;
    try {
      await api(`/kanban/api/boards/${boardId}/shares/${id}`, { method: 'PATCH', body });
      getModal('kanbanShareEditModal')?.hide();
      openShareModal();
    } catch (err) {
      notify(err.message || 'Speichern fehlgeschlagen');
    }
  });

  document.getElementById('kanbanSaveTemplateBtn')?.addEventListener('click', async () => {
    const name = await askPrompt(i18n.saveTemplate || 'Vorlagenname', board.title, {
      title: i18n.saveTemplate || 'Als Vorlage',
    });
    if (name == null || !String(name).trim()) return;
    try {
      await api('/kanban/api/templates', { method: 'POST', body: { board_id: boardId, name: String(name).trim() } });
      notify('Vorlage gespeichert. Beim Anlegen eines neuen Boards kannst du sie auswählen.', 'success');
    } catch (err) {
      notify(err.message || 'Vorlage konnte nicht gespeichert werden');
    }
  });

  let filterTimer = null;
  const filterState = {
    q: '',
    no_members: false,
    assigned_to_me: false,
    assignee_ids: [],
    completed: null,
    no_labels: false,
    label_ids: [],
    due: '',
    activity: '',
    collapse_empty: false,
  };

  function populateFilterOptions() {
    const memRoot = document.getElementById('kanbanFilterMembers');
    if (memRoot) {
      memRoot.innerHTML = (board.members || []).map((m) =>
        `<label class="kanban-filter-member-row">
          <input type="checkbox" data-filter-assignee="${m.id}" ${filterState.assignee_ids.includes(m.id) ? 'checked' : ''}>
          ${avatarHtml(m)}
          <span>${esc(m.name || '')}</span>
        </label>`
      ).join('');
    }
    const lbRoot = document.getElementById('kanbanFilterLabels');
    if (lbRoot) {
      lbRoot.innerHTML = (board.labels || []).map((lb) =>
        `<label class="kanban-filter-label-row">
          <input type="checkbox" data-filter-label="${lb.id}" ${filterState.label_ids.includes(lb.id) ? 'checked' : ''}>
          ${labelChipHtml(lb)}
        </label>`
      ).join('');
    }
    const kw = document.getElementById('kanbanFilterKeyword');
    if (kw) kw.value = filterState.q || '';
    const noMem = document.getElementById('kanbanFilterNoMembers');
    if (noMem) noMem.checked = !!filterState.no_members;
    const me = document.getElementById('kanbanFilterAssignedMe');
    if (me) me.checked = !!filterState.assigned_to_me;
    const done = document.getElementById('kanbanFilterCompleted');
    const notDone = document.getElementById('kanbanFilterNotCompleted');
    if (done) done.checked = filterState.completed === true;
    if (notDone) notDone.checked = filterState.completed === false;
    const noLb = document.getElementById('kanbanFilterNoLabels');
    if (noLb) noLb.checked = !!filterState.no_labels;
    document.querySelectorAll('input[name="kanbanFilterDue"]').forEach((el) => {
      el.checked = el.value === (filterState.due || '');
    });
    document.querySelectorAll('input[name="kanbanFilterActivity"]').forEach((el) => {
      el.checked = el.value === (filterState.activity || '');
    });
    const collapse = document.getElementById('kanbanFilterCollapseEmpty');
    if (collapse) collapse.checked = !!filterState.collapse_empty;
  }

  function readFilterState() {
    filterState.q = (document.getElementById('kanbanFilterKeyword')?.value || '').trim();
    filterState.no_members = !!document.getElementById('kanbanFilterNoMembers')?.checked;
    filterState.assigned_to_me = !!document.getElementById('kanbanFilterAssignedMe')?.checked;
    filterState.assignee_ids = filterState.no_members
      ? []
      : Array.from(document.querySelectorAll('[data-filter-assignee]:checked')).map((el) => Number(el.dataset.filterAssignee));
    const completed = !!document.getElementById('kanbanFilterCompleted')?.checked;
    const notCompleted = !!document.getElementById('kanbanFilterNotCompleted')?.checked;
    if (completed && !notCompleted) filterState.completed = true;
    else if (notCompleted && !completed) filterState.completed = false;
    else filterState.completed = null;
    filterState.no_labels = !!document.getElementById('kanbanFilterNoLabels')?.checked;
    filterState.label_ids = filterState.no_labels
      ? []
      : Array.from(document.querySelectorAll('[data-filter-label]:checked')).map((el) => Number(el.dataset.filterLabel));
    filterState.due = document.querySelector('input[name="kanbanFilterDue"]:checked')?.value || '';
    filterState.activity = document.querySelector('input[name="kanbanFilterActivity"]:checked')?.value || '';
    filterState.collapse_empty = !!document.getElementById('kanbanFilterCollapseEmpty')?.checked;
  }

  function countActiveFilters() {
    let n = 0;
    if (filterState.q) n += 1;
    if (filterState.no_members) n += 1;
    if (filterState.assigned_to_me) n += 1;
    if (filterState.assignee_ids.length) n += 1;
    if (filterState.completed !== null) n += 1;
    if (filterState.no_labels) n += 1;
    if (filterState.label_ids.length) n += 1;
    if (filterState.due) n += 1;
    if (filterState.activity) n += 1;
    return n;
  }

  function updateFilterBadge() {
    const badge = document.getElementById('kanbanFilterBadge');
    if (!badge) return;
    const n = countActiveFilters();
    badge.hidden = n === 0;
    badge.textContent = String(n);
    document.getElementById('kanbanFilterBtn')?.classList.toggle('is-active', n > 0);
  }

  async function applyFilters() {
    readFilterState();
    updateFilterBadge();
    const active = countActiveFilters() > 0;
    if (!active) {
      listsEl.querySelectorAll('.kanban-card').forEach((el) => el.classList.remove('is-filtered-out'));
      listsEl.querySelectorAll('.kanban-list-col').forEach((el) => el.classList.remove('is-collapsed-by-filter'));
      return;
    }
    try {
      const body = {
        q: filterState.q || undefined,
        no_members: filterState.no_members || undefined,
        assigned_to_me: filterState.assigned_to_me || undefined,
        assignee_ids: filterState.assignee_ids.length ? filterState.assignee_ids : undefined,
        no_labels: filterState.no_labels || undefined,
        label_ids: filterState.label_ids.length ? filterState.label_ids : undefined,
        due: filterState.due || undefined,
        activity: filterState.activity || undefined,
      };
      if (filterState.completed === true) body.completed = true;
      if (filterState.completed === false) body.completed = false;
      const data = await api(`/kanban/api/boards/${boardId}/filter`, {
        method: 'POST',
        body,
      });
      const ids = new Set(data.card_ids || []);
      listsEl.querySelectorAll('.kanban-card').forEach((el) => {
        el.classList.toggle('is-filtered-out', !ids.has(Number(el.dataset.cardId)));
      });
      listsEl.querySelectorAll('.kanban-list-col').forEach((col) => {
        if (!filterState.collapse_empty) {
          col.classList.remove('is-collapsed-by-filter');
          return;
        }
        const cards = col.querySelectorAll('.kanban-card');
        const anyVisible = Array.from(cards).some((c) => !c.classList.contains('is-filtered-out'));
        col.classList.toggle('is-collapsed-by-filter', cards.length > 0 && !anyVisible);
      });
    } catch (err) {
      console.warn('Kanban filter failed', err);
    }
  }

  function scheduleFilter() {
    clearTimeout(filterTimer);
    filterTimer = setTimeout(applyFilters, 150);
  }

  document.getElementById('kanbanFilterBtn')?.addEventListener('click', () => {
    populateFilterOptions();
    getModal('kanbanFilterModal')?.show();
  });

  document.getElementById('kanbanFilterReset')?.addEventListener('click', () => {
    filterState.q = '';
    filterState.no_members = false;
    filterState.assigned_to_me = false;
    filterState.assignee_ids = [];
    filterState.completed = null;
    filterState.no_labels = false;
    filterState.label_ids = [];
    filterState.due = '';
    filterState.activity = '';
    filterState.collapse_empty = false;
    populateFilterOptions();
    applyFilters();
  });

  document.getElementById('kanbanFilterApply')?.addEventListener('click', () => {
    applyFilters();
  });

  document.getElementById('kanbanFilterPanel')?.addEventListener('input', scheduleFilter);
  document.getElementById('kanbanFilterPanel')?.addEventListener('change', (ev) => {
    const t = ev.target;
    if (!t) return;
    // Status: nur eine Option gleichzeitig
    if (t.id === 'kanbanFilterCompleted' && t.checked) {
      const other = document.getElementById('kanbanFilterNotCompleted');
      if (other) other.checked = false;
    }
    if (t.id === 'kanbanFilterNotCompleted' && t.checked) {
      const other = document.getElementById('kanbanFilterCompleted');
      if (other) other.checked = false;
    }
    // Keine Mitglieder vs. konkrete Mitglieder
    if (t.id === 'kanbanFilterNoMembers' && t.checked) {
      document.querySelectorAll('[data-filter-assignee]').forEach((el) => { el.checked = false; });
      const me = document.getElementById('kanbanFilterAssignedMe');
      if (me) me.checked = false;
    }
    if ((t.dataset && t.dataset.filterAssignee) || t.id === 'kanbanFilterAssignedMe') {
      if (t.checked) {
        const none = document.getElementById('kanbanFilterNoMembers');
        if (none) none.checked = false;
      }
    }
    if (t.id === 'kanbanFilterNoLabels' && t.checked) {
      document.querySelectorAll('[data-filter-label]').forEach((el) => { el.checked = false; });
    }
    if (t.dataset && t.dataset.filterLabel && t.checked) {
      const none = document.getElementById('kanbanFilterNoLabels');
      if (none) none.checked = false;
    }
    scheduleFilter();
  });

  function connectSSE() {
    const url = app.dataset.sseUrl;
    if (!url || !window.EventSource) {
      setInterval(async () => {
        if (document.hidden || ignoreSSE) return;
        try {
          const data = await api(`/kanban/api/boards/${boardId}`);
          if (data.lists) {
            board.lists = data.lists;
            board.labels = data.labels;
            board.members = data.members || board.members;
            renderBoardMembers();
            renderBoard();
          }
        } catch (_) { /* ignore */ }
      }, 8000);
      return;
    }
    try {
      const es = new EventSource(url);
      es.onmessage = (ev) => {
        if (ignoreSSE) return;
        try {
          handleLiveEvent(JSON.parse(ev.data));
        } catch (_) { /* ignore */ }
      };
      ['kanban:card_created', 'kanban:card_updated', 'kanban:card_moved', 'kanban:card_deleted',
        'kanban:list_created', 'kanban:list_updated', 'kanban:list_deleted', 'kanban:lists_reordered',
        'kanban:board_updated', 'kanban:label_created', 'kanban:members_updated',
        'kanban:custom_field_created', 'kanban:custom_field_updated', 'kanban:custom_field_deleted'].forEach((name) => {
        es.addEventListener(name, (ev) => {
          if (ignoreSSE) return;
          try { handleLiveEvent({ event: name, data: JSON.parse(ev.data) }); } catch (_) {}
        });
      });
    } catch (_) { /* ignore */ }
  }

  function handleLiveEvent(msg) {
    const event = msg.event || '';
    const data = msg.data || msg;
    if (event.includes('label_created') && data.id) {
      board.labels = board.labels || [];
      if (!board.labels.some((l) => l.id === data.id)) board.labels.push(data);
      return;
    }
    if (event.includes('custom_field')) {
      refreshBoard();
      return;
    }
    if (event.includes('members_updated')) {
      refreshBoard();
      return;
    }
    if (event.includes('card_deleted') || (data.id && event.includes('deleted') && !data.list_id)) {
      for (const l of board.lists) {
        l.cards = (l.cards || []).filter((c) => c.id !== (data.id || data.card_id));
      }
      renderBoard();
      return;
    }
    if (data.list_id || data.cards || (data.title && data.card_count != null)) {
      refreshBoard();
      return;
    }
    if (data.id && data.list_id) {
      upsertCardLocal(data);
      renderBoard();
    }
  }

  async function refreshBoard() {
    try {
      const data = await api(`/kanban/api/boards/${boardId}`);
      if (data.lists) {
        board.lists = data.lists;
        board.labels = data.labels || board.labels;
        board.members = data.members || board.members;
        if (data.custom_fields) board.custom_fields = data.custom_fields;
        renderBoardMembers();
        renderBoard();
      }
    } catch (_) { /* ignore */ }
  }

  if (new URLSearchParams(window.location.search).get('share') === '1' && canManage) {
    setTimeout(openShareModal, 400);
  }

  const params = new URLSearchParams(window.location.search);
  if (params.get('card')) {
    setTimeout(() => openCard(Number(params.get('card'))), 300);
  }

  renderBoardMembers();
  renderBoard();
  connectSSE();
})();
