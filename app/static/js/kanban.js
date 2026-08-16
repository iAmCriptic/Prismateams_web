(function () {
  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  var _inlineRenameActive = null;
  var bgMap = {};
  (window.KANBAN_BACKGROUNDS || []).forEach(function (b) {
    bgMap[b.key] = b.css;
  });

  // Overview: list/grid toggle (Files-kompatibel: active + is-active)
  var listBtn = qs('#kanbanListViewBtn');
  var gridBtn = qs('#kanbanGridViewBtn');
  function applyView(mode) {
    localStorage.setItem('kanbanViewMode', mode);
    qsa('[data-view-grid]').forEach(function (el) {
      el.style.display = mode === 'grid' ? '' : 'none';
    });
    qsa('[data-view-list]').forEach(function (el) {
      el.style.display = mode === 'list' ? '' : 'none';
    });
    if (listBtn && gridBtn) {
      listBtn.classList.toggle('active', mode === 'list');
      listBtn.classList.toggle('is-active', mode === 'list');
      gridBtn.classList.toggle('active', mode === 'grid');
      gridBtn.classList.toggle('is-active', mode === 'grid');
    }
  }
  if (listBtn && gridBtn) {
    listBtn.addEventListener('click', function () { applyView('list'); });
    gridBtn.addEventListener('click', function () { applyView('grid'); });
    applyView(localStorage.getItem('kanbanViewMode') || 'grid');
  }

  function closeOpenDropdowns() {
    try {
      qsa('.dropdown-menu.show').forEach(function (m) { m.classList.remove('show'); });
      qsa('.dropdown.show').forEach(function (d) { d.classList.remove('show'); });
    } catch (e) { /* ignore */ }
  }

  function isVisible(el) {
    if (!el || !el.getClientRects || !el.getClientRects().length) return false;
    var style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') return false;
    var node = el;
    while (node && node !== document.body) {
      var cs = window.getComputedStyle(node);
      if (cs.display === 'none' || cs.visibility === 'hidden') return false;
      node = node.parentElement;
    }
    return true;
  }

  function cancelInlineRename() {
    if (!_inlineRenameActive) return;
    try {
      _inlineRenameActive.el.outerHTML = _inlineRenameActive.restoreHtml;
    } catch (e) { /* ignore */ }
    _inlineRenameActive = null;
  }

  function visibleRenameTarget(id, preferRoot) {
    var sel = '[data-rename-target="board-' + id + '"]';
    if (preferRoot) {
      var local = preferRoot.querySelector(sel);
      if (local && isVisible(local)) return local;
    }
    return qsa(sel).find(isVisible) || null;
  }

  function updateBoardTitles(id, title) {
    qsa('[data-rename-target="board-' + id + '"]').forEach(function (el) {
      if (el.classList.contains('files-inline-rename')) return;
      if (el.tagName === 'A') {
        var text = el.querySelector('.files-item-name-text');
        if (text) {
          text.textContent = title;
          text.setAttribute('title', title);
        }
      } else {
        var link = el.querySelector('a');
        if (link) {
          link.textContent = title;
        } else {
          el.textContent = title;
        }
        el.setAttribute('title', title);
      }
    });
    qsa('[data-kanban-rename="' + id + '"]').forEach(function (btn) {
      btn.setAttribute('data-kanban-title', title);
    });
    qsa('[data-kanban-color="' + id + '"]').forEach(function (btn) {
      btn.setAttribute('data-kanban-title', title);
    });
  }

  function startInlineRename(id, currentName, preferRoot) {
    closeOpenDropdowns();
    cancelInlineRename();
    var target = visibleRenameTarget(id, preferRoot);
    if (!target) return;

    var restoreHtml = target.outerHTML;
    var wrap = document.createElement('div');
    wrap.className = 'files-inline-rename';
    wrap.setAttribute('data-rename-target', 'board-' + id);
    wrap.addEventListener('click', function (e) { e.stopPropagation(); e.preventDefault(); });

    var input = document.createElement('input');
    input.type = 'text';
    input.className = 'form-control form-control-sm files-pill-input';
    input.value = currentName || '';
    input.setAttribute('aria-label', 'Umbenennen');

    var saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.className = 'btn btn-sm btn-accent files-pill-btn';
    saveBtn.innerHTML = '<i class="bi bi-check"></i>';
    saveBtn.title = 'Speichern';

    var cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'btn btn-sm btn-secondary files-pill-btn';
    cancelBtn.innerHTML = '<i class="bi bi-x"></i>';
    cancelBtn.title = 'Abbrechen';

    wrap.appendChild(input);
    wrap.appendChild(saveBtn);
    wrap.appendChild(cancelBtn);
    target.replaceWith(wrap);
    _inlineRenameActive = { el: wrap, restoreHtml };
    setTimeout(function () { input.focus(); input.select(); }, 0);

    function submitRename() {
      var name = (input.value || '').trim();
      if (!name) { input.focus(); return; }
      fetch('/kanban/api/boards/' + id, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify({ title: name })
      }).then(function (r) { return r.json(); }).then(function (data) {
        if (!data.success && data.error) {
          alert(data.error);
          return;
        }
        var title = (data.board && data.board.title) || name;
        cancelInlineRename();
        updateBoardTitles(id, title);
      }).catch(function () { alert('Fehler beim Umbenennen'); });
    }

    saveBtn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      submitRename();
    });
    cancelBtn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      cancelInlineRename();
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); submitRename(); }
      if (e.key === 'Escape') { e.preventDefault(); cancelInlineRename(); }
    });
  }

  function openColorModal(id, currentBg, title) {
    closeOpenDropdowns();
    qs('#kanbanColorBoardId').value = id;
    qs('#kanbanColorSelected').value = currentBg || 'teal';
    qs('#kanbanColorModalTitle').textContent = title || '';
    qsa('#kanbanColorPicker .kanban-bg-swatch').forEach(function (btn) {
      btn.classList.toggle('is-active', btn.dataset.bg === (currentBg || 'teal'));
    });
    var modal = bootstrap.Modal.getOrCreateInstance(qs('#kanbanColorModal'));
    modal.show();
  }

  function applyBoardColor(id, key) {
    var css = bgMap[key] || bgMap.teal || '';
    qsa('[data-board-cover="' + id + '"]').forEach(function (el) {
      el.style.background = css;
    });
    qsa('[data-board-swatch="' + id + '"]').forEach(function (el) {
      el.style.background = css;
    });
    qsa('[data-kanban-color="' + id + '"]').forEach(function (btn) {
      btn.setAttribute('data-kanban-bg', key);
    });
  }

  window.kanbanStartRename = function (btn) {
    if (!btn) return;
    var id = btn.getAttribute('data-kanban-rename');
    if (!id) return;
    startInlineRename(
      id,
      btn.getAttribute('data-kanban-title') || '',
      btn.closest('[data-board-wrapper]')
    );
  };

  window.kanbanOpenColor = function (btn) {
    if (!btn) return;
    openColorModal(
      btn.getAttribute('data-kanban-color'),
      btn.getAttribute('data-kanban-bg') || 'teal',
      btn.getAttribute('data-kanban-title') || ''
    );
  };

  window.kanbanCloseBoard = async function (btn) {
    if (!btn) return;
    var id = btn.getAttribute('data-kanban-close');
    if (!id || !confirm('Board schließen?')) return;
    closeOpenDropdowns();
    try {
      var res = await fetch('/kanban/api/boards/' + id, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify({ closed: true })
      });
      var data = await res.json().catch(function () { return {}; });
      if (data.success !== false && res.ok) {
        qsa('[data-board-wrapper="' + id + '"]').forEach(function (el) { el.remove(); });
      } else {
        alert(data.error || 'Fehler');
      }
    } catch (err) {
      alert('Fehler');
    }
  };

  qsa('#kanbanColorPicker .kanban-bg-swatch').forEach(function (btn) {
    btn.addEventListener('click', function () {
      qsa('#kanbanColorPicker .kanban-bg-swatch').forEach(function (b) { b.classList.remove('is-active'); });
      btn.classList.add('is-active');
      qs('#kanbanColorSelected').value = btn.dataset.bg;
    });
  });

  qs('#kanbanColorSave')?.addEventListener('click', async function () {
    var id = qs('#kanbanColorBoardId').value;
    var bg = qs('#kanbanColorSelected').value || 'teal';
    if (!id) return;
    var res = await fetch('/kanban/api/boards/' + id, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify({ background: bg })
    });
    var data = await res.json().catch(function () { return {}; });
    if (data.success !== false && res.ok) {
      applyBoardColor(id, (data.board && data.board.background) || bg);
      bootstrap.Modal.getInstance(qs('#kanbanColorModal'))?.hide();
    } else {
      alert(data.error || 'Fehler');
    }
  });

  // Create board modal
  var form = qs('#createBoardForm');
  if (form) {
    var vis = qs('#boardVisibility');
    var teamWrap = qs('#boardTeamWrap');
    var templateWrap = qs('#boardTemplateWrap');
    var templateSelect = qs('#boardTemplate');

    function syncTeam() {
      if (teamWrap) teamWrap.style.display = vis && vis.value === 'team' ? '' : 'none';
    }
    function syncCreateMode() {
      var mode = (form.querySelector('input[name="create_mode"]:checked') || {}).value || 'empty';
      if (templateWrap) templateWrap.style.display = mode === 'template' ? '' : 'none';
      if (templateSelect) {
        templateSelect.required = mode === 'template';
        if (mode !== 'template') templateSelect.value = '';
      }
    }
    if (vis) {
      vis.addEventListener('change', syncTeam);
      syncTeam();
    }
    qsa('input[name="create_mode"]', form).forEach(function (radio) {
      radio.addEventListener('change', syncCreateMode);
    });
    syncCreateMode();

    qsa('#createBoardForm .kanban-bg-swatch').forEach(function (btn) {
      btn.addEventListener('click', function () {
        qsa('#createBoardForm .kanban-bg-swatch').forEach(function (b) { b.classList.remove('is-active'); });
        btn.classList.add('is-active');
        var input = qs('#boardBackground');
        if (input) input.value = btn.dataset.bg;
      });
    });
    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      var fd = new FormData(form);
      var mode = fd.get('create_mode') || 'empty';
      var payload = Object.fromEntries(fd.entries());
      delete payload.create_mode;
      if (!payload.team_id) delete payload.team_id;
      if (mode !== 'template' || !payload.template_id) {
        delete payload.template_id;
      }
      if (mode === 'template' && !payload.template_id) {
        alert('Bitte eine Vorlage wählen');
        return;
      }
      var res = await fetch('/kanban/api/boards', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify(payload)
      });
      var data = await res.json();
      if (data.success && data.board) {
        window.location.href = data.board.url;
      } else {
        alert(data.error || 'Fehler');
      }
    });
  }
})();
