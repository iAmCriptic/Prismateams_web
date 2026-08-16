(function () {
  const app = document.getElementById('kanbanBoardApp');
  if (!app || !window.KANBAN_BOARD) return;

  const board = window.KANBAN_BOARD;
  board.lists = board.lists || [];
  board.labels = board.labels || [];

  const canEdit = app.dataset.canEdit === '1';
  const canManage = app.dataset.canManage === '1';
  const boardId = board.id;
  const i18n = window.KANBAN_I18N || {};
  let currentCardId = null;
  let currentCardDetail = null;
  let commentSystem = null;
  let ignoreSSE = false;
  let cardModal = null;
  const sortableInstances = [];

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

  async function api(url, opts) {
    const res = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
        ...((opts && opts.headers) || {}),
      },
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
        animation: 150,
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
            alert(err.message || 'Verschieben fehlgeschlagen');
            refreshBoard();
          }
          ignoreSSE = false;
        },
      }));
    });
    sortableInstances.push(Sortable.create(listsEl, {
      animation: 150,
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
          alert(err.message || 'Sortieren fehlgeschlagen');
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
        alert('Liste konnte nicht erstellt werden');
      }
    } catch (err) {
      alert(err.message || 'Liste konnte nicht erstellt werden');
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
        alert('Karte konnte nicht erstellt werden');
      }
    } catch (err) {
      alert(err.message || 'Karte konnte nicht erstellt werden');
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
      const name = prompt(i18n.listName || 'Listenname', list.title || '');
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
        alert(err.message || 'Umbenennen fehlgeschlagen');
      }
      return;
    }

    const deleteListBtn = e.target.closest('[data-list-delete]');
    if (deleteListBtn) {
      e.preventDefault();
      const listId = Number(deleteListBtn.getAttribute('data-list-delete'));
      if (!confirm('Liste und alle Karten löschen?')) return;
      try {
        await api(`/kanban/api/lists/${listId}`, { method: 'DELETE' });
        board.lists = board.lists.filter((l) => l.id !== listId);
        renderBoard();
      } catch (err) {
        alert(err.message || 'Löschen fehlgeschlagen');
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
      alert(err.message || 'Karte konnte nicht geladen werden');
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
            alert(err.message || 'Verschieben fehlgeschlagen');
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

    const clRoot = document.getElementById('cardChecklists');
    clRoot.innerHTML = (card.checklists || []).map((cl) => `
      <div class="kanban-checklist" data-checklist-id="${cl.id}">
        <strong>${esc(cl.title)}</strong>
        ${(cl.items || []).map((it) => `
          <label class="kanban-checklist-item">
            <input type="checkbox" data-item-id="${it.id}" ${it.done ? 'checked' : ''} ${canEdit ? '' : 'disabled'}>
            <span>${esc(it.text)}</span>
          </label>`).join('')}
        ${canEdit ? `<form class="kanban-add-item-form mt-2" data-checklist-id="${cl.id}">
          <input class="form-control form-control-sm kanban-pill-input" name="text" placeholder="Item…">
        </form>` : ''}
      </div>`).join('');

    clRoot.querySelectorAll('input[type=checkbox][data-item-id]').forEach((cb) => {
      cb.addEventListener('change', async () => {
        try {
          const r = await api(`/kanban/api/checklist-items/${cb.dataset.itemId}`, {
            method: 'PATCH', body: { done: cb.checked },
          });
          if (r.card) upsertCardLocal(r.card);
        } catch (err) {
          alert(err.message || 'Fehler');
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
          alert(err.message || 'Fehler');
        }
      });
    });

    const attRoot = document.getElementById('cardAttachments');
    attRoot.innerHTML = (card.attachments || []).map((a) => `
      <div class="kanban-attach-row">
        ${a.is_link
          ? `<i class="bi bi-link-45deg"></i>`
          : (a.is_image ? `<img class="kanban-attach-thumb" src="${esc(a.preview_url)}" alt="">` : `<i class="bi bi-file-earmark"></i>`)}
        <a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.filename)}</a>
        ${a.onlyoffice_url ? `<a class="btn btn-sm kanban-pill-btn" href="${esc(a.onlyoffice_url)}"><i class="bi bi-pencil-square me-1"></i>OnlyOffice</a>` : ''}
        ${canEdit && a.is_image ? `<button type="button" class="btn btn-sm kanban-pill-btn" data-set-cover="${a.id}">Titelbild</button>` : ''}
        ${!a.is_link && (a.is_pdf || a.is_image) ? `<a class="btn btn-sm kanban-pill-btn" href="${esc(a.preview_url)}" target="_blank">Vorschau</a>` : ''}
        ${canEdit ? `<button type="button" class="btn btn-sm kanban-pill-btn kanban-pill-btn--ghost" data-del-att="${a.id}"><i class="bi bi-trash"></i></button>` : ''}
      </div>`).join('') || '<p class="text-muted small">Keine Anhänge</p>';

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
          alert(err.message || 'Fehler');
        }
      });
    });
    attRoot.querySelectorAll('[data-del-att]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!confirm('Anhang löschen?')) return;
        try {
          await api(`/kanban/api/attachments/${btn.getAttribute('data-del-att')}`, { method: 'DELETE' });
          openCard(cardId);
          refreshBoard();
        } catch (err) {
          alert(err.message || 'Fehler');
        }
      });
    });

    // Comments – Form klonen, damit Listener nicht doppelt hängen
    const commentsRoot = document.getElementById('kanbanCardComments');
    if (commentsRoot) {
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
        commentSystem = new CommentSystem('kanban_card', cardId, 'kanbanCardComments');
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
          alert('Keine Abstimmung vorhanden');
          return;
        }
        document.getElementById('kanbanPollInput').value = '';
        getModal('kanbanPollModal')?.show();
        return;
      }
      await toggleVote();
    } catch (err) {
      alert(err.message || 'Fehler');
    }
  });

  document.getElementById('cardPollVoteBtn')?.addEventListener('click', async () => {
    try {
      await toggleVote();
    } catch (err) {
      alert(err.message || 'Fehler');
    }
  });

  document.getElementById('cardPollEditBtn')?.addEventListener('click', () => {
    const text = document.getElementById('cardPollText')?.textContent || '';
    document.getElementById('kanbanPollInput').value = text;
    getModal('kanbanPollModal')?.show();
  });

  document.getElementById('cardPollClearBtn')?.addEventListener('click', async () => {
    if (!confirm('Abstimmung entfernen?')) return;
    try {
      await savePollText('');
      getModal('kanbanPollModal')?.hide();
    } catch (err) {
      alert(err.message || 'Fehler');
    }
  });

  document.getElementById('kanbanPollSave')?.addEventListener('click', async () => {
    const text = (document.getElementById('kanbanPollInput')?.value || '').trim();
    if (!text) {
      alert('Bitte Text eingeben');
      return;
    }
    try {
      await savePollText(text);
      getModal('kanbanPollModal')?.hide();
    } catch (err) {
      alert(err.message || 'Fehler');
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
      alert(err.message || 'Fehler');
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
      alert(err.message || 'Fehler');
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
      alert(err.message || 'Link konnte nicht hinzugefügt werden');
    }
  });

  async function uploadCardFile(file, { asCover } = {}) {
    if (!file || !currentCardId) return;
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(`/kanban/api/cards/${currentCardId}/attachments`, {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
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
      alert(err.message || 'Upload fehlgeschlagen');
    }
  });

  document.getElementById('cardAttachFile')?.addEventListener('change', async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = '';
    if (!file) return;
    try {
      await uploadCardFile(file, { asCover: false });
    } catch (err) {
      alert(err.message || 'Upload fehlgeschlagen');
    }
  });

  document.getElementById('cardDeleteBtn')?.addEventListener('click', async () => {
    if (!currentCardId || !confirm('Karte löschen?')) return;
    try {
      await api(`/kanban/api/cards/${currentCardId}`, { method: 'DELETE' });
      ensureCardModal()?.hide();
      for (const l of board.lists) {
        l.cards = (l.cards || []).filter((c) => c.id !== currentCardId);
      }
      currentCardId = null;
      renderBoard();
    } catch (err) {
      alert(err.message || 'Fehler');
    }
  });

  document.getElementById('cardModalTitle')?.addEventListener('change', async (e) => {
    if (!canEdit || !currentCardId) return;
    try {
      const r = await api(`/kanban/api/cards/${currentCardId}`, { method: 'PATCH', body: { title: e.target.value } });
      if (r.card) { upsertCardLocal(r.card); renderBoard(); }
    } catch (err) {
      alert(err.message || 'Fehler');
    }
  });
  document.getElementById('cardModalDescription')?.addEventListener('change', async (e) => {
    if (!canEdit || !currentCardId) return;
    try {
      await api(`/kanban/api/cards/${currentCardId}`, { method: 'PATCH', body: { description: e.target.value } });
    } catch (err) {
      alert(err.message || 'Fehler');
    }
  });

  document.getElementById('cardAddChecklist')?.addEventListener('click', async () => {
    if (!currentCardId) return;
    const title = prompt('Checkliste', 'Checkliste');
    if (!title) return;
    try {
      await api(`/kanban/api/cards/${currentCardId}/checklists`, { method: 'POST', body: { title } });
      openCard(currentCardId);
    } catch (err) {
      alert(err.message || 'Fehler');
    }
  });

  document.getElementById('cardAddDue')?.addEventListener('click', () => {
    if (!currentCardId) return;
    const input = document.getElementById('kanbanDueInput');
    if (input) input.value = toDatetimeLocalValue(currentCardDetail && currentCardDetail.due_date);
    getModal('kanbanDueModal')?.show();
  });

  document.getElementById('kanbanDueForm')?.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!currentCardId) return;
    const val = document.getElementById('kanbanDueInput')?.value || '';
    try {
      await api(`/kanban/api/cards/${currentCardId}`, {
        method: 'PATCH',
        body: { due_date: val || null },
      });
      getModal('kanbanDueModal')?.hide();
      openCard(currentCardId);
      refreshBoard();
    } catch (err) {
      alert(err.message || 'Fehler');
    }
  });

  document.getElementById('kanbanDueClear')?.addEventListener('click', async () => {
    if (!currentCardId) return;
    try {
      await api(`/kanban/api/cards/${currentCardId}`, {
        method: 'PATCH',
        body: { due_date: null },
      });
      getModal('kanbanDueModal')?.hide();
      openCard(currentCardId);
      refreshBoard();
    } catch (err) {
      alert(err.message || 'Fehler');
    }
  });

  function renderMembersPicker() {
    const list = document.getElementById('kanbanMembersList');
    if (!list) return;
    const assigned = new Set((currentCardDetail && currentCardDetail.assignees || []).map((a) => a.id));
    const members = board.members || [];
    list.innerHTML = members.map((m) =>
      `<button type="button" class="kanban-label-pick-btn${assigned.has(m.id) ? ' is-on' : ''}" data-user-id="${m.id}">
        ${avatarHtml(m)}
        <span>${esc(m.name || '')}</span>
      </button>`
    ).join('') || '<p class="text-muted small">Keine Mitglieder</p>';
    list.querySelectorAll('[data-user-id]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        try {
          const r = await api(`/kanban/api/cards/${currentCardId}/assignees`, {
            method: 'POST',
            body: { user_id: Number(btn.dataset.userId) },
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
        } catch (err) {
          alert(err.message || 'Fehler');
        }
      });
    });
  }

  document.getElementById('cardAddMembers')?.addEventListener('click', () => {
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
          alert(err.message || 'Fehler');
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
      alert(err.message || 'Fehler');
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
          alert(btn.getAttribute('data-copy-share'));
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
        if (!confirm('Freigabelink löschen?')) return;
        try {
          await api(`/kanban/api/boards/${boardId}/shares/${btn.getAttribute('data-del-share')}`, { method: 'DELETE' });
          openShareModal();
        } catch (err) {
          alert(err.message || 'Löschen fehlgeschlagen');
        }
      });
    });
  }

  document.getElementById('kanbanShareBtn')?.addEventListener('click', (e) => {
    e.preventDefault();
    openShareModal();
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
      alert(err.message || 'Link konnte nicht erstellt werden');
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
      alert(err.message || 'Speichern fehlgeschlagen');
    }
  });

  document.getElementById('kanbanSaveTemplateBtn')?.addEventListener('click', async () => {
    const name = prompt(i18n.saveTemplate || 'Vorlagenname', board.title);
    if (!name) return;
    try {
      await api('/kanban/api/templates', { method: 'POST', body: { board_id: boardId, name } });
      alert('Vorlage gespeichert. Beim Anlegen eines neuen Boards kannst du sie auswählen.');
    } catch (err) {
      alert(err.message || 'Vorlage konnte nicht gespeichert werden');
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
        'kanban:board_updated', 'kanban:label_created', 'kanban:members_updated'].forEach((name) => {
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
