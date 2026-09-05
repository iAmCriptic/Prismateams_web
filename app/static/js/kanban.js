(function () {
  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  var _inlineRenameActive = null;
  var bgMap = {};
  (window.KANBAN_BACKGROUNDS || []).forEach(function (b) {
    bgMap[b.key] = b.css;
  });

  // Overview: list/grid toggle (Files-kompatibel: indicator + data-view + active)
  var listBtn = qs('#kanbanListViewBtn');
  var gridBtn = qs('#kanbanGridViewBtn');
  var viewToggle = qs('.kanban-toolbar .files-view-toggle') || qs('.files-view-toggle');
  function applyView(mode) {
    if (mode !== 'list' && mode !== 'grid') mode = 'grid';
    localStorage.setItem('kanbanViewMode', mode);
    qsa('[data-view-grid]').forEach(function (el) {
      el.style.display = mode === 'grid' ? '' : 'none';
    });
    qsa('[data-view-list]').forEach(function (el) {
      el.style.display = mode === 'list' ? '' : 'none';
    });
    if (viewToggle) viewToggle.dataset.view = mode;
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
          if (typeof window.showAppBanner === 'function') window.showAppBanner(data.error, 'danger');
          else alert(data.error);
          return;
        }
        var title = (data.board && data.board.title) || name;
        cancelInlineRename();
        updateBoardTitles(id, title);
      }).catch(function () {
        if (typeof window.showAppBanner === 'function') window.showAppBanner('Fehler beim Umbenennen', 'danger');
        else alert('Fehler beim Umbenennen');
      });
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

  function applyBoardColor(id, key, coverUrl) {
    var css = bgMap[key] || bgMap.teal || '';
    qsa('[data-board-cover="' + id + '"]').forEach(function (el) {
      el.style.background = css;
      var img = el.querySelector('[data-board-cover-img="' + id + '"], .kanban-grid-cover__img');
      var icon = el.querySelector('.bi-kanban');
      if (coverUrl) {
        if (img) {
          img.src = coverUrl;
          img.hidden = false;
        } else {
          el.insertAdjacentHTML('afterbegin', '<img src="' + coverUrl + '" alt="" class="kanban-grid-cover__img" data-board-cover-img="' + id + '">');
        }
        if (icon) icon.remove();
      } else if (coverUrl === null || coverUrl === '') {
        if (img) img.remove();
        if (!el.querySelector('.bi-kanban')) {
          el.insertAdjacentHTML('beforeend', '<i class="bi bi-kanban text-white" aria-hidden="true"></i>');
        }
      }
    });
    qsa('[data-board-swatch="' + id + '"]').forEach(function (el) {
      el.style.background = css;
    });
    qsa('[data-kanban-color="' + id + '"]').forEach(function (btn) {
      btn.setAttribute('data-kanban-bg', key);
    });
  }

  function setColorImageHint(hasImage) {
    var hint = qs('#kanbanColorImageHint');
    if (hint) hint.hidden = !hasImage;
  }

  function openColorModal(id, currentBg, title, hasCover) {
    closeOpenDropdowns();
    qs('#kanbanColorBoardId').value = id;
    qs('#kanbanColorSelected').value = currentBg || 'teal';
    qs('#kanbanColorModalTitle').textContent = title || '';
    qsa('#kanbanColorPicker .kanban-bg-swatch').forEach(function (btn) {
      btn.classList.toggle('is-active', btn.dataset.bg === (currentBg || 'teal'));
    });
    var fileInput = qs('#kanbanColorImageInput');
    if (fileInput) fileInput.value = '';
    setColorImageHint(!!hasCover);
    var modal = bootstrap.Modal.getOrCreateInstance(qs('#kanbanColorModal'));
    modal.show();
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
    var id = btn.getAttribute('data-kanban-color');
    var hasCover = !!document.querySelector('[data-board-cover-img="' + id + '"]');
    openColorModal(
      id,
      btn.getAttribute('data-kanban-bg') || 'teal',
      btn.getAttribute('data-kanban-title') || '',
      hasCover
    );
  };

  window.kanbanCloseBoard = async function (btn) {
    if (!btn) return;
    var id = btn.getAttribute('data-kanban-close');
    if (!id) return;
    var ok = typeof window.ptConfirm === 'function'
      ? await window.ptConfirm('Board schließen?', { danger: true, confirmLabel: 'Schließen', title: 'Board schließen' })
      : window.confirm('Board schließen?');
    if (!ok) return;
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
        if (typeof window.showAppBanner === 'function') window.showAppBanner(data.error || 'Fehler', 'danger');
        else alert(data.error || 'Fehler');
      }
    } catch (err) {
      if (typeof window.showAppBanner === 'function') window.showAppBanner('Fehler', 'danger');
      else alert('Fehler');
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
      var board = data.board || {};
      applyBoardColor(id, board.background || bg, board.cover_path || undefined);
      bootstrap.Modal.getInstance(qs('#kanbanColorModal'))?.hide();
    } else {
      if (typeof window.showAppBanner === 'function') window.showAppBanner(data.error || 'Fehler', 'danger');
      else alert(data.error || 'Fehler');
    }
  });

  qs('#kanbanColorImageUpload')?.addEventListener('click', async function () {
    var id = qs('#kanbanColorBoardId').value;
    var input = qs('#kanbanColorImageInput');
    if (!id || !input || !input.files || !input.files[0]) return;
    var fd = new FormData();
    fd.append('file', input.files[0]);
    var res = await fetch('/kanban/api/boards/' + id + '/background', {
      method: 'POST',
      body: fd,
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    });
    var data = await res.json().catch(function () { return {}; });
    if (data.success !== false && res.ok) {
      var board = data.board || {};
      applyBoardColor(id, board.background || qs('#kanbanColorSelected').value || 'teal', board.cover_path || null);
      setColorImageHint(!!board.cover_path);
      input.value = '';
    } else if (typeof window.showAppBanner === 'function') {
      window.showAppBanner(data.error || 'Fehler', 'danger');
    } else {
      alert(data.error || 'Fehler');
    }
  });

  qs('#kanbanColorImageClear')?.addEventListener('click', async function () {
    var id = qs('#kanbanColorBoardId').value;
    if (!id) return;
    var res = await fetch('/kanban/api/boards/' + id + '/background', {
      method: 'DELETE',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    });
    var data = await res.json().catch(function () { return {}; });
    if (data.success !== false && res.ok) {
      var board = data.board || {};
      applyBoardColor(id, board.background || qs('#kanbanColorSelected').value || 'teal', null);
      setColorImageHint(false);
    }
  });

  // Create board modal
  var form = qs('#createBoardForm');
  if (form) {
    var templateWrap = qs('#boardTemplateWrap');
    var templateSelect = qs('#boardTemplate');
    var createModal = qs('#createBoardModal');
    var bgImageInput = qs('#boardBackgroundImage');

    if (window.InventoryPillSelect) {
      window.InventoryPillSelect.enhanceAll(createModal || form);
    }
    if (createModal) {
      createModal.addEventListener('shown.bs.modal', function () {
        if (window.InventoryPillSelect) {
          window.InventoryPillSelect.enhanceAll(createModal);
        }
      });
    }

    function syncCreateMode() {
      var mode = (form.querySelector('input[name="create_mode"]:checked') || {}).value || 'empty';
      if (templateWrap) templateWrap.style.display = mode === 'template' ? '' : 'none';
      if (templateSelect) {
        templateSelect.required = mode === 'template';
        if (mode !== 'template') {
          templateSelect.value = '';
          if (window.InventoryPillSelect) window.InventoryPillSelect.sync(templateSelect);
        }
      }
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
      var imageFile = bgImageInput && bgImageInput.files && bgImageInput.files[0] ? bgImageInput.files[0] : null;
      var payload = Object.fromEntries(fd.entries());
      delete payload.create_mode;
      delete payload.background_image;
      var visVal = String(payload.visibility || '');
      if (visVal.indexOf('team:') === 0) {
        payload.visibility = 'team';
        payload.team_id = visVal.slice(5);
      } else {
        delete payload.team_id;
      }
      if (mode !== 'template' || !payload.template_id) {
        delete payload.template_id;
      }
      if (mode === 'template' && !payload.template_id) {
        if (typeof window.showAppBanner === 'function') window.showAppBanner('Bitte eine Vorlage wählen', 'warning');
        else alert('Bitte eine Vorlage wählen');
        return;
      }
      var submitBtn = form.querySelector('[type="submit"]');
      if (submitBtn) submitBtn.disabled = true;
      try {
        var res = await fetch('/kanban/api/boards', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
          body: JSON.stringify(payload)
        });
        var data = await res.json();
        if (!(data.success && data.board)) {
          if (typeof window.showAppBanner === 'function') window.showAppBanner(data.error || 'Fehler', 'danger');
          else alert(data.error || 'Fehler');
          return;
        }
        if (imageFile && data.board.id) {
          var imgFd = new FormData();
          imgFd.append('file', imageFile);
          var imgRes = await fetch('/kanban/api/boards/' + data.board.id + '/background', {
            method: 'POST',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            body: imgFd
          });
          var imgData = await imgRes.json().catch(function () { return {}; });
          if (!imgRes.ok || imgData.success === false) {
            if (typeof window.showAppBanner === 'function') {
              window.showAppBanner(imgData.error || 'Board erstellt, Bild-Upload fehlgeschlagen', 'warning');
            }
          }
        }
        window.location.href = data.board.url;
      } catch (err) {
        if (typeof window.showAppBanner === 'function') window.showAppBanner(err.message || 'Fehler', 'danger');
        else alert(err.message || 'Fehler');
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }
})();
