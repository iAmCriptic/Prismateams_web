/* ToDos Modul – Interaktive Checkliste, Pool-Übernahme, Suche & Modals */
(function () {
  'use strict';

  const shell = document.getElementById('todosShell');
  if (!shell) return;

  const section = shell.dataset.section || 'private';
  const teamId = shell.dataset.teamId ? parseInt(shell.dataset.teamId, 10) : null;
  const viewMode = shell.dataset.view || 'today';
  const i18n = window.TODOS_I18N || {};

  function getCsrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
  }

  async function api(url, options) {
    const opts = Object.assign({
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      credentials: 'same-origin',
    }, options || {});
    const res = await fetch(url, opts);
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    return res.json();
  }

  function esc(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
  }

  function renderItemRow(item) {
    const isTodo = item.source === 'todo';
    const doneCls = item.is_completed ? ' is-done' : '';
    const editableCls = isTodo && item.can_edit ? ' is-editable' : '';
    const disabledAttr = item.can_edit ? '' : 'disabled';

    let sourceHtml = '';
    if (item.source_url && item.source_label) {
      const iconCls = item.source === 'kanban' ? 'bi-kanban' : 'bi-calendar2-week';
      sourceHtml = `<a class="todo-item-row__source" href="${esc(item.source_url)}"><i class="bi ${iconCls}" aria-hidden="true"></i><span>${esc(item.source_label)}</span></a>`;
    } else if (item.source_label && section === 'private') {
      sourceHtml = `<span class="todo-item-row__source"><i class="bi bi-people" aria-hidden="true"></i><span>${esc(item.source_label)}</span></span>`;
    }

    let claimHtml = '';
    if (item.can_claim) {
      claimHtml = `<button type="button" class="todo-item-row__claim-btn" data-todo-claim="${item.id}">${esc(i18n.claim || 'Übernehmen')}</button>`;
    }

    let dueHtml = '';
    if (item.due_label) {
      const dueBtnAttr = isTodo && item.can_edit ? `data-todo-due="${item.id}"` : 'disabled';
      dueHtml = `<button type="button" class="todo-item-row__due todo-item-row__due--${esc(item.due_state)}" ${dueBtnAttr} title="${esc(item.due_label)}"><i class="bi bi-calendar-event" aria-hidden="true"></i><span>${esc(item.due_label)}</span></button>`;
    } else if (isTodo && item.can_edit) {
      dueHtml = `<button type="button" class="todo-item-row__icon-btn" data-todo-due="${item.id}" title="${esc(i18n.addDue || 'Datum setzen')}" aria-label="${esc(i18n.addDue || 'Datum setzen')}"><i class="bi bi-calendar-plus" aria-hidden="true"></i></button>`;
    }

    let avatarHtml = '';
    if (item.assignee) {
      const assignAttr = isTodo && item.visibility !== 'private' && item.can_edit ? `data-todo-assignee="${item.id}"` : 'disabled';
      if (item.assignee.avatar_url) {
        avatarHtml = `<button type="button" class="todo-item-row__avatar" ${assignAttr} title="${esc(item.assignee.name)}"><img src="${esc(item.assignee.avatar_url)}" alt="${esc(item.assignee.name)}"></button>`;
      } else {
        avatarHtml = `<button type="button" class="todo-item-row__avatar" ${assignAttr} title="${esc(item.assignee.name)}"><span>${esc(item.assignee.initials)}</span></button>`;
      }
    } else if (isTodo && item.visibility !== 'private' && item.can_edit) {
      avatarHtml = `<button type="button" class="todo-item-row__icon-btn" data-todo-assignee="${item.id}" title="${esc(i18n.assign || 'Zuweisen')}" aria-label="${esc(i18n.assign || 'Zuweisen')}"><i class="bi bi-person-plus" aria-hidden="true"></i></button>`;
    }

    let deleteHtml = '';
    if (item.can_delete) {
      deleteHtml = `<button type="button" class="btn btn-sm btn-link text-muted p-1" data-todo-delete="${item.id}" title="${esc(i18n.deleteItem || 'Löschen')}" aria-label="${esc(i18n.deleteItem || 'Löschen')}"><i class="bi bi-trash" aria-hidden="true"></i></button>`;
    }

    return `
      <div class="todo-item-row${doneCls}"
           data-source="${esc(item.source)}"
           data-item-id="${item.id}"
           data-due-date="${esc(item.due_date || '')}"
           data-due-time="${esc(item.due_time || '')}"
           data-assignee-id="${esc(item.assignee_id || '')}">
        <input type="checkbox" class="form-check-input todo-item-row__check" ${item.is_completed ? 'checked' : ''} ${disabledAttr} aria-label="${esc(item.title)}">
        <div class="todo-item-row__body">
          <span class="todo-item-row__text${editableCls}">${esc(item.title)}</span>
          ${sourceHtml}
        </div>
        <div class="todo-item-row__meta">
          ${claimHtml}
          ${dueHtml}
          ${avatarHtml}
          ${deleteHtml}
        </div>
      </div>`;
  }

  function getSearchValue() {
    const desktop = document.getElementById('todosSearchInput');
    const mobile = document.getElementById('todosSearchInputMobile');
    return (desktop && desktop.value) || (mobile && mobile.value) || '';
  }

  async function reloadItems() {
    const params = new URLSearchParams({
      section,
      view: viewMode,
      q: getSearchValue().trim(),
    });
    if (teamId) params.set('team_id', String(teamId));
    const data = await api(`/todos/api/items?${params.toString()}`, { method: 'GET' });

    const openList = document.getElementById('todosOpenList');
    const openCard = document.getElementById('todosOpenCard');
    const emptyState = document.getElementById('todosEmptyState');
    const completedSection = document.getElementById('todosCompletedSection');
    const completedList = document.getElementById('todosCompletedList');
    const completedCount = document.getElementById('todosCompletedCount');

    openList.innerHTML = (data.open_items || []).map(renderItemRow).join('');
    completedList.innerHTML = (data.completed_items || []).map(renderItemRow).join('');

    const hasOpen = (data.open_items || []).length > 0;
    openCard.classList.toggle('d-none', !hasOpen);
    emptyState.classList.toggle('d-none', hasOpen);

    const compLen = (data.completed_items || []).length;
    completedCount.textContent = String(compLen);
    completedSection.classList.toggle('d-none', compLen === 0);
  }

  // Create Todo
  const createForm = document.getElementById('createTodoForm');
  if (createForm) {
    createForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const titleInput = document.getElementById('createTodoTitle');
      const dueInput = document.getElementById('createTodoDueDate');
      const timeInput = document.getElementById('createTodoDueTime');
      const assigneeSelect = document.getElementById('createTodoAssignee');
      const title = (titleInput.value || '').trim();
      if (!title) return;

      await api('/todos/api/items', {
        method: 'POST',
        body: JSON.stringify({
          title,
          visibility: section,
          team_id: teamId,
          due_date: dueInput ? dueInput.value || null : null,
          due_time: timeInput ? timeInput.value || null : null,
          assignee_id: assigneeSelect && assigneeSelect.value ? parseInt(assigneeSelect.value, 10) : null,
        }),
      });

      titleInput.value = '';
      if (timeInput) timeInput.value = '';
      if (assigneeSelect) assigneeSelect.value = '';
      bootstrap.Modal.getOrCreateInstance(document.getElementById('createTodoModal')).hide();
      await reloadItems();
    });
  }

  // Due Modal
  let activeDueItemId = null;
  const dueModalEl = document.getElementById('todoDueModal');
  const dueForm = document.getElementById('todoDueForm');
  const dueDateInput = document.getElementById('todoDueDateInput');
  const dueTimeInput = document.getElementById('todoDueTimeInput');
  const dueClearBtn = document.getElementById('todoDueClearBtn');

  if (dueForm) {
    dueForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!activeDueItemId) return;
      await api(`/todos/api/items/todo/${activeDueItemId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          due_date: dueDateInput.value || null,
          due_time: dueTimeInput.value || null,
        }),
      });
      bootstrap.Modal.getOrCreateInstance(dueModalEl).hide();
      await reloadItems();
    });
  }

  if (dueClearBtn) {
    dueClearBtn.addEventListener('click', async () => {
      if (!activeDueItemId) return;
      await api(`/todos/api/items/todo/${activeDueItemId}`, {
        method: 'PATCH',
        body: JSON.stringify({ due_date: null, due_time: null }),
      });
      bootstrap.Modal.getOrCreateInstance(dueModalEl).hide();
      await reloadItems();
    });
  }

  // Assignee Modal
  let activeAssigneeItemId = null;
  const assigneeModalEl = document.getElementById('todoAssigneeModal');
  if (assigneeModalEl) {
    assigneeModalEl.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-assign-user]');
      if (!btn || !activeAssigneeItemId) return;
      const val = btn.dataset.assignUser;
      await api(`/todos/api/items/todo/${activeAssigneeItemId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          assignee_id: val ? parseInt(val, 10) : null,
        }),
      });
      bootstrap.Modal.getOrCreateInstance(assigneeModalEl).hide();
      await reloadItems();
    });
  }

  // Event delegation on list container
  const listContainer = document.getElementById('todosListContainer');
  if (listContainer) {
    listContainer.addEventListener('change', async (e) => {
      const check = e.target.closest('.todo-item-row__check');
      if (!check) return;
      const row = check.closest('.todo-item-row');
      if (!row) return;
      const source = row.dataset.source;
      const itemId = row.dataset.itemId;
      await api(`/todos/api/items/${source}/${itemId}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_completed: check.checked }),
      });
      await reloadItems();
    });

    listContainer.addEventListener('click', async (e) => {
      const claimBtn = e.target.closest('[data-todo-claim]');
      if (claimBtn) {
        const id = claimBtn.dataset.todoClaim;
        await api(`/todos/api/items/todo/${id}/claim`, { method: 'POST', body: '{}' });
        await reloadItems();
        return;
      }

      const dueBtn = e.target.closest('[data-todo-due]');
      if (dueBtn) {
        const row = dueBtn.closest('.todo-item-row');
        activeDueItemId = dueBtn.dataset.todoDue;
        dueDateInput.value = row?.dataset.dueDate || '';
        dueTimeInput.value = row?.dataset.dueTime || '';
        bootstrap.Modal.getOrCreateInstance(dueModalEl).show();
        return;
      }

      const assignBtn = e.target.closest('[data-todo-assignee]');
      if (assignBtn) {
        activeAssigneeItemId = assignBtn.dataset.todoAssignee;
        bootstrap.Modal.getOrCreateInstance(assigneeModalEl).show();
        return;
      }

      const delBtn = e.target.closest('[data-todo-delete]');
      if (delBtn) {
        const id = delBtn.dataset.todoDelete;
        await api(`/todos/api/items/todo/${id}`, { method: 'DELETE' });
        await reloadItems();
        return;
      }

      const textEl = e.target.closest('.todo-item-row__text.is-editable');
      if (textEl) {
        const row = textEl.closest('.todo-item-row');
        if (!row || row.querySelector('.todo-item-row__input')) return;
        const orig = textEl.textContent;
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'todo-item-row__input';
        input.value = orig;
        textEl.replaceWith(input);
        input.focus();
        input.select();

        let saved = false;
        const commit = async () => {
          if (saved) return;
          saved = true;
          const next = input.value.trim();
          if (next && next !== orig) {
            await api(`/todos/api/items/todo/${row.dataset.itemId}`, {
              method: 'PATCH',
              body: JSON.stringify({ title: next }),
            });
          }
          await reloadItems();
        };
        input.addEventListener('keydown', (ev) => {
          if (ev.key === 'Enter') {
            ev.preventDefault();
            commit();
          } else if (ev.key === 'Escape') {
            saved = true;
            reloadItems();
          }
        });
        input.addEventListener('blur', commit);
      }
    });
  }

  // Search inputs (desktop + mobile)
  let searchTimer = null;
  function bindSearch(inputId, clearId) {
    const input = document.getElementById(inputId);
    const clear = document.getElementById(clearId);
    if (!input) return;
    input.addEventListener('input', () => {
      if (clear) clear.classList.toggle('d-none', !input.value);
      clearTimeout(searchTimer);
      searchTimer = setTimeout(reloadItems, 200);
    });
    if (clear) {
      clear.addEventListener('click', () => {
        input.value = '';
        clear.classList.add('d-none');
        reloadItems();
      });
    }
  }
  bindSearch('todosSearchInput', 'todosSearchClear');
  bindSearch('todosSearchInputMobile', 'todosSearchClearMobile');
})();
