(function () {
  'use strict';

  var root = document.getElementById('importWizardRoot');
  if (!root) return;

  var state = {
    step: 1,
    maxReached: 1,
    source: null, // 'google_drive' | 'nextcloud' | 'kanban'
    kanbanMode: 'trello', // 'trello' | 'file'
    connectionId: null,
    connectionName: '',
    path: '',
    pathStack: [],
    selectedCloud: {},
    trelloConnected: root.getAttribute('data-trello-connected') === '1',
    trelloAccount: ((document.getElementById('trelloAccountLabel') || {}).textContent || '').trim(),
    trelloBoardsLoaded: false,
    selectedTrelloBoards: [],
    selectedFile: null,
    space: null,
    teamId: null,
  };

  function msg(attr) {
    return root.getAttribute('data-i18n-' + attr) || '';
  }

  function csrfHeaders() {
    var token = document.querySelector('meta[name="csrf-token"]');
    var h = { Accept: 'application/json' };
    if (token && token.content) h['X-CSRFToken'] = token.content;
    return h;
  }

  function replaceId(url, id) {
    return (url || '').replace(/\/0(\/|$)/, '/' + id + '$1');
  }

  function formatSize(n) {
    n = Number(n) || 0;
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1024 * 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + ' MB';
    return (n / (1024 * 1024 * 1024)).toFixed(1) + ' GB';
  }

  function showStepError(stepNum, text) {
    var el = document.getElementById('wizardStep' + stepNum + 'Error');
    if (!el) return;
    if (!text) {
      el.classList.add('d-none');
      el.textContent = '';
    } else {
      el.textContent = text;
      el.classList.remove('d-none');
    }
  }

  function clearAllErrors() {
    showStepError(2, '');
    showStepError(3, '');
    showStepError(4, '');
  }

  function toast(text, type) {
    if (window.SettingsToast && text) {
      window.SettingsToast.show(text, type || 'success');
    }
  }

  function isCloudSource() {
    return state.source === 'google_drive' || state.source === 'nextcloud';
  }

  function canAdvanceFromStep(s) {
    if (s === 1) return !!state.source;
    if (s === 2) {
      if (isCloudSource()) return !!state.connectionId;
      if (state.source === 'kanban') {
        return state.kanbanMode === 'file' ? true : state.trelloConnected;
      }
    }
    if (s === 3) {
      if (isCloudSource()) return Object.keys(state.selectedCloud).length > 0;
      if (state.source === 'kanban') {
        if (state.kanbanMode === 'trello') return state.selectedTrelloBoards.length > 0;
        return !!state.selectedFile;
      }
    }
    if (s === 4) {
      if (isCloudSource()) {
        syncSpaceFromUi();
        return !!state.space;
      }
      if (state.source === 'kanban') {
        var sel = document.getElementById('wizardKanbanTarget');
        return !!(sel && sel.value);
      }
    }
    return false;
  }

  function syncFooterButtons() {
    var footer = document.getElementById('wizardFooter');
    var prevBtn = document.getElementById('wizardPrevBtn');
    var nextBtn = document.getElementById('wizardNextBtn');
    var startBtn = document.getElementById('wizardStartBtn');
    if (!footer) return;

    if (state.step === 1) {
      footer.classList.add('d-none');
      return;
    }
    footer.classList.remove('d-none');
    if (prevBtn) prevBtn.disabled = state.step <= 1;

    if (state.step < 4) {
      if (nextBtn) {
        nextBtn.classList.remove('d-none');
        nextBtn.disabled = !canAdvanceFromStep(state.step);
      }
      if (startBtn) startBtn.classList.add('d-none');
    } else {
      if (nextBtn) nextBtn.classList.add('d-none');
      if (startBtn) {
        startBtn.classList.remove('d-none');
        startBtn.disabled = !canAdvanceFromStep(4);
      }
    }
  }

  function renderStepPanels() {
    // Stepper tabs
    root.querySelectorAll('.mailbox-wizard-step').forEach(function (tab) {
      var n = parseInt(tab.getAttribute('data-step-tab'), 10);
      tab.classList.toggle('is-active', n === state.step);
      tab.classList.toggle('is-done', n < state.step);
      if (n === state.step) {
        tab.setAttribute('aria-current', 'step');
      } else {
        tab.removeAttribute('aria-current');
      }
      if (n <= state.maxReached && n !== state.step) {
        tab.setAttribute('data-clickable', '1');
      } else {
        tab.removeAttribute('data-clickable');
      }
    });

    // Main step panels
    root.querySelectorAll('[data-wizard-panel]').forEach(function (panel) {
      var n = parseInt(panel.getAttribute('data-wizard-panel'), 10);
      panel.classList.toggle('d-none', n !== state.step);
    });

    // Step 2 sub-panels
    var authGoogle = document.getElementById('wizardAuthGoogle');
    var authNc = document.getElementById('wizardAuthNextcloud');
    var authKanban = document.getElementById('wizardAuthKanban');
    if (authGoogle) authGoogle.classList.toggle('d-none', state.source !== 'google_drive');
    if (authNc) authNc.classList.toggle('d-none', state.source !== 'nextcloud');
    if (authKanban) authKanban.classList.toggle('d-none', state.source !== 'kanban');

    if (state.source === 'kanban') {
      var trelloAuthBox = document.getElementById('wizardKanbanTrelloAuthBox');
      var fileAuthHint = document.getElementById('wizardKanbanFileAuthHint');
      if (trelloAuthBox) trelloAuthBox.classList.toggle('d-none', state.kanbanMode !== 'trello');
      if (fileAuthHint) fileAuthHint.classList.toggle('d-none', state.kanbanMode !== 'file');
    }

    // Step 3 sub-panels
    var selCloud = document.getElementById('wizardSelectCloud');
    var selTrello = document.getElementById('wizardSelectTrello');
    var selFile = document.getElementById('wizardSelectKanbanFile');
    if (selCloud) selCloud.classList.toggle('d-none', !isCloudSource());
    if (selTrello) selTrello.classList.toggle('d-none', !(state.source === 'kanban' && state.kanbanMode === 'trello'));
    if (selFile) selFile.classList.toggle('d-none', !(state.source === 'kanban' && state.kanbanMode === 'file'));

    // Step 4 sub-panels
    var tgtCloud = document.getElementById('wizardTargetCloud');
    var tgtKanban = document.getElementById('wizardTargetKanban');
    if (tgtCloud) tgtCloud.classList.toggle('d-none', !isCloudSource());
    if (tgtKanban) tgtKanban.classList.toggle('d-none', state.source !== 'kanban');

    syncFooterButtons();
  }

  function updateSummary() {
    var srcEl = document.getElementById('wizardSummarySource');
    var accEl = document.getElementById('wizardSummaryAccount');
    var selEl = document.getElementById('wizardSummarySelection');
    if (!srcEl || !accEl || !selEl) return;

    if (state.source === 'google_drive') {
      srcEl.textContent = msg('src-google');
      accEl.textContent = state.connectionName || '—';
      selEl.textContent = msg('items-count').replace('{count}', String(Object.keys(state.selectedCloud).length));
    } else if (state.source === 'nextcloud') {
      srcEl.textContent = msg('src-nextcloud');
      accEl.textContent = state.connectionName || '—';
      selEl.textContent = msg('items-count').replace('{count}', String(Object.keys(state.selectedCloud).length));
    } else if (state.source === 'kanban' && state.kanbanMode === 'trello') {
      srcEl.textContent = msg('src-kanban-trello');
      accEl.textContent = state.trelloAccount || 'Trello';
      selEl.textContent = msg('boards-count').replace('{count}', String(state.selectedTrelloBoards.length));
    } else if (state.source === 'kanban' && state.kanbanMode === 'file') {
      srcEl.textContent = msg('src-kanban-file');
      accEl.textContent = state.selectedFile ? state.selectedFile.name : '—';
      selEl.textContent = state.selectedFile ? formatSize(state.selectedFile.size) : '—';
    }
  }

  function goToStep(n) {
    clearAllErrors();
    state.step = n;
    if (n > state.maxReached) state.maxReached = n;

    if (n === 3) {
      if (isCloudSource() && state.connectionId) {
        browse('');
      } else if (state.source === 'kanban' && state.kanbanMode === 'trello' && state.trelloConnected && !state.trelloBoardsLoaded) {
        loadTrelloBoards();
      }
    }
    if (n === 4) {
      updateSummary();
      if (isCloudSource()) {
        syncSpaceFromUi();
        loadDestFolders();
      }
      var resBox = document.getElementById('wizardKanbanResults');
      if (resBox) resBox.hidden = true;
    }

    renderStepPanels();
  }

  // Step 1: Source cards
  root.querySelectorAll('.sp-import-source-card').forEach(function (card) {
    card.addEventListener('click', function () {
      var chosen = card.getAttribute('data-source-choice');
      if (!chosen) return;
      if (state.source !== chosen) {
        state.source = chosen;
        state.connectionId = null;
        state.connectionName = '';
        state.path = '';
        state.pathStack = [];
        state.selectedCloud = {};
        state.maxReached = 2;
        root.querySelectorAll('.cloud-import-conn').forEach(function (li) {
          li.classList.remove('active');
        });
      }
      root.querySelectorAll('.sp-import-source-card').forEach(function (c) {
        c.classList.toggle('is-selected', c === card);
      });

      // Auto-select single connection if available for cloud sources
      if (chosen === 'google_drive' || chosen === 'nextcloud') {
        var listId = chosen === 'google_drive' ? 'wizardGoogleConnections' : 'wizardNextcloudConnections';
        var list = document.getElementById(listId);
        if (list) {
          var rows = list.querySelectorAll('.cloud-import-conn');
          if (rows.length === 1) {
            selectCloudConnection(rows[0].getAttribute('data-connection-id'), rows[0].getAttribute('data-display-name'));
          }
        }
      }

      goToStep(2);
    });
  });

  // Stepper tab clicks (allow jumping back to visited steps)
  root.querySelectorAll('.mailbox-wizard-step').forEach(function (tab) {
    tab.addEventListener('click', function () {
      if (tab.getAttribute('data-clickable') !== '1') return;
      var target = parseInt(tab.getAttribute('data-step-tab'), 10);
      if (target >= 1 && target <= state.maxReached) {
        goToStep(target);
      }
    });
  });

  // Wizard Back / Next
  var prevBtn = document.getElementById('wizardPrevBtn');
  if (prevBtn) {
    prevBtn.addEventListener('click', function () {
      if (state.step > 1) goToStep(state.step - 1);
    });
  }

  var nextBtn = document.getElementById('wizardNextBtn');
  if (nextBtn) {
    nextBtn.addEventListener('click', function () {
      if (state.step < 4 && canAdvanceFromStep(state.step)) {
        goToStep(state.step + 1);
      }
    });
  }

  // ── Cloud Connections (Google Drive & Nextcloud) ────────────────────────
  function selectCloudConnection(id, displayName) {
    state.connectionId = id;
    state.connectionName = displayName || '';
    state.path = '';
    state.pathStack = [];
    state.selectedCloud = {};
    root.querySelectorAll('.cloud-import-conn').forEach(function (li) {
      li.classList.toggle('active', String(li.getAttribute('data-connection-id')) === String(id));
    });
    syncFooterButtons();
  }

  function bindConnectionRow(li) {
    var selBtn = li.querySelector('.cloud-import-select-conn');
    if (selBtn) {
      selBtn.addEventListener('click', function () {
        selectCloudConnection(li.getAttribute('data-connection-id'), li.getAttribute('data-display-name'));
      });
    }
    var delBtn = li.querySelector('.cloud-import-delete-conn');
    if (delBtn) {
      delBtn.addEventListener('click', function () {
        var id = li.getAttribute('data-connection-id');
        if (!window.confirm(msg('delete-confirm') || 'OK?')) return;
        fetch(replaceId(root.getAttribute('data-delete-base'), id), {
          method: 'DELETE',
          headers: csrfHeaders(),
          credentials: 'same-origin',
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.ok) {
              if (String(state.connectionId) === String(id)) {
                state.connectionId = null;
                state.connectionName = '';
              }
              li.remove();
              syncFooterButtons();
            } else {
              showStepError(2, data.error || 'Error');
            }
          });
      });
    }
  }

  root.querySelectorAll('.cloud-import-conn').forEach(bindConnectionRow);

  var showNc = document.getElementById('cloudImportShowNextcloud');
  var ncForm = document.getElementById('cloudImportNextcloudForm');
  if (showNc && ncForm) {
    showNc.addEventListener('click', function () {
      ncForm.classList.toggle('d-none');
    });
  }

  var connectNcBtn = document.getElementById('cloudImportConnectNextcloudBtn');
  if (connectNcBtn) {
    connectNcBtn.addEventListener('click', function () {
      showStepError(2, '');
      var server = (document.getElementById('ncServer') || {}).value || '';
      var user = (document.getElementById('ncUser') || {}).value || '';
      var pass = (document.getElementById('ncPass') || {}).value || '';
      connectNcBtn.disabled = true;
      fetch(root.getAttribute('data-url-connect-nextcloud'), {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, csrfHeaders()),
        credentials: 'same-origin',
        body: JSON.stringify({
          server_url: server.trim(),
          username: user.trim(),
          app_password: pass,
        }),
      })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          connectNcBtn.disabled = false;
          if (!res.ok || !res.j.ok) {
            showStepError(2, (res.j && res.j.error) || 'Error');
            return;
          }
          var conn = res.j.connection;
          var list = document.getElementById('wizardNextcloudConnections');
          var empty = document.getElementById('wizardNextcloudEmpty');
          if (empty) empty.remove();
          if (list && conn) {
            var li = document.createElement('li');
            li.className = 'sp-conn-row cloud-import-conn';
            li.setAttribute('data-connection-id', String(conn.id));
            li.setAttribute('data-provider', 'nextcloud');
            li.setAttribute('data-display-name', conn.display_name || 'Nextcloud');
            li.innerHTML =
              '<button type="button" class="sp-conn-select cloud-import-select-conn">' +
              '<i class="bi bi-cloud" aria-hidden="true"></i> <strong></strong></button>' +
              '<button type="button" class="btn btn-sm btn-outline-danger rounded-pill cloud-import-delete-conn" aria-label="' + msg('delete') + '">' +
              '<i class="bi bi-trash" aria-hidden="true"></i></button>';
            li.querySelector('strong').textContent = conn.display_name || 'Nextcloud';
            bindConnectionRow(li);
            list.insertBefore(li, list.firstChild);
            selectCloudConnection(String(conn.id), conn.display_name);
            if (ncForm) ncForm.classList.add('d-none');
            goToStep(3);
          }
        })
        .catch(function () {
          connectNcBtn.disabled = false;
          showStepError(2, 'Error');
        });
    });
  }

  // ── Cloud Browser (Step 3) ──────────────────────────────────────────────
  function browse(path) {
    if (!state.connectionId) return;
    showStepError(3, '');
    var url = replaceId(root.getAttribute('data-browse-base'), state.connectionId) +
      '?path=' + encodeURIComponent(path || '');
    fetch(url, { headers: csrfHeaders(), credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.ok) {
          showStepError(3, data.error || 'Error');
          return;
        }
        state.path = data.path || '';
        var pathEl = document.getElementById('cloudImportBrowsePath');
        if (pathEl) pathEl.textContent = '/' + (state.path || '');
        var up = document.getElementById('cloudImportBrowseUp');
        if (up) up.disabled = !state.path;
        renderBrowse(data.entries || []);
        updateCloudSelectionHint();
      })
      .catch(function () { showStepError(3, 'Error'); });
  }

  function renderBrowse(entries) {
    var tbody = document.getElementById('cloudImportBrowseBody');
    if (!tbody) return;
    tbody.innerHTML = '';
    entries.forEach(function (e) {
      var tr = document.createElement('tr');
      var checked = !!state.selectedCloud[e.id];
      tr.innerHTML =
        '<td><input type="checkbox" class="form-check-input cloud-import-check" ' +
        (checked ? 'checked ' : '') + '></td>' +
        '<td class="cloud-import-name-cell"></td>' +
        '<td class="small text-muted">' + (e.is_dir ? '—' : formatSize(e.size)) + '</td>';
      var nameCell = tr.querySelector('.cloud-import-name-cell');
      var icon = document.createElement('i');
      icon.className = 'bi ' + (e.is_dir ? 'bi-folder' : 'bi-file-earmark') + ' me-2';
      nameCell.appendChild(icon);
      if (e.is_dir) {
        var a = document.createElement('button');
        a.type = 'button';
        a.className = 'btn btn-link p-0 text-decoration-none';
        a.textContent = e.name;
        a.addEventListener('click', function () {
          state.pathStack.push(state.path);
          browse(e.id);
        });
        nameCell.appendChild(a);
      } else {
        nameCell.appendChild(document.createTextNode(e.name));
      }
      var cb = tr.querySelector('.cloud-import-check');
      cb.addEventListener('change', function () {
        if (cb.checked) {
          state.selectedCloud[e.id] = {
            id: e.id,
            name: e.name,
            is_dir: !!e.is_dir,
            size: e.size || 0,
            path: e.path || e.id,
          };
        } else {
          delete state.selectedCloud[e.id];
        }
        updateCloudSelectionHint();
      });
      tbody.appendChild(tr);
    });
  }

  function updateCloudSelectionHint() {
    var n = Object.keys(state.selectedCloud).length;
    var hint = document.getElementById('cloudImportSelectionHint');
    if (hint) {
      hint.textContent = n ? msg('items-count').replace('{count}', String(n)) : '';
    }
    syncFooterButtons();
  }

  var upBtn = document.getElementById('cloudImportBrowseUp');
  if (upBtn) {
    upBtn.addEventListener('click', function () {
      var prev = state.pathStack.pop();
      if (prev === undefined) {
        var parts = (state.path || '').split('/').filter(Boolean);
        parts.pop();
        browse(parts.join('/'));
      } else {
        browse(prev);
      }
    });
  }

  // ── Cloud Target Space & Folders (Step 4) ───────────────────────────────
  function syncSpaceFromUi() {
    var btn = root.querySelector('.cloud-import-space-btn.active');
    if (!btn) {
      state.space = null;
      state.teamId = null;
      return;
    }
    state.space = btn.getAttribute('data-space');
    var tid = btn.getAttribute('data-team-id');
    state.teamId = tid ? parseInt(tid, 10) : null;
  }

  function loadDestFolders() {
    syncSpaceFromUi();
    var sel = document.getElementById('cloudImportDestFolder');
    var urlBase = root.getAttribute('data-url-dest-folders');
    if (!sel || !state.space || !urlBase) return;
    var url = urlBase + '?space=' + encodeURIComponent(state.space) +
      (state.teamId ? '&team_id=' + state.teamId : '');
    fetch(url, { headers: csrfHeaders(), credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.ok) return;
        sel.innerHTML = '';
        var opt0 = document.createElement('option');
        opt0.value = data.root_id != null ? String(data.root_id) : '';
        opt0.textContent = msg('root') || 'Root';
        sel.appendChild(opt0);
        (data.folders || []).forEach(function (f) {
          var o = document.createElement('option');
          o.value = String(f.id);
          o.textContent = f.name;
          sel.appendChild(o);
        });
      })
      .catch(function () {});
  }

  root.querySelectorAll('.cloud-import-space-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      root.querySelectorAll('.cloud-import-space-btn').forEach(function (b) {
        b.classList.remove('active');
        b.setAttribute('aria-pressed', 'false');
      });
      btn.classList.add('active');
      btn.setAttribute('aria-pressed', 'true');
      loadDestFolders();
      syncFooterButtons();
    });
  });

  // ── Kanban Mode & Trello Auth ───────────────────────────────────────────
  root.querySelectorAll('.wizard-kanban-mode-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var mode = btn.getAttribute('data-kanban-mode');
      if (!mode) return;
      state.kanbanMode = mode;
      root.querySelectorAll('.wizard-kanban-mode-btn').forEach(function (b) {
        var active = b === btn;
        b.classList.toggle('active', active);
        b.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
      renderStepPanels();
    });
  });

  var trelloConnectBox = document.getElementById('trelloConnectBox');
  var trelloConnectedBox = document.getElementById('trelloConnectedBox');
  var apiKeyInput = document.getElementById('trelloApiKeyInput');
  var tokenInput = document.getElementById('trelloTokenInput');
  var authorizeBtn = document.getElementById('trelloAuthorizeBtn');
  var manualConnectBtn = document.getElementById('trelloManualConnectBtn');
  var manualTokenLink = document.getElementById('trelloManualTokenLink');
  var trelloAccountLabel = document.getElementById('trelloAccountLabel');
  var refreshBoardsBtn = document.getElementById('trelloRefreshBoardsBtn');
  var disconnectBtn = document.getElementById('trelloDisconnectBtn');
  var boardListEl = document.getElementById('trelloBoardList');

  function buildTrelloTokenUrl(apiKey, withCallback) {
    var cbUrl = root.getAttribute('data-url-trello-callback');
    var base = 'https://trello.com/1/authorize?expiration=1day&name=Prismateams&scope=read&response_type=token&key=' + encodeURIComponent(apiKey);
    if (withCallback && cbUrl) {
      base += '&callback_method=fragment&return_url=' + encodeURIComponent(cbUrl);
    }
    return base;
  }

  if (apiKeyInput && manualTokenLink) {
    apiKeyInput.addEventListener('input', function () {
      var key = (apiKeyInput.value || '').trim();
      if (key) {
        manualTokenLink.href = buildTrelloTokenUrl(key, false);
        manualTokenLink.classList.remove('d-none');
      } else {
        manualTokenLink.classList.add('d-none');
      }
    });
  }

  function renderTrelloBoards(boards) {
    if (!boardListEl) return;
    boardListEl.innerHTML = '';
    state.selectedTrelloBoards = [];
    if (!boards || !boards.length) {
      var empty = document.createElement('p');
      empty.className = 'text-muted small mb-0';
      empty.textContent = msg('trello-no-boards');
      boardListEl.appendChild(empty);
      syncFooterButtons();
      return;
    }
    boards.forEach(function (b) {
      var label = document.createElement('label');
      label.className = 'sp-trello-board-item';
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.className = 'form-check-input mt-0';
      cb.value = b.id;
      cb.addEventListener('change', function () {
        if (cb.checked) {
          state.selectedTrelloBoards.push({ id: b.id, name: b.name });
        } else {
          state.selectedTrelloBoards = state.selectedTrelloBoards.filter(function (x) { return x.id !== b.id; });
        }
        syncFooterButtons();
      });
      var meta = document.createElement('div');
      meta.className = 'min-width-0 flex-grow-1';
      var title = document.createElement('div');
      title.className = 'sp-trello-board-item-title';
      title.textContent = b.name;
      meta.appendChild(title);
      if (b.desc) {
        var desc = document.createElement('div');
        desc.className = 'sp-trello-board-item-desc';
        desc.textContent = b.desc;
        meta.appendChild(desc);
      }
      label.appendChild(cb);
      label.appendChild(meta);
      boardListEl.appendChild(label);
    });
    syncFooterButtons();
  }

  async function loadTrelloBoards() {
    var boardsUrl = root.getAttribute('data-url-trello-boards');
    if (!boardListEl || !boardsUrl) return;
    boardListEl.innerHTML = '<div class="text-muted small">' + msg('trello-loading') + '</div>';
    state.selectedTrelloBoards = [];
    syncFooterButtons();
    try {
      var res = await fetch(boardsUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      var data = await res.json().catch(function () { return {}; });
      if (res.ok && data.success) {
        state.trelloBoardsLoaded = true;
        renderTrelloBoards(data.boards || []);
      } else {
        boardListEl.innerHTML = '';
        showStepError(3, data.error || msg('failed'));
      }
    } catch (_) {
      boardListEl.innerHTML = '';
    }
  }

  async function connectTrello(apiKey, token) {
    var connectUrl = root.getAttribute('data-url-trello-connect');
    if (!apiKey || !token) {
      showStepError(2, msg('need-key-token'));
      return;
    }
    showStepError(2, '');
    try {
      var res = await fetch(connectUrl, {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, csrfHeaders()),
        body: JSON.stringify({ api_key: apiKey, token: token }),
      });
      var data = await res.json().catch(function () { return {}; });
      if (res.ok && data.success && data.profile) {
        var acctText = (data.profile.full_name || '') + (data.profile.username ? ' (@' + data.profile.username + ')' : '');
        state.trelloConnected = true;
        state.trelloAccount = acctText;
        state.trelloBoardsLoaded = false;
        if (trelloAccountLabel) trelloAccountLabel.textContent = acctText;
        if (trelloConnectBox) trelloConnectBox.hidden = true;
        if (trelloConnectedBox) trelloConnectedBox.hidden = false;
        toast(msg('trello-connected'), 'success');
        syncFooterButtons();
      } else {
        showStepError(2, data.error || msg('failed'));
      }
    } catch (_) {
      showStepError(2, msg('failed'));
    }
  }

  if (authorizeBtn) {
    authorizeBtn.addEventListener('click', function () {
      var key = (apiKeyInput && apiKeyInput.value || '').trim();
      if (!key) {
        showStepError(2, msg('need-key'));
        if (apiKeyInput) apiKeyInput.focus();
        return;
      }
      window.open(buildTrelloTokenUrl(key, true), 'trelloAuthorize', 'width=620,height=720,noopener=no');
    });
  }

  window.addEventListener('message', function (ev) {
    if (ev.origin !== window.location.origin) return;
    if (ev.data && ev.data.type === 'prismateams_trello_token' && ev.data.token) {
      var key = (apiKeyInput && apiKeyInput.value || '').trim();
      if (tokenInput) tokenInput.value = ev.data.token;
      connectTrello(key, ev.data.token);
    }
  });

  if (manualConnectBtn) {
    manualConnectBtn.addEventListener('click', function () {
      var key = (apiKeyInput && apiKeyInput.value || '').trim();
      var tok = (tokenInput && tokenInput.value || '').trim();
      connectTrello(key, tok);
    });
  }

  if (refreshBoardsBtn) {
    refreshBoardsBtn.addEventListener('click', loadTrelloBoards);
  }

  if (disconnectBtn) {
    disconnectBtn.addEventListener('click', async function () {
      var discUrl = root.getAttribute('data-url-trello-disconnect');
      try {
        await fetch(discUrl, {
          method: 'POST',
          headers: Object.assign({ 'X-Requested-With': 'XMLHttpRequest' }, csrfHeaders()),
        });
      } catch (_) {}
      state.trelloConnected = false;
      state.trelloAccount = '';
      state.trelloBoardsLoaded = false;
      state.selectedTrelloBoards = [];
      if (trelloConnectedBox) trelloConnectedBox.hidden = true;
      if (trelloConnectBox) trelloConnectBox.hidden = false;
      if (boardListEl) boardListEl.innerHTML = '';
      toast(msg('trello-disconnected'), 'success');
      syncFooterButtons();
    });
  }

  // ── Kanban File Dropzone (Step 3) ───────────────────────────────────────
  var fileInput = document.getElementById('settingsKanbanFile');
  var dropzone = document.getElementById('settingsKanbanDropzone');
  var preview = document.getElementById('settingsKanbanPreview');
  var previewIcon = document.getElementById('settingsKanbanPreviewIcon');
  var previewName = document.getElementById('settingsKanbanPreviewName');
  var previewInfo = document.getElementById('settingsKanbanPreviewInfo');
  var previewClear = document.getElementById('settingsKanbanPreviewClear');

  function setSelectedKanbanFile(file) {
    state.selectedFile = file || null;
    if (!file) {
      if (fileInput) fileInput.value = '';
      if (preview) preview.hidden = true;
      if (dropzone) dropzone.classList.remove('has-file');
      syncFooterButtons();
      return;
    }
    var ext = (file.name.split('.').pop() || '').toUpperCase();
    if (previewName) previewName.textContent = file.name;
    if (previewInfo) previewInfo.textContent = (ext ? ext + ' · ' : '') + formatSize(file.size);
    if (previewIcon) {
      previewIcon.className = ext === 'ZIP'
        ? 'bi bi-file-earmark-zip'
        : (ext === 'CSV' ? 'bi bi-filetype-csv' : 'bi bi-filetype-json');
    }
    if (preview) preview.hidden = false;
    if (dropzone) dropzone.classList.add('has-file');
    syncFooterButtons();
  }

  if (fileInput) {
    fileInput.addEventListener('change', function () {
      setSelectedKanbanFile(fileInput.files && fileInput.files[0]);
    });
  }
  if (previewClear) {
    previewClear.addEventListener('click', function () {
      setSelectedKanbanFile(null);
    });
  }
  if (dropzone) {
    ['dragenter', 'dragover'].forEach(function (evt) {
      dropzone.addEventListener(evt, function (e) {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.add('is-dragover');
      });
    });
    ['dragleave', 'drop'].forEach(function (evt) {
      dropzone.addEventListener(evt, function (e) {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.remove('is-dragover');
      });
    });
    dropzone.addEventListener('drop', function (e) {
      var files = e.dataTransfer && e.dataTransfer.files;
      if (files && files.length) setSelectedKanbanFile(files[0]);
    });
  }

  // ── Start Import (Step 4) ───────────────────────────────────────────────
  function renderKanbanResults(boards) {
    var box = document.getElementById('wizardKanbanResults');
    if (!box) return;
    box.hidden = false;
    box.innerHTML = '';
    boards.forEach(function (b) {
      var row = document.createElement('div');
      row.className = 'sp-import-result is-ok';
      row.innerHTML = '<i class="bi bi-check-circle" aria-hidden="true"></i><span></span>';
      row.querySelector('span').textContent = b.title || b.name || ('#' + b.id);
      if (b.url) {
        var a = document.createElement('a');
        a.href = b.url;
        a.className = 'ms-auto';
        a.textContent = msg('open');
        row.appendChild(a);
      }
      box.appendChild(row);
    });
  }

  function createKanbanJobRow(title, targetLabel, subtitleText) {
    var list = document.getElementById('cloudImportJobs');
    if (!list) {
      return {
        setProgress: function () {},
        setDetail: function () {},
        complete: function () {},
        fail: function () {},
      };
    }
    var empty = document.getElementById('cloudImportEmptyJobs');
    if (empty) empty.remove();

    var li = document.createElement('li');
    li.className = 'sp-job-row kanban-import-job';
    li.setAttribute('data-status', 'running');
    li.innerHTML =
      '<div class="d-flex justify-content-between align-items-start gap-2">' +
      '<div class="min-width-0 flex-grow-1">' +
      '<strong class="kanban-import-job-title"></strong> ' +
      '<span class="badge text-bg-primary ms-1 kanban-import-job-status"></span>' +
      '<div class="small text-muted kanban-import-job-meta"></div>' +
      '</div>' +
      '<div class="kanban-import-job-actions"></div>' +
      '</div>' +
      '<div class="progress mt-2 sp-job-progress">' +
      '<div class="progress-bar progress-bar-striped progress-bar-animated sp-job-bar-slow" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="5" style="width: 5%"></div>' +
      '</div>';

    var titleEl = li.querySelector('.kanban-import-job-title');
    var badgeEl = li.querySelector('.kanban-import-job-status');
    var metaEl = li.querySelector('.kanban-import-job-meta');
    var actionsEl = li.querySelector('.kanban-import-job-actions');
    var barEl = li.querySelector('.progress-bar');

    if (titleEl) titleEl.textContent = title || 'Kanban';
    if (badgeEl) badgeEl.textContent = msg('status-running') || 'In progress';
    if (metaEl) {
      metaEl.textContent = targetLabel + (subtitleText ? ' · ' + subtitleText : '');
    }

    list.insertBefore(li, list.firstChild);
    li.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    var pct = 5;
    var finished = false;
    var timer = setInterval(function () {
      if (finished) return;
      pct = Math.min(88, pct + Math.max(0.15, (88 - pct) * 0.022));
      if (barEl) {
        barEl.style.width = pct.toFixed(1) + '%';
        barEl.setAttribute('aria-valuenow', String(Math.round(pct)));
      }
    }, 600);

    return {
      setProgress: function (nextPct) {
        if (finished) return;
        var clamped = Math.max(pct, Math.min(88, Number(nextPct) || 0));
        pct = clamped;
        if (barEl) {
          barEl.style.width = pct.toFixed(1) + '%';
          barEl.setAttribute('aria-valuenow', String(Math.round(pct)));
        }
      },
      setDetail: function (detail) {
        if (metaEl) {
          metaEl.textContent = targetLabel + (detail ? ' · ' + detail : '');
        }
      },
      complete: function (boards) {
        if (finished) return;
        finished = true;
        clearInterval(timer);
        li.setAttribute('data-status', 'completed');
        if (badgeEl) {
          badgeEl.className = 'badge text-bg-success ms-1 kanban-import-job-status';
          badgeEl.textContent = msg('status-completed') || 'Completed';
        }
        if (barEl) {
          barEl.classList.remove('sp-job-bar-slow', 'progress-bar-striped', 'progress-bar-animated');
          barEl.classList.add('sp-job-bar-finish', 'bg-success');
          barEl.style.width = '100%';
          barEl.setAttribute('aria-valuenow', '100');
        }
        if (actionsEl && boards && boards.length === 1 && boards[0].url) {
          var link = document.createElement('a');
          link.href = boards[0].url;
          link.className = 'btn btn-sm btn-outline-secondary rounded-pill';
          link.textContent = msg('open') || 'Open';
          actionsEl.appendChild(link);
        }
      },
      fail: function (errMsg) {
        if (finished) return;
        finished = true;
        clearInterval(timer);
        li.setAttribute('data-status', 'failed');
        if (badgeEl) {
          badgeEl.className = 'badge text-bg-danger ms-1 kanban-import-job-status';
          badgeEl.textContent = msg('status-failed') || 'Failed';
        }
        if (barEl) {
          barEl.classList.remove('sp-job-bar-slow', 'progress-bar-striped', 'progress-bar-animated');
          barEl.classList.add('sp-job-bar-finish', 'bg-danger');
        }
        if (errMsg) {
          var errDiv = document.createElement('div');
          errDiv.className = 'small text-danger mt-1';
          errDiv.textContent = errMsg;
          var infoWrap = li.querySelector('.min-width-0');
          if (infoWrap) infoWrap.appendChild(errDiv);
        }
      },
    };
  }

  function addCloudJobToList(job) {
    var list = document.getElementById('cloudImportJobs');
    if (!list || !job) return;
    var empty = document.getElementById('cloudImportEmptyJobs');
    if (empty) empty.remove();
    var li = document.createElement('li');
    li.className = 'sp-job-row cloud-import-job';
    li.setAttribute('data-job-id', String(job.id));
    li.setAttribute('data-status', job.status || 'pending');
    li.innerHTML =
      '<div class="d-flex justify-content-between align-items-start gap-2">' +
      '<div><strong></strong> <span class="badge text-bg-secondary ms-1 cloud-import-job-status"></span>' +
      '<div class="small text-muted"><span class="cloud-import-job-space"></span> · <span class="cloud-import-job-progress-text">0/0</span></div></div>' +
      '<button type="button" class="btn btn-sm btn-outline-secondary rounded-pill cloud-import-cancel-job">' + msg('cancel') + '</button>' +
      '</div>' +
      '<div class="progress mt-2" style="height:6px"><div class="progress-bar cloud-import-job-bar" role="progressbar" style="width:0%"></div></div>';
    li.querySelector('strong').textContent = job.display_name || state.connectionName || '—';
    li.querySelector('.cloud-import-job-status').textContent = job.status || 'pending';
    li.querySelector('.cloud-import-job-space').textContent = job.target_space || '';
    bindCancelBtn(li.querySelector('.cloud-import-cancel-job'));
    list.insertBefore(li, list.firstChild);
    pollJob(li);
    li.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  var startBtn = document.getElementById('wizardStartBtn');
  if (startBtn) {
    startBtn.addEventListener('click', async function () {
      showStepError(4, '');
      if (isCloudSource()) {
        syncSpaceFromUi();
        if (!state.space) return;
        var destSel = document.getElementById('cloudImportDestFolder');
        var targetFolderId = destSel && destSel.value ? parseInt(destSel.value, 10) : null;
        var selected = Object.keys(state.selectedCloud).map(function (k) { return state.selectedCloud[k]; });
        startBtn.disabled = true;
        try {
          var res = await fetch(root.getAttribute('data-url-start-job'), {
            method: 'POST',
            headers: Object.assign({ 'Content-Type': 'application/json' }, csrfHeaders()),
            credentials: 'same-origin',
            body: JSON.stringify({
              connection_id: parseInt(state.connectionId, 10),
              selected: selected,
              target_space: state.space,
              team_id: state.teamId,
              target_folder_id: targetFolderId,
            }),
          });
          var data = await res.json().catch(function () { return {}; });
          if (!res.ok || !data.ok) {
            showStepError(4, data.error || 'Error');
            return;
          }
          toast(msg('cloud-started'), 'success');
          addCloudJobToList(data.job);
          state.selectedCloud = {};
          goToStep(1);
        } catch (_) {
          showStepError(4, 'Error');
        } finally {
          syncFooterButtons();
        }
        return;
      }

      if (state.source === 'kanban' && state.kanbanMode === 'trello') {
        var ids = state.selectedTrelloBoards.map(function (b) { return b.id; });
        var visSelect = document.getElementById('wizardKanbanTarget');
        var visVal = visSelect ? visSelect.value : 'private';
        var visLabel = visSelect && visSelect.selectedIndex >= 0 ? visSelect.options[visSelect.selectedIndex].text.trim() : visVal;
        var basePayload = { visibility: visVal.indexOf('team:') === 0 ? 'team' : visVal };
        if (visVal.indexOf('team:') === 0) basePayload.team_id = visVal.slice(5);
        startBtn.disabled = true;
        toast(msg('saving'), 'saving');

        var trelloJobTitle = state.selectedTrelloBoards.length === 1
          ? state.selectedTrelloBoards[0].name
          : msg('src-kanban-trello');
        var trelloJobSubtitle = state.selectedTrelloBoards.length > 1
          ? msg('boards-count').replace('{count}', String(state.selectedTrelloBoards.length))
          : msg('src-kanban-trello');
        var kanbanJob = createKanbanJobRow(trelloJobTitle, visLabel, trelloJobSubtitle);

        var importedBoards = [];
        var lastError = null;
        try {
          for (var bi = 0; bi < ids.length; bi++) {
            var payload = Object.assign({ board_ids: [ids[bi]] }, basePayload);
            var tres = await fetch(root.getAttribute('data-url-trello-import'), {
              method: 'POST',
              headers: Object.assign({ 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, csrfHeaders()),
              body: JSON.stringify(payload),
            });
            var tdata = await tres.json().catch(function () { return {}; });
            if (tres.ok && tdata.success && tdata.boards) {
              importedBoards = importedBoards.concat(tdata.boards);
              renderKanbanResults(importedBoards);
            } else {
              lastError = tdata.error || msg('failed');
            }
          }
          if (importedBoards.length) {
            kanbanJob.complete(importedBoards);
            toast(
              importedBoards.length === 1 ? msg('done-one') : msg('done-many').replace('{count}', String(importedBoards.length)),
              'success'
            );
          } else {
            kanbanJob.fail(lastError || msg('failed'));
            showStepError(4, lastError || msg('failed'));
          }
        } catch (_) {
          if (importedBoards.length) {
            kanbanJob.complete(importedBoards);
            renderKanbanResults(importedBoards);
          } else {
            kanbanJob.fail(msg('failed'));
            showStepError(4, msg('failed'));
          }
        } finally {
          syncFooterButtons();
        }
        return;
      }

      if (state.source === 'kanban' && state.kanbanMode === 'file') {
        if (!state.selectedFile) return;
        var fd = new FormData();
        fd.append('file', state.selectedFile);
        var fVisEl = document.getElementById('wizardKanbanTarget');
        var fVis = (fVisEl && fVisEl.value) || 'private';
        var fVisLabel = fVisEl && fVisEl.selectedIndex >= 0 ? fVisEl.options[fVisEl.selectedIndex].text.trim() : fVis;
        if (fVis.indexOf('team:') === 0) {
          fd.append('visibility', 'team');
          fd.append('team_id', fVis.slice(5));
        } else {
          fd.append('visibility', fVis);
        }
        var progressWrap = document.getElementById('settingsKanbanProgress');
        var progressLabel = document.getElementById('settingsKanbanProgressLabel');
        var progressPct = document.getElementById('settingsKanbanProgressPct');
        var progressTrack = document.getElementById('settingsKanbanProgressTrack');
        var progressBar = document.getElementById('settingsKanbanProgressBar');

        function setProg(pct, text) {
          var p = Math.max(0, Math.min(100, Math.round(pct)));
          if (progressWrap) progressWrap.hidden = false;
          if (progressBar) progressBar.style.width = p + '%';
          if (progressTrack) progressTrack.setAttribute('aria-valuenow', String(p));
          if (progressPct) progressPct.textContent = p + '%';
          if (progressLabel && text) progressLabel.textContent = text;
        }

        startBtn.disabled = true;
        setProg(0, msg('uploading'));
        toast(msg('saving'), 'saving');
        var fileJob = createKanbanJobRow(state.selectedFile.name, fVisLabel, msg('src-kanban-file'));

        var xhr = new XMLHttpRequest();
        xhr.open('POST', root.getAttribute('data-url-kanban-import'), true);
        xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
        var csrfMeta = document.querySelector('meta[name="csrf-token"]');
        if (csrfMeta && csrfMeta.content) xhr.setRequestHeader('X-CSRFToken', csrfMeta.content);

        xhr.upload.addEventListener('progress', function (ev) {
          if (ev.lengthComputable && ev.total > 0) {
            var pct = (ev.loaded / ev.total) * 100;
            setProg(pct, pct >= 100 ? msg('processing') : msg('uploading'));
            fileJob.setProgress(Math.min(40, (ev.loaded / ev.total) * 40));
          }
        });
        xhr.upload.addEventListener('load', function () {
          setProg(100, msg('processing'));
          fileJob.setProgress(40);
        });
        xhr.addEventListener('load', function () {
          if (progressWrap) progressWrap.hidden = true;
          syncFooterButtons();
          var data = {};
          try { data = JSON.parse(xhr.responseText || '{}'); } catch (_) {}
          if (xhr.status >= 200 && xhr.status < 300 && data.success) {
            var boards = data.boards || (data.board ? [data.board] : []);
            fileJob.complete(boards);
            renderKanbanResults(boards);
            toast(
              boards.length === 1 ? msg('done-one') : msg('done-many').replace('{count}', String(boards.length)),
              'success'
            );
          } else {
            fileJob.fail(data.error || msg('failed'));
            showStepError(4, data.error || msg('failed'));
          }
        });
        xhr.addEventListener('error', function () {
          if (progressWrap) progressWrap.hidden = true;
          syncFooterButtons();
          fileJob.fail(msg('failed'));
          showStepError(4, msg('failed'));
        });
        xhr.send(fd);
      }
    });
  }

  // ── Cloud Job Polling ───────────────────────────────────────────────────
  function pollJob(li) {
    var id = li.getAttribute('data-job-id');
    var status = li.getAttribute('data-status');
    var jobBase = root.getAttribute('data-job-base');
    if (!id || !jobBase || ['completed', 'failed', 'cancelled'].indexOf(status) >= 0) return;
    fetch(replaceId(jobBase, id), {
      headers: csrfHeaders(),
      credentials: 'same-origin',
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.ok || !data.job) return;
        var job = data.job;
        li.setAttribute('data-status', job.status);
        var badge = li.querySelector('.cloud-import-job-status');
        if (badge) badge.textContent = job.status;
        var prog = li.querySelector('.cloud-import-job-progress-text');
        if (prog) prog.textContent = job.files_done + '/' + job.files_total;
        var bar = li.querySelector('.cloud-import-job-bar');
        if (bar) bar.style.width = (job.progress || 0) + '%';
        var err = li.querySelector('.cloud-import-job-error');
        if (job.error_message) {
          if (!err) {
            err = document.createElement('div');
            err.className = 'small text-danger cloud-import-job-error';
            var wrap = li.querySelector('div > div');
            if (wrap) wrap.appendChild(err);
          }
          err.textContent = job.error_message;
        }
        if (['pending', 'running', 'cancelling'].indexOf(job.status) >= 0) {
          setTimeout(function () { pollJob(li); }, 2000);
        } else {
          var cancelBtn = li.querySelector('.cloud-import-cancel-job');
          if (cancelBtn) cancelBtn.remove();
        }
      })
      .catch(function () {
        setTimeout(function () { pollJob(li); }, 4000);
      });
  }

  function bindCancelBtn(btn) {
    if (!btn) return;
    btn.addEventListener('click', function () {
      var li = btn.closest('.cloud-import-job');
      if (!li) return;
      var id = li.getAttribute('data-job-id');
      fetch(replaceId(root.getAttribute('data-cancel-base'), id), {
        method: 'POST',
        headers: csrfHeaders(),
        credentials: 'same-origin',
      }).then(function () { pollJob(li); });
    });
  }

  root.querySelectorAll('.cloud-import-job').forEach(function (li) {
    var st = li.getAttribute('data-status');
    if (['pending', 'running', 'cancelling'].indexOf(st) >= 0) pollJob(li);
    bindCancelBtn(li.querySelector('.cloud-import-cancel-job'));
  });

  // ── Init & Deep-link (?source=google_drive|nextcloud|kanban) ───────────
  var initSrc = root.getAttribute('data-initial-source');
  if (initSrc === 'google_drive' || initSrc === 'nextcloud' || initSrc === 'kanban') {
    var card = root.querySelector('.sp-import-source-card[data-source-choice="' + initSrc + '"]');
    if (card) {
      card.click();
      // If returning from Google OAuth and a connection exists, jump directly to Step 3!
      if (initSrc === 'google_drive' && state.connectionId) {
        goToStep(3);
      }
    }
  } else {
    renderStepPanels();
  }
})();
