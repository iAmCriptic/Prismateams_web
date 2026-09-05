(function () {
  'use strict';

  var root = document.getElementById('cloudImportRoot');
  if (!root) return;

  var state = {
    connectionId: null,
    path: '',
    pathStack: [],
    selected: {},
    space: null,
    teamId: null,
  };

  function csrfHeaders() {
    var token = document.querySelector('meta[name="csrf-token"]');
    var h = { Accept: 'application/json' };
    if (token && token.content) h['X-CSRFToken'] = token.content;
    return h;
  }

  function replaceId(url, id) {
    return url.replace(/\/0(\/|$)/, '/' + id + '$1');
  }

  function showError(msg) {
    var el = document.getElementById('cloudImportError');
    if (!el) return;
    if (!msg) {
      el.classList.add('d-none');
      el.textContent = '';
      return;
    }
    el.textContent = msg;
    el.classList.remove('d-none');
  }

  function formatSize(n) {
    n = Number(n) || 0;
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1024 * 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + ' MB';
    return (n / (1024 * 1024 * 1024)).toFixed(1) + ' GB';
  }

  function selectedSpaceBtn() {
    return root.querySelector('.cloud-import-space-btn.active');
  }

  function syncSpaceFromUi() {
    var btn = selectedSpaceBtn();
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
    if (!sel || !state.space) return;
    var url = root.getAttribute('data-url-dest-folders') +
      '?space=' + encodeURIComponent(state.space) +
      (state.teamId ? '&team_id=' + state.teamId : '');
    fetch(url, { headers: csrfHeaders(), credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.ok) return;
        var rootLabel = sel.options[0] ? sel.options[0].textContent : '';
        sel.innerHTML = '';
        var opt0 = document.createElement('option');
        opt0.value = data.root_id != null ? String(data.root_id) : '';
        opt0.textContent = rootLabel || 'Root';
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
    });
  });

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
            showError((res.j && res.j.error) || 'Error');
            return;
          }
          window.location.reload();
        })
        .catch(function () {
          connectNcBtn.disabled = false;
          showError('Error');
        });
    });
  }

  function selectConnection(id) {
    state.connectionId = id;
    state.path = '';
    state.pathStack = [];
    state.selected = {};
    var section = document.getElementById('cloudImportBrowseSection');
    if (section) section.classList.remove('d-none');
    root.querySelectorAll('.cloud-import-conn').forEach(function (li) {
      li.classList.toggle('active', String(li.getAttribute('data-connection-id')) === String(id));
    });
    browse('');
  }

  root.querySelectorAll('.cloud-import-select-conn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var li = btn.closest('.cloud-import-conn');
      if (!li) return;
      selectConnection(li.getAttribute('data-connection-id'));
    });
  });

  root.querySelectorAll('.cloud-import-delete-conn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var li = btn.closest('.cloud-import-conn');
      if (!li) return;
      var id = li.getAttribute('data-connection-id');
      if (!window.confirm('OK?')) return;
      fetch(replaceId(root.getAttribute('data-delete-base'), id), {
        method: 'DELETE',
        headers: csrfHeaders(),
        credentials: 'same-origin',
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.ok) window.location.reload();
          else showError(data.error || 'Error');
        });
    });
  });

  function browse(path) {
    if (!state.connectionId) return;
    showError('');
    var url = replaceId(root.getAttribute('data-browse-base'), state.connectionId) +
      '?path=' + encodeURIComponent(path || '');
    fetch(url, { headers: csrfHeaders(), credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.ok) {
          showError(data.error || 'Error');
          return;
        }
        state.path = data.path || '';
        var pathEl = document.getElementById('cloudImportBrowsePath');
        if (pathEl) pathEl.textContent = '/' + (state.path || '');
        var up = document.getElementById('cloudImportBrowseUp');
        if (up) up.disabled = !state.path;
        renderBrowse(data.entries || []);
        updateSelectionHint();
      })
      .catch(function () { showError('Error'); });
  }

  function renderBrowse(entries) {
    var tbody = document.getElementById('cloudImportBrowseBody');
    if (!tbody) return;
    tbody.innerHTML = '';
    entries.forEach(function (e) {
      var tr = document.createElement('tr');
      var checked = !!state.selected[e.id];
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
          state.selected[e.id] = {
            id: e.id,
            name: e.name,
            is_dir: !!e.is_dir,
            size: e.size || 0,
            path: e.path || e.id,
          };
        } else {
          delete state.selected[e.id];
        }
        updateSelectionHint();
      });
      tbody.appendChild(tr);
    });
  }

  function updateSelectionHint() {
    var n = Object.keys(state.selected).length;
    var hint = document.getElementById('cloudImportSelectionHint');
    var start = document.getElementById('cloudImportStartBtn');
    if (hint) hint.textContent = n ? String(n) : '';
    if (start) start.disabled = n === 0 || !state.connectionId;
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

  var startBtn = document.getElementById('cloudImportStartBtn');
  if (startBtn) {
    startBtn.addEventListener('click', function () {
      syncSpaceFromUi();
      if (!state.space) {
        showError('space');
        return;
      }
      var destSel = document.getElementById('cloudImportDestFolder');
      var targetFolderId = destSel && destSel.value ? parseInt(destSel.value, 10) : null;
      var selected = Object.keys(state.selected).map(function (k) { return state.selected[k]; });
      startBtn.disabled = true;
      fetch(root.getAttribute('data-url-start-job'), {
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
      })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          startBtn.disabled = false;
          if (!res.ok || !res.j.ok) {
            showError((res.j && res.j.error) || 'Error');
            return;
          }
          window.location.reload();
        })
        .catch(function () {
          startBtn.disabled = false;
          showError('Error');
        });
    });
  }

  function pollJob(li) {
    var id = li.getAttribute('data-job-id');
    var status = li.getAttribute('data-status');
    if (!id || ['completed', 'failed', 'cancelled'].indexOf(status) >= 0) return;
    fetch(replaceId(root.getAttribute('data-job-base'), id), {
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
            li.querySelector('div') && li.querySelector('div').appendChild(err);
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

  root.querySelectorAll('.cloud-import-job').forEach(function (li) {
    var st = li.getAttribute('data-status');
    if (['pending', 'running', 'cancelling'].indexOf(st) >= 0) pollJob(li);
  });

  root.querySelectorAll('.cloud-import-cancel-job').forEach(function (btn) {
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
  });

  // init
  syncSpaceFromUi();
  loadDestFolders();
})();
