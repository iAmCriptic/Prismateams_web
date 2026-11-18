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
    document.querySelectorAll('[data-copy-target]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var targetId = btn.getAttribute('data-copy-target');
        var el = document.getElementById(targetId);
        if (!el) return;
        var text = el.value || el.textContent || '';
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

  document.addEventListener('DOMContentLoaded', function () {
    initSearchFilter();
    initCopyButtons();
    initVoucherChecklist();
    initEditHelperModal();
    initEditShiftModal();
    bindAutoShiftHours('addShiftStart', 'addShiftEnd', 'addShiftHours');
    bindAutoShiftHours('editShiftStart', 'editShiftEnd', 'editShiftHours');
  });
})();
