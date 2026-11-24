(function () {
  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  var idxI18n = window.KANBAN_INDEX_I18N || {};
  var _inlineRenameActive = null;
  var bgMap = {};
  (window.KANBAN_BACKGROUNDS || []).forEach(function (b) {
    bgMap[b.key] = b.css;
  });

  // Overview: list/grid toggle (Files-kompatibel: indicator + data-view + active)
  var listBtn = qs('#kanbanListViewBtn');
  var gridBtn = qs('#kanbanGridViewBtn');
  var viewToggle = qs('.kanban-toolbar .mod-view-toggle') || qs('.mod-view-toggle');
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
        var text = el.querySelector('.mod-item-name-text');
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
    input.className = 'form-control form-control-sm mod-pill-input';
    input.value = currentName || '';
    input.setAttribute('aria-label', idxI18n.rename || 'Umbenennen');

    var saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.className = 'btn btn-sm btn-accent mod-pill-btn';
    saveBtn.innerHTML = '<i class="bi bi-check"></i>';
    saveBtn.title = idxI18n.save || 'Speichern';

    var cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'btn btn-sm btn-secondary mod-pill-btn';
    cancelBtn.innerHTML = '<i class="bi bi-x"></i>';
    cancelBtn.title = idxI18n.cancel || 'Abbrechen';

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
        var msg = idxI18n.renameFailed || 'Fehler beim Umbenennen';
        if (typeof window.showAppBanner === 'function') window.showAppBanner(msg, 'danger');
        else alert(msg);
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
          var newImg = document.createElement('img');
          newImg.src = coverUrl;
          newImg.alt = '';
          newImg.className = 'kanban-grid-cover__img';
          newImg.setAttribute('data-board-cover-img', String(id));
          el.insertBefore(newImg, el.firstChild);
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
      ? await window.ptConfirm(idxI18n.closeConfirm || 'Board schließen?', {
          danger: true,
          confirmLabel: idxI18n.closeBtn || 'Schließen',
          title: idxI18n.closeConfirm || 'Board schließen'
        })
      : window.confirm(idxI18n.closeConfirm || 'Board schließen?');
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
      if (templateWrap) templateWrap.hidden = mode !== 'template';
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
        var warn = idxI18n.chooseTemplate || 'Bitte eine Vorlage wählen';
        if (typeof window.showAppBanner === 'function') window.showAppBanner(warn, 'warning');
        else alert(warn);
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

  // Live unread notification badges on board cards
  async function refreshBoardUnreadCounts() {
    try {
      var res = await fetch('/kanban/api/boards/unread_counts', {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      });
      if (!res.ok) return;
      var data = await res.json();
      var counts = data.unread_counts || {};

      qsa('[data-board-wrapper]').forEach(function (wrapper) {
        var boardId = wrapper.dataset.boardWrapper;
        var count = counts[boardId] || counts[String(boardId)] || 0;
        var cover = wrapper.querySelector('.kanban-grid-cover');
        var badge = wrapper.querySelector('.kanban-board-unread-badge');

        if (count > 0) {
          if (!badge && cover) {
            badge = document.createElement('span');
            badge.className = 'position-absolute top-0 end-0 m-2 badge rounded-pill bg-danger kanban-board-unread-badge';
            badge.dataset.boardUnreadBadge = boardId;
            cover.appendChild(badge);
          }
          if (badge) {
            var unreadLabel = count + ' ' + (count > 1 ? (idxI18n.unreadMany || 'neue Benachrichtigungen') : (idxI18n.unreadOne || 'neue Benachrichtigung'));
            badge.textContent = String(count);
            badge.title = unreadLabel;
            badge.setAttribute('aria-label', unreadLabel);
            badge.style.display = '';
          }
        } else if (badge) {
          badge.remove();
        }
      });
    } catch (_) {}
  }

  window.addEventListener('focus', function () {
    refreshBoardUnreadCounts();
  });

  // Stellt sicher, dass das ⋮-Menü auf Index-Karten immer über allen Nachbarkarten & Sektionen liegt
  document.addEventListener('show.bs.dropdown', function (e) {
    var toggle = e.target;
    var card = toggle.closest ? toggle.closest('.kanban-board-card') : null;
    if (card) {
      card.classList.add('has-dropdown-open');
      var wrapper = card.closest('[data-board-wrapper]');
      if (wrapper) wrapper.classList.add('has-dropdown-open');
      var section = card.closest('.kanban-section');
      if (section) section.classList.add('has-dropdown-open');
    }
  });

  document.addEventListener('hidden.bs.dropdown', function (e) {
    var toggle = e.target;
    var card = toggle.closest ? toggle.closest('.kanban-board-card') : null;
    if (card) {
      card.classList.remove('has-dropdown-open');
      var wrapper = card.closest('[data-board-wrapper]');
      if (wrapper) wrapper.classList.remove('has-dropdown-open');
      var section = card.closest('.kanban-section');
      if (section) section.classList.remove('has-dropdown-open');
    }
    document.querySelectorAll('.has-dropdown-open').forEach(function (el) {
      if (!el.querySelector('.dropdown-menu.show')) {
        el.classList.remove('has-dropdown-open');
      }
    });
  });

  // Live-Suche nach Boards auf der Startseite (Navbar & Mobile)
  (function initKanbanBoardSearch() {
    var inputs = [
      qs('#kanbanIndexSearchInput'),
      qs('#kanbanIndexSearchInputMobile')
    ].filter(Boolean);
    var clearBtns = [
      qs('#kanbanIndexSearchClear'),
      qs('#kanbanIndexSearchClearMobile')
    ].filter(Boolean);
    var emptyHint = qs('#kanbanBoardSearchEmpty');

    if (!inputs.length) return;

    function applySearch(rawQuery) {
      var query = (rawQuery || '').trim().toLowerCase();

      clearBtns.forEach(function (btn) {
        btn.classList.toggle('d-none', !query);
      });

      var boardWrappers = qsa('[data-board-wrapper]');
      var totalVisible = 0;

      boardWrappers.forEach(function (el) {
        var name = (el.getAttribute('data-board-search-name') || '').toLowerCase();
        var team = (el.getAttribute('data-board-search-team') || '').toLowerCase();
        var match = !query || name.includes(query) || team.includes(query);
        el.classList.toggle('d-none', !match);
        if (match) totalVisible++;
      });

      // Filter sections: hide sections that have no visible boards when searching
      qsa('.kanban-section').forEach(function (sec) {
        if (!query) {
          sec.classList.remove('d-none');
        } else {
          var itemsInSec = sec.querySelectorAll('[data-board-wrapper]:not(.d-none)');
          sec.classList.toggle('d-none', itemsInSec.length === 0);
        }
      });

      if (emptyHint) {
        emptyHint.classList.toggle('d-none', !(query && boardWrappers.length > 0 && totalVisible === 0));
      }
    }

    inputs.forEach(function (input) {
      input.addEventListener('input', function () {
        var val = input.value;
        inputs.forEach(function (other) {
          if (other !== input) other.value = val;
        });
        applySearch(val);
      });
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          var hasMore = !!document.querySelector('[data-lazy-has-more="1"]');
          if (hasMore) {
            e.preventDefault();
            var url = new URL(window.location.href);
            var q = (input.value || '').trim();
            if (q) url.searchParams.set('q', q);
            else url.searchParams.delete('q');
            window.location.href = url.toString();
          }
          return;
        }
        if (e.key === 'Escape' && input.value) {
          e.preventDefault();
          inputs.forEach(function (inp) { inp.value = ''; });
          applySearch('');
        }
      });
    });

    clearBtns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        inputs.forEach(function (inp) {
          inp.value = '';
        });
        if (inputs[0]) inputs[0].focus();
        applySearch('');
      });
    });

    if (inputs[0] && inputs[0].value) {
      applySearch(inputs[0].value);
    }
  })();

  // Board zwischen Bereichen verschieben (Modal + Drag & Drop, inkl. Berechtigungsanpassung)
  function moveBoardToArea(boardId, visibility, teamId) {
    if (!boardId || !visibility) return Promise.resolve();
    return fetch('/kanban/api/boards/' + boardId, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify({
        visibility: visibility,
        team_id: visibility === 'team' ? (teamId ? Number(teamId) : null) : null
      })
    }).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok || (!data.success && data.error)) {
          throw new Error((data && data.error) || (idxI18n.moveFailed || 'Verschieben fehlgeschlagen'));
        }
        location.reload();
      });
    }).catch(function (err) {
      var msg = (err && err.message) || (idxI18n.moveFailed || 'Verschieben fehlgeschlagen');
      if (typeof window.showAppBanner === 'function') window.showAppBanner(msg, 'danger');
      else alert(msg);
    });
  }

  window.kanbanOpenMove = function (btn) {
    closeOpenDropdowns();
    var boardId = btn && btn.getAttribute('data-kanban-move');
    if (!boardId) return;
    var title = btn.getAttribute('data-kanban-title') || '';
    var vis = btn.getAttribute('data-kanban-vis') || 'private';
    var teamId = btn.getAttribute('data-kanban-team-id') || '';

    var idInput = qs('#kanbanMoveBoardId');
    var nameEl = qs('#kanbanMoveBoardName');
    var selectEl = qs('#kanbanMoveBoardTarget');
    if (idInput) idInput.value = boardId;
    if (nameEl) nameEl.textContent = title;
    if (selectEl) {
      var val = vis === 'team' && teamId ? ('team:' + teamId) : vis;
      selectEl.value = val;
      selectEl.dispatchEvent(new Event('change', { bubbles: true }));
    }
    var modalEl = qs('#kanbanMoveBoardModal');
    if (modalEl && window.bootstrap && window.bootstrap.Modal) {
      window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  };

  var moveSaveBtn = qs('#kanbanMoveBoardSave');
  if (moveSaveBtn) {
    moveSaveBtn.addEventListener('click', function () {
      var boardId = (qs('#kanbanMoveBoardId') || {}).value;
      var rawTarget = (qs('#kanbanMoveBoardTarget') || {}).value || '';
      if (!boardId || !rawTarget) return;
      var vis = rawTarget;
      var teamId = null;
      if (rawTarget.indexOf('team:') === 0) {
        vis = 'team';
        teamId = Number(rawTarget.slice(5));
      }
      moveSaveBtn.disabled = true;
      moveBoardToArea(boardId, vis, teamId).finally(function () {
        moveSaveBtn.disabled = false;
      });
    });
  }

  (function initBoardSectionDragDrop() {
    var dragState = null;

    document.addEventListener('dragstart', function (e) {
      var item = e.target && e.target.closest ? e.target.closest('[data-board-id][data-board-manage="1"]') : null;
      if (!item) return;
      if (e.target.closest('.dropdown, button, input')) {
        e.preventDefault();
        return;
      }
      dragState = {
        boardId: item.getAttribute('data-board-id'),
        vis: item.getAttribute('data-board-vis') || '',
        teamId: item.getAttribute('data-board-team-id') || ''
      };
      item.classList.add('is-dragging');
      document.body.classList.add('kanban-board-dragging');
      if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', dragState.boardId);
      }
    });

    document.addEventListener('dragend', function () {
      dragState = null;
      document.body.classList.remove('kanban-board-dragging');
      qsa('.is-dragging').forEach(function (el) { el.classList.remove('is-dragging'); });
      qsa('.kanban-section.is-drop-target').forEach(function (sec) { sec.classList.remove('is-drop-target'); });
    });

    qsa('.kanban-section[data-drop-visibility]').forEach(function (sec) {
      function isDifferentTarget() {
        if (!dragState) return false;
        var targetVis = sec.getAttribute('data-drop-visibility') || '';
        var targetTeam = sec.getAttribute('data-drop-team-id') || '';
        return targetVis !== dragState.vis || targetTeam !== dragState.teamId;
      }

      sec.addEventListener('dragover', function (e) {
        if (!isDifferentTarget()) return;
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
        sec.classList.add('is-drop-target');
      });

      sec.addEventListener('dragenter', function (e) {
        if (!isDifferentTarget()) return;
        e.preventDefault();
        sec.classList.add('is-drop-target');
      });

      sec.addEventListener('dragleave', function (e) {
        if (e.relatedTarget && sec.contains(e.relatedTarget)) return;
        sec.classList.remove('is-drop-target');
      });

      sec.addEventListener('drop', function (e) {
        if (!isDifferentTarget()) return;
        e.preventDefault();
        sec.classList.remove('is-drop-target');
        var targetVis = sec.getAttribute('data-drop-visibility') || '';
        var targetTeam = sec.getAttribute('data-drop-team-id') || '';
        var bId = dragState.boardId;
        dragState = null;
        document.body.classList.remove('kanban-board-dragging');
        moveBoardToArea(bId, targetVis, targetTeam || null);
      });
    });
  })();
})();
