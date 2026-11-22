(function () {
  'use strict';

  function initSearchFilter() {
    var input = document.getElementById('modSearchInput');
    var clearBtn = document.getElementById('modSearchClear');
    var tableBody = document.getElementById('helpersTableBody');
    if (!input || !tableBody) return;

    function applyFilter() {
      var q = (input.value || '').trim().toLowerCase();
      if (clearBtn) {
        clearBtn.classList.toggle('d-none', q.length === 0);
      }
      var rows = tableBody.querySelectorAll('tr[data-search]');
      rows.forEach(function (row) {
        var hay = (row.getAttribute('data-search') || '').toLowerCase();
        row.classList.toggle('d-none', q.length > 0 && hay.indexOf(q) === -1);
      });
    }

    input.addEventListener('input', applyFilter);
    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        input.value = '';
        applyFilter();
        input.focus();
      });
    }
  }

  function initCopyButtons() {
    document.querySelectorAll('[data-copy-target], [data-copy-text]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var text = btn.getAttribute('data-copy-text') || '';
        if (!text) {
          var targetId = btn.getAttribute('data-copy-target');
          var el = targetId ? document.getElementById(targetId) : null;
          text = el ? (el.value || el.textContent || '') : '';
        }
        if (!text) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(function () {
            var copiedLabel = btn.getAttribute('data-i18n-copied') || 'Kopiert';
            var origHtml = btn.innerHTML;
            btn.textContent = copiedLabel;
            setTimeout(function () {
              btn.innerHTML = origHtml;
            }, 1500);
          });
        }
      });
    });
  }

  function initVoucherChecklist() {
    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    var csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

    document.querySelectorAll('.js-toggle-voucher').forEach(function (cb) {
      cb.addEventListener('change', function () {
        var url = cb.getAttribute('data-url');
        if (!url) return;
        fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrfToken
          },
          body: JSON.stringify({})
        })
          .then(function (resp) { return resp.json(); })
          .then(function (data) {
            if (!data || !data.ok) {
              cb.checked = !cb.checked;
            }
          })
          .catch(function () {
            cb.checked = !cb.checked;
          });
      });
    });
  }

  function initEditHelperModal() {
    var modalEl = document.getElementById('helpersEditHelperModal');
    if (!modalEl) return;
    var form = modalEl.querySelector('form');
    document.querySelectorAll('.js-edit-helper-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var actionUrl = btn.getAttribute('data-action');
        if (form && actionUrl) form.setAttribute('action', actionUrl);

        var setVal = function (id, attr) {
          var el = modalEl.querySelector('#' + id);
          if (el) el.value = btn.getAttribute(attr) || '';
        };
        setVal('editHelperFirstName', 'data-first-name');
        setVal('editHelperLastName', 'data-last-name');
        setVal('editHelperEmail', 'data-email');
        setVal('editHelperPhone', 'data-phone');
        setVal('editHelperTshirt', 'data-tshirt');
        setVal('editHelperAllergies', 'data-allergies');
        setVal('editHelperStatus', 'data-status');

        var customRaw = btn.getAttribute('data-custom') || '{}';
        var customObj = {};
        try {
          customObj = JSON.parse(customRaw);
        } catch (e) {
          customObj = {};
        }

        var wishAreas = [];
        try { wishAreas = JSON.parse(btn.getAttribute('data-wish-areas') || '[]'); } catch (e) { wishAreas = []; }
        modalEl.querySelectorAll('.js-edit-wish-area').forEach(function (cb) {
          cb.checked = wishAreas.indexOf(parseInt(cb.value, 10)) !== -1;
        });

        var wishDays = [];
        try { wishDays = JSON.parse(btn.getAttribute('data-wish-days') || '[]'); } catch (e) { wishDays = []; }
        modalEl.querySelectorAll('.js-edit-wish-day').forEach(function (cb) {
          cb.checked = wishDays.indexOf(cb.value) !== -1;
        });

        modalEl.querySelectorAll('[data-custom-key]').forEach(function (inputEl) {
          var key = inputEl.getAttribute('data-custom-key');
          var val = customObj[key];
          if (inputEl.type === 'checkbox') {
            inputEl.checked = Boolean(val);
          } else if (inputEl.tagName === 'SELECT' && inputEl.multiple) {
            var arr = Array.isArray(val) ? val : [];
            Array.from(inputEl.options).forEach(function (opt) {
              opt.selected = arr.indexOf(opt.value) !== -1;
            });
          } else {
            inputEl.value = val != null ? String(val) : '';
          }
        });
      });
    });
  }

  function initEditShiftModal() {
    var modalEl = document.getElementById('helpersEditShiftModal');
    if (!modalEl) return;
    var form = modalEl.querySelector('form');
    document.querySelectorAll('.js-edit-shift-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var actionUrl = btn.getAttribute('data-action');
        if (form && actionUrl) form.setAttribute('action', actionUrl);

        var setVal = function (id, attr) {
          var el = modalEl.querySelector('#' + id);
          if (el) el.value = btn.getAttribute(attr) || '';
        };
        setVal('editShiftHelper', 'data-helper-id');
        setVal('editShiftGroupCount', 'data-group-count');
        setVal('editShiftRole', 'data-role');
        setVal('editShiftDay', 'data-day');
        setVal('editShiftDate', 'data-date');
        setVal('editShiftStart', 'data-start');
        setVal('editShiftEnd', 'data-end');
        setVal('editShiftHours', 'data-hours');
        setVal('editShiftFoodOverride', 'data-food-override');
        setVal('editShiftDrinksOverride', 'data-drinks-override');
        setVal('editShiftNotes', 'data-notes');

        var headCb = modalEl.querySelector('#editShiftIsHead');
        if (headCb) headCb.checked = btn.getAttribute('data-is-head') === '1';
      });
    });
  }

  function parseTimeMinutes(raw) {
    var text = (raw || '').trim().replace('.', ':');
    var m = /^(\d{1,2}):(\d{2})$/.exec(text);
    if (!m) return null;
    var hh = parseInt(m[1], 10);
    var mm = parseInt(m[2], 10);
    if (hh === 24 && mm === 0) return 24 * 60;
    if (hh >= 0 && hh <= 23 && mm >= 0 && mm <= 59) return hh * 60 + mm;
    return null;
  }

  function bindAutoShiftHours(startId, endId, hoursId) {
    var startEl = document.getElementById(startId);
    var endEl = document.getElementById(endId);
    var hoursEl = document.getElementById(hoursId);
    if (!startEl || !endEl || !hoursEl) return;

    function recalc() {
      var sMin = parseTimeMinutes(startEl.value);
      var eMin = parseTimeMinutes(endEl.value);
      if (sMin === null || eMin === null) return;
      var diff = eMin - sMin;
      if (diff <= 0) diff += 24 * 60;
      hoursEl.value = Math.round((diff / 60) * 100) / 100;
    }

    startEl.addEventListener('input', recalc);
    startEl.addEventListener('change', recalc);
    endEl.addEventListener('input', recalc);
    endEl.addEventListener('change', recalc);
  }

  function initPlaceholderPills() {
    var pills = document.querySelectorAll('.js-placeholder-pill[data-placeholder]');
    var editors = Array.from(document.querySelectorAll('.helpers-token-editor[data-token-target]'));
    if (!editors.length) return;

    var tokenLabels = {};
    pills.forEach(function (pill) {
      var key = pill.getAttribute('data-placeholder-key') || '';
      var label = pill.getAttribute('data-placeholder-label') || pill.textContent.trim();
      if (key) tokenLabels[key] = label;
    });

    function createTokenChip(key, label) {
      var span = document.createElement('span');
      span.className = 'helpers-mail-token';
      span.setAttribute('contenteditable', 'false');
      span.setAttribute('data-token-key', key);
      span.textContent = label || tokenLabels[key] || key;
      return span;
    }

    function renderEditor(editor, rawText) {
      editor.innerHTML = '';
      var isSingle = editor.classList.contains('helpers-token-editor--single');
      var re = /\{\{\s*([a-zA-Z0-9_\-]+)\s*\}\}/g;
      var lastIndex = 0;
      var match;

      function appendTextWithBreaks(text) {
        if (!text) return;
        if (isSingle) {
          editor.appendChild(document.createTextNode(text.replace(/\r?\n/g, ' ')));
          return;
        }
        var lines = text.split(/\r?\n/);
        lines.forEach(function (line, idx) {
          if (idx > 0) editor.appendChild(document.createElement('br'));
          if (line) editor.appendChild(document.createTextNode(line));
        });
      }

      while ((match = re.exec(rawText)) !== null) {
        appendTextWithBreaks(rawText.slice(lastIndex, match.index));
        var key = match[1].trim();
        editor.appendChild(createTokenChip(key, tokenLabels[key] || key));
        lastIndex = re.lastIndex;
      }
      appendTextWithBreaks(rawText.slice(lastIndex));
    }

    function serializeEditor(editor) {
      var isSingle = editor.classList.contains('helpers-token-editor--single');
      var parts = [];

      function walk(node, isBlockChild) {
        if (node.nodeType === Node.TEXT_NODE) {
          parts.push(node.nodeValue.replace(/\u00a0/g, ' '));
          return;
        }
        if (node.nodeType !== Node.ELEMENT_NODE) return;

        var tokenKey = node.getAttribute('data-token-key');
        if (tokenKey) {
          parts.push('{{ ' + tokenKey + ' }}');
          return;
        }
        if (node.tagName === 'BR') {
          if (!isSingle) parts.push('\n');
          return;
        }
        var isBlock = node.tagName === 'DIV' || node.tagName === 'P';
        if (isBlock && !isSingle && isBlockChild && parts.length > 0 && !parts[parts.length - 1].endsWith('\n')) {
          parts.push('\n');
        }
        Array.from(node.childNodes).forEach(function (child) {
          walk(child, true);
        });
      }

      Array.from(editor.childNodes).forEach(function (child) {
        walk(child, true);
      });
      var result = parts.join('');
      return isSingle ? result.replace(/\r?\n/g, ' ').trim() : result;
    }

    function syncEditor(editor) {
      var targetId = editor.getAttribute('data-token-target');
      var target = targetId ? document.getElementById(targetId) : null;
      if (target) target.value = serializeEditor(editor);
    }

    var lastFocused = document.getElementById('spHelperMailBodyEditor') || editors[0];
    var savedRange = null;

    function saveSelection(editor) {
      var sel = window.getSelection();
      if (sel && sel.rangeCount > 0 && editor.contains(sel.anchorNode)) {
        savedRange = sel.getRangeAt(0).cloneRange();
      }
    }

    function insertChipAtCursor(editor, key, label) {
      if (!editor) return;
      editor.focus();
      var chip = createTokenChip(key, label);
      var sel = window.getSelection();
      var range = null;
      if (savedRange && editor.contains(savedRange.startContainer)) {
        range = savedRange;
      } else if (sel && sel.rangeCount > 0 && editor.contains(sel.anchorNode)) {
        range = sel.getRangeAt(0);
      }

      if (range) {
        range.deleteContents();
        range.insertNode(chip);
        range.setStartAfter(chip);
        range.collapse(true);
        if (sel) {
          sel.removeAllRanges();
          sel.addRange(range);
        }
      } else {
        editor.appendChild(chip);
      }
      saveSelection(editor);
      syncEditor(editor);
    }

    editors.forEach(function (editor) {
      var targetId = editor.getAttribute('data-token-target');
      var target = targetId ? document.getElementById(targetId) : null;
      if (target) {
        renderEditor(editor, target.value || '');
      }

      editor.addEventListener('focus', function () {
        lastFocused = editor;
      });
      editor.addEventListener('keyup', function () {
        saveSelection(editor);
        syncEditor(editor);
      });
      editor.addEventListener('mouseup', function () {
        saveSelection(editor);
      });
      editor.addEventListener('input', function () {
        syncEditor(editor);
      });
      editor.addEventListener('blur', function () {
        syncEditor(editor);
      });
      if (editor.classList.contains('helpers-token-editor--single')) {
        editor.addEventListener('keydown', function (e) {
          if (e.key === 'Enter') e.preventDefault();
        });
      }
      editor.addEventListener('dragover', function (e) {
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
      });
      editor.addEventListener('drop', function (e) {
        var key = e.dataTransfer ? e.dataTransfer.getData('text/x-helper-token-key') : '';
        var label = e.dataTransfer ? e.dataTransfer.getData('text/x-helper-token-label') : '';
        if (!key) return;
        e.preventDefault();
        lastFocused = editor;
        insertChipAtCursor(editor, key, label);
      });
    });

    document.querySelectorAll('.js-helper-mail-form').forEach(function (form) {
      form.addEventListener('submit', function () {
        editors.forEach(syncEditor);
      });
    });

    pills.forEach(function (pill) {
      pill.addEventListener('dragstart', function (e) {
        var key = pill.getAttribute('data-placeholder-key') || '';
        var label = pill.getAttribute('data-placeholder-label') || pill.textContent.trim();
        if (e.dataTransfer) {
          e.dataTransfer.setData('text/x-helper-token-key', key);
          e.dataTransfer.setData('text/x-helper-token-label', label);
          e.dataTransfer.setData('text/plain', label);
          e.dataTransfer.effectAllowed = 'copy';
        }
      });
      pill.addEventListener('click', function () {
        var key = pill.getAttribute('data-placeholder-key') || '';
        var label = pill.getAttribute('data-placeholder-label') || pill.textContent.trim();
        if (key) insertChipAtCursor(lastFocused, key, label);
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initSearchFilter();
    initCopyButtons();
    initVoucherChecklist();
    initEditHelperModal();
    initEditShiftModal();
    bindAutoShiftHours('addShiftStart', 'addShiftEnd', 'addShiftHours');
    bindAutoShiftHours('editShiftStart', 'editShiftEnd', 'editShiftHours');
    initPlaceholderPills();
  });
})();
