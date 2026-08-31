(function () {
  'use strict';

  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }

  function qsa(sel, root) {
    return Array.from((root || document).querySelectorAll(sel));
  }

  function csrfToken() {
    const meta = qs('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    const input = qs('input[name="csrf_token"]');
    return input ? input.value : '';
  }

  function formatBytes(bytes) {
    const n = Number(bytes) || 0;
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / (1024 * 1024)).toFixed(1) + ' MB';
  }

  function categoryLabel(app, cat) {
    return app.dataset['i18nCategory' + cat.charAt(0).toUpperCase() + cat.slice(1)] || cat;
  }

  function optionIcon(opt) {
    if (opt.group === 'size' || opt.kind === 'resize' || opt.kind === 'page_size') {
      return 'bi-aspect-ratio';
    }
    const fmt = (opt.target_format || '').toLowerCase();
    if (['mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a', 'opus'].indexOf(fmt) >= 0) return 'bi-music-note-beamed';
    if (['jpeg', 'png', 'webp', 'bmp', 'tiff', 'gif'].indexOf(fmt) >= 0) return 'bi-image';
    if (fmt === 'pdf') return 'bi-file-earmark-pdf';
    return 'bi-file-earmark';
  }

  function initFileConverter() {
    const app = qs('#fileConverterApp');
    if (!app) return;

    const state = {
      uploadToken: null,
      sourceFilename: null,
      sourceFormat: null,
      sourceCategory: null,
      options: [],
      selectedOptionId: null,
      pollTimers: {},
    };

    const stepUpload = qs('#fcStepUpload', app);
    const stepOptions = qs('#fcStepOptions', app);
    const dropzone = qs('#fcDropzone', app);
    const fileInput = qs('#fcFileInput', app);
    const uploadProgress = qs('#fcUploadProgress', app);
    const uploadProgressBar = qs('#fcUploadProgressBar', app);
    const uploadError = qs('#fcUploadError', app);
    const convertError = qs('#fcConvertError', app);
    const convertBtn = qs('#fcConvertBtn', app);
    const resetBtn = qs('#fcResetBtn', app);
    const metaName = qs('#fcMetaName', app);
    const metaInfo = qs('#fcMetaInfo', app);
    const optionsFormat = qs('#fcOptionsFormat', app);
    const optionsSize = qs('#fcOptionsSize', app);
    const paramPanel = qs('#fcParamPanel', app);
    const paramCustom = qs('#fcParamCustom', app);
    const paramPercent = qs('#fcParamPercent', app);
    const jobsBody = qs('#fcJobsBody', app);

    function showError(el, msg) {
      if (!el) return;
      if (msg) {
        el.textContent = msg;
        el.classList.remove('d-none');
      } else {
        el.textContent = '';
        el.classList.add('d-none');
      }
    }

    function setTab(tab) {
      qsa('.fc-nav-link', app).forEach(function (btn) {
        btn.classList.toggle('active', btn.getAttribute('data-fc-tab') === tab);
      });
      qsa('[data-fc-panel]', app).forEach(function (panel) {
        panel.classList.toggle('d-none', panel.getAttribute('data-fc-panel') !== tab);
      });
    }

    function updateJobsBadge(delta) {
      qsa('[data-fc-jobs-badge]', app).forEach(function (badge) {
        let count = parseInt(badge.getAttribute('data-count') || '0', 10) || 0;
        if (typeof delta === 'number') count = Math.max(0, count + delta);
        badge.setAttribute('data-count', String(count));
        badge.textContent = count > 0 ? String(count) : '';
      });
    }

    function resetWizard() {
      state.uploadToken = null;
      state.sourceFilename = null;
      state.sourceFormat = null;
      state.sourceCategory = null;
      state.options = [];
      state.selectedOptionId = null;
      if (fileInput) fileInput.value = '';
      showError(uploadError, null);
      showError(convertError, null);
      if (uploadProgress) uploadProgress.classList.add('d-none');
      if (uploadProgressBar) uploadProgressBar.style.width = '0%';
      if (stepUpload) stepUpload.classList.remove('d-none');
      if (stepOptions) stepOptions.classList.add('d-none');
      if (optionsFormat) optionsFormat.innerHTML = '';
      if (optionsSize) optionsSize.innerHTML = '';
      if (paramPanel) paramPanel.classList.add('d-none');
      if (convertBtn) convertBtn.disabled = true;
    }

    function selectOption(optionId) {
      state.selectedOptionId = optionId;
      qsa('.fc-option-btn', app).forEach(function (btn) {
        btn.classList.toggle('active', btn.getAttribute('data-option-id') === optionId);
      });

      const opt = state.options.find(function (o) { return o.id === optionId; });
      if (!opt) {
        if (convertBtn) convertBtn.disabled = true;
        if (paramPanel) paramPanel.classList.add('d-none');
        return;
      }

      if (convertBtn) convertBtn.disabled = false;
      const mode = (opt.params && opt.params.mode) || '';
      if (mode === 'custom' || mode === 'percent') {
        paramPanel.classList.remove('d-none');
        paramCustom.classList.toggle('d-none', mode !== 'custom');
        paramPercent.classList.toggle('d-none', mode !== 'percent');
      } else {
        paramPanel.classList.add('d-none');
      }
    }

    function renderOptions(options) {
      state.options = options || [];
      optionsFormat.innerHTML = '';
      optionsSize.innerHTML = '';

      const formatOpts = state.options.filter(function (o) { return o.group === 'format'; });
      const sizeOpts = state.options.filter(function (o) { return o.group === 'size'; });

      function renderGroup(container, list, title) {
        if (!list.length) return;
        const titleEl = document.createElement('div');
        titleEl.className = 'fc-group-title';
        titleEl.textContent = title;
        container.appendChild(titleEl);
        const grid = document.createElement('div');
        grid.className = 'fc-option-grid';
        list.forEach(function (opt) {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'fc-option-btn';
          btn.setAttribute('data-option-id', opt.id);
          btn.innerHTML = '<i class="bi ' + optionIcon(opt) + '" aria-hidden="true"></i><span></span>';
          btn.querySelector('span').textContent = opt.label || opt.target_format;
          btn.addEventListener('click', function () { selectOption(opt.id); });
          grid.appendChild(btn);
        });
        container.appendChild(grid);
      }

      renderGroup(optionsFormat, formatOpts, app.dataset.i18nGroupFormat || 'Format');
      renderGroup(optionsSize, sizeOpts, app.dataset.i18nGroupSize || 'Size');
    }

    function showOptionsStep(data) {
      state.uploadToken = data.upload_token;
      state.sourceFilename = data.source_filename;
      state.sourceFormat = data.source_format;
      state.sourceCategory = data.source_category;
      metaName.textContent = data.source_filename;
      metaInfo.textContent =
        categoryLabel(app, data.source_category) +
        ' · ' +
        String(data.source_format || '').toUpperCase() +
        ' · ' +
        formatBytes(data.file_size);
      renderOptions(data.options || []);
      stepUpload.classList.add('d-none');
      stepOptions.classList.remove('d-none');
      convertBtn.disabled = true;
      showError(convertError, null);
    }

    function uploadFile(file) {
      if (!file) return;
      const maxSize = parseInt(app.dataset.maxFileSize || '0', 10) || 0;
      if (maxSize > 0 && file.size > maxSize) {
        showError(uploadError, app.dataset.i18nFileTooLarge || 'File too large');
        return;
      }

      showError(uploadError, null);
      uploadProgress.classList.remove('d-none');
      uploadProgressBar.style.width = '10%';
      qs('#fcDropzoneTitle', app).textContent = app.dataset.i18nUploading || 'Uploading…';

      const form = new FormData();
      form.append('file', file);

      const xhr = new XMLHttpRequest();
      xhr.open('POST', app.dataset.uploadUrl);
      const token = csrfToken();
      if (token) xhr.setRequestHeader('X-CSRFToken', token);

      xhr.upload.addEventListener('progress', function (e) {
        if (e.lengthComputable) {
          const pct = Math.max(5, Math.round((e.loaded / e.total) * 100));
          uploadProgressBar.style.width = pct + '%';
        }
      });

      xhr.onload = function () {
        uploadProgressBar.style.width = '100%';
        let data = {};
        try { data = JSON.parse(xhr.responseText || '{}'); } catch (err) { data = {}; }
        if (xhr.status >= 200 && xhr.status < 300) {
          showOptionsStep(data);
        } else {
          showError(uploadError, data.error || (app.dataset.i18nUploadHint || 'Upload failed'));
          qs('#fcDropzoneTitle', app).textContent = app.dataset.i18nUploadTitle || 'Upload';
        }
        setTimeout(function () { uploadProgress.classList.add('d-none'); }, 400);
      };

      xhr.onerror = function () {
        showError(uploadError, app.dataset.i18nUploadHint || 'Upload failed');
        uploadProgress.classList.add('d-none');
      };

      xhr.send(form);
    }

    function collectParams(opt) {
      const params = {};
      const mode = (opt.params && opt.params.mode) || '';
      if (mode === 'custom') {
        params.mode = 'custom';
        params.width = parseInt(qs('#fcWidth', app).value || '0', 10) || 0;
        params.height = parseInt(qs('#fcHeight', app).value || '0', 10) || 0;
        params.keep_aspect = qs('#fcKeepAspect', app).checked;
      } else if (mode === 'percent') {
        params.mode = 'percent';
        params.percent = parseFloat(qs('#fcPercent', app).value || '100') || 100;
      }
      return params;
    }

    function statusUrl(jobId) {
      return (app.dataset.statusUrlTemplate || '').replace('/0', '/' + jobId);
    }
    function downloadUrl(jobId) {
      return (app.dataset.downloadUrlTemplate || '').replace('/0', '/' + jobId);
    }
    function deleteUrl(jobId) {
      return (app.dataset.deleteUrlTemplate || '').replace('/0', '/' + jobId);
    }

    function statusBadgeHtml(status, errorMessage) {
      if (status === 'completed') {
        return '<span class="badge rounded-pill bg-success">' + (app.dataset.i18nStatusCompleted || 'Done') + '</span>';
      }
      if (status === 'failed') {
        let html = '<span class="badge rounded-pill bg-danger">' + (app.dataset.i18nStatusFailed || 'Failed') + '</span>';
        if (errorMessage) {
          html += '<div class="small text-danger mt-1 job-error"></div>';
        }
        return html;
      }
      if (status === 'processing' || status === 'pending') {
        return (
          '<div class="progress fc-job-progress">' +
          '<div class="progress-bar progress-bar-striped progress-bar-animated bg-primary" style="width:60%">' +
          (app.dataset.i18nStatusProcessing || '…') +
          '</div></div>'
        );
      }
      return '<span class="badge rounded-pill bg-secondary">' + (app.dataset.i18nStatusPending || 'Pending') + '</span>';
    }

    function categoryIcon(cat) {
      if (cat === 'audio') return 'bi-music-note-beamed';
      if (cat === 'image') return 'bi-image';
      if (cat === 'pdf') return 'bi-file-earmark-pdf';
      return 'bi-file-earmark-text';
    }

    function upsertJobRow(job) {
      const empty = qs('.fc-empty-row', jobsBody);
      if (empty) empty.remove();

      let row = qs('tr.fc-job[data-job-id="' + job.id + '"]', jobsBody);
      const isNew = !row;
      if (!row) {
        row = document.createElement('tr');
        row.className = 'mod-list-row fc-job';
        row.setAttribute('data-job-id', String(job.id));
        jobsBody.insertBefore(row, jobsBody.firstChild);
        updateJobsBadge(1);
      }
      row.setAttribute('data-status', job.status);

      const downloadBtn = job.downloadable
        ? '<a class="btn btn-sm btn-link" href="' + downloadUrl(job.id) + '" title="' + (app.dataset.i18nDownload || 'Download') + '"><i class="bi bi-download"></i></a>'
        : '';

      row.innerHTML =
        '<td><div class="d-flex align-items-center gap-2 min-width-0">' +
        '<span class="fc-job-icon flex-shrink-0"><i class="bi ' + categoryIcon(job.source_category) + '"></i></span>' +
        '<div class="min-width-0"><span class="mod-list-name text-truncate d-inline-block" style="max-width:280px"></span>' +
        '<div class="small text-muted">→ ' + String(job.target_format || '').toUpperCase() + '</div></div></div></td>' +
        '<td class="d-none d-sm-table-cell"></td>' +
        '<td class="job-status-cell">' + statusBadgeHtml(job.status, job.error_message) + '</td>' +
        '<td class="d-none d-md-table-cell">–</td>' +
        '<td class="text-end"><div class="mod-list-actions"><div class="mod-list-hover-actions">' + downloadBtn + '</div>' +
        '<div class="dropdown d-inline-block"><button class="btn btn-sm btn-link" type="button" data-bs-toggle="dropdown"><i class="bi bi-three-dots-vertical"></i></button>' +
        '<ul class="dropdown-menu dropdown-menu-end fc-pill-dropdown"><li><button type="button" class="dropdown-item text-danger fc-job-delete-btn" data-job-id="' + job.id + '"><i class="bi bi-trash me-2"></i>' + (app.dataset.i18nDelete || 'Delete') + '</button></li></ul></div></div></td>';

      row.querySelector('.mod-list-name').textContent = job.source_filename || '';
      row.children[1].textContent = categoryLabel(app, job.source_category || '');
      const errEl = row.querySelector('.job-error');
      if (errEl && job.error_message) errEl.textContent = job.error_message;

      if (job.status === 'completed' || job.status === 'failed') {
        if (isNew || row.getAttribute('data-was-active') === '1') {
          updateJobsBadge(-1);
          row.removeAttribute('data-was-active');
        }
      } else {
        row.setAttribute('data-was-active', '1');
      }

      return row;
    }

    function pollJob(jobId) {
      if (state.pollTimers[jobId]) return;
      const tick = function () {
        fetch(statusUrl(jobId), { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (job) {
            upsertJobRow(job);
            if (job.status === 'completed' || job.status === 'failed') {
              clearInterval(state.pollTimers[jobId]);
              delete state.pollTimers[jobId];
            }
          })
          .catch(function () { /* ignore transient */ });
      };
      state.pollTimers[jobId] = setInterval(tick, 1500);
      tick();
    }

    function startConvert() {
      if (!state.selectedOptionId || !state.uploadToken) return;
      const opt = state.options.find(function (o) { return o.id === state.selectedOptionId; });
      if (!opt) return;

      showError(convertError, null);
      convertBtn.disabled = true;

      const payload = {
        upload_token: state.uploadToken,
        option_id: state.selectedOptionId,
        source_category: state.sourceCategory,
        source_format: state.sourceFormat,
        source_filename: state.sourceFilename,
        params: collectParams(opt),
      };

      fetch(app.dataset.convertUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-CSRFToken': csrfToken(),
        },
        body: JSON.stringify(payload),
      })
        .then(function (r) {
          return r.json().then(function (data) {
            return { ok: r.ok, status: r.status, data: data };
          });
        })
        .then(function (res) {
          if (!res.ok) {
            showError(convertError, res.data.error || 'Error');
            convertBtn.disabled = false;
            return;
          }
          upsertJobRow(res.data);
          pollJob(res.data.id);
          resetWizard();
          setTab('jobs');
        })
        .catch(function () {
          showError(convertError, 'Error');
          convertBtn.disabled = false;
        });
    }

    function portalConfirm(message, options) {
      if (typeof window.ptConfirm === 'function') {
        return window.ptConfirm(String(message || ''), options || {});
      }
      return Promise.resolve(window.confirm(String(message || '')));
    }

    function deleteJob(jobId) {
      portalConfirm(app.dataset.i18nDeleteConfirm || 'Delete?', {
        danger: true,
        confirmLabel: app.dataset.i18nDelete || undefined,
      }).then(function (ok) {
        if (!ok) return;
        fetch(deleteUrl(jobId), {
          method: 'DELETE',
          credentials: 'same-origin',
          headers: { Accept: 'application/json', 'X-CSRFToken': csrfToken() },
        })
          .then(function (r) {
            if (!r.ok) return;
            const row = qs('tr.fc-job[data-job-id="' + jobId + '"]', jobsBody);
            if (row) {
              if (row.getAttribute('data-was-active') === '1' || row.getAttribute('data-status') === 'processing' || row.getAttribute('data-status') === 'pending') {
                updateJobsBadge(-1);
              }
              row.remove();
            }
            if (state.pollTimers[jobId]) {
              clearInterval(state.pollTimers[jobId]);
              delete state.pollTimers[jobId];
            }
            if (!qs('tr.fc-job', jobsBody)) {
              jobsBody.innerHTML = '<tr class="fc-empty-row"><td colspan="5" class="text-muted text-center py-4">–</td></tr>';
            }
          });
      });
    }

    // Events
    qsa('.fc-nav-link', app).forEach(function (btn) {
      btn.addEventListener('click', function () {
        setTab(btn.getAttribute('data-fc-tab'));
        if (btn.getAttribute('data-fc-dismiss-offcanvas')) {
          const oc = qs('#fcMobileNav');
          if (oc && window.bootstrap && bootstrap.Offcanvas) {
            const inst = bootstrap.Offcanvas.getInstance(oc);
            if (inst) inst.hide();
          }
        }
      });
    });

    if (dropzone && fileInput) {
      dropzone.addEventListener('click', function () { fileInput.click(); });
      dropzone.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          fileInput.click();
        }
      });
      fileInput.addEventListener('change', function () {
        if (fileInput.files && fileInput.files[0]) uploadFile(fileInput.files[0]);
      });
      ['dragenter', 'dragover'].forEach(function (ev) {
        dropzone.addEventListener(ev, function (e) {
          e.preventDefault();
          e.stopPropagation();
          dropzone.classList.add('fc-dragover');
        });
      });
      ['dragleave', 'drop'].forEach(function (ev) {
        dropzone.addEventListener(ev, function (e) {
          e.preventDefault();
          e.stopPropagation();
          dropzone.classList.remove('fc-dragover');
        });
      });
      dropzone.addEventListener('drop', function (e) {
        const files = e.dataTransfer && e.dataTransfer.files;
        if (files && files[0]) uploadFile(files[0]);
      });
    }

    if (resetBtn) resetBtn.addEventListener('click', resetWizard);
    if (convertBtn) convertBtn.addEventListener('click', startConvert);

    app.addEventListener('click', function (e) {
      const del = e.target.closest('.fc-job-delete-btn');
      if (del) {
        e.preventDefault();
        deleteJob(del.getAttribute('data-job-id'));
      }
    });

    qsa('.fc-clear-all-btn', app).forEach(function (btn) {
      btn.addEventListener('click', function () {
        portalConfirm(app.dataset.i18nClearConfirm || 'Clear?', {
          danger: true,
          confirmLabel: app.dataset.i18nDelete || undefined,
        }).then(function (ok) {
          if (!ok) return;
          qsa('.fc-clear-all-btn', app).forEach(function (b) { b.disabled = true; });
          fetch(app.dataset.clearAllUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { Accept: 'application/json', 'X-CSRFToken': csrfToken() },
          }).then(function (r) {
            if (r.ok) {
              window.location.reload();
              return;
            }
            qsa('.fc-clear-all-btn', app).forEach(function (b) { b.disabled = false; });
          }).catch(function () {
            qsa('.fc-clear-all-btn', app).forEach(function (b) { b.disabled = false; });
          });
        });
      });
    });

    // Resume polling for active jobs
    qsa('tr.fc-job', jobsBody).forEach(function (row) {
      const status = row.getAttribute('data-status');
      const id = row.getAttribute('data-job-id');
      if ((status === 'pending' || status === 'processing') && id) {
        row.setAttribute('data-was-active', '1');
        pollJob(id);
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initFileConverter);
  } else {
    initFileConverter();
  }
})();
