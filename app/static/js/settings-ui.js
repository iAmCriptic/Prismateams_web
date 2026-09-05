/**
 * Settings Premium UI — toast, autosave, search flash, collapse, tooltips.
 */
(function (window, document) {
  'use strict';

  var DEBOUNCE_MS = 500;
  var TOAST_MS = 2600;
  var FLASH_CLASS = 'sp-search-flash';
  var activeFlashEl = null;
  var toastHost = null;
  var toastEl = null;
  var toastTimer = null;
  var i18n = (window.SETTINGS_UI_I18N) || {};

  function t(key, fallback) {
    return i18n[key] || fallback || key;
  }

  function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  /* ——— Toast ——— */
  function ensureToastHost() {
    if (toastHost) return toastHost;
    toastHost = document.getElementById('spToastHost');
    if (!toastHost) {
      toastHost = document.createElement('div');
      toastHost.id = 'spToastHost';
      toastHost.className = 'sp-toast-host';
      toastHost.setAttribute('aria-live', 'polite');
      document.body.appendChild(toastHost);
    }
    return toastHost;
  }

  function showToast(message, state) {
    state = state || 'success';
    var host = ensureToastHost();
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'sp-toast';
      toastEl.setAttribute('role', 'status');
      toastEl.innerHTML =
        '<span class="sp-toast-icon" aria-hidden="true"><i class="bi"></i></span>' +
        '<span class="sp-toast-msg"></span>' +
        '<button type="button" class="sp-toast-close" aria-label="' + t('close', 'Schließen') + '"><i class="bi bi-x-lg"></i></button>';
      toastEl.querySelector('.sp-toast-close').addEventListener('click', hideToast);
      host.appendChild(toastEl);
    }
    toastEl.classList.remove('sp-toast--saving', 'sp-toast--success', 'sp-toast--error', 'is-visible');
    toastEl.classList.add('sp-toast--' + state);
    var icon = toastEl.querySelector('.sp-toast-icon i');
    icon.className = 'bi ' + (
      state === 'saving' ? 'bi-arrow-repeat' :
      state === 'error' ? 'bi-exclamation-circle' :
      'bi-check-circle'
    );
    toastEl.querySelector('.sp-toast-msg').textContent = message || '';
    // reflow for animation
    void toastEl.offsetWidth;
    toastEl.classList.add('is-visible');
    if (toastTimer) clearTimeout(toastTimer);
    if (state !== 'saving') {
      toastTimer = setTimeout(hideToast, TOAST_MS);
    }
  }

  function hideToast() {
    if (!toastEl) return;
    toastEl.classList.remove('is-visible');
    if (toastTimer) {
      clearTimeout(toastTimer);
      toastTimer = null;
    }
  }

  window.SettingsToast = { show: showToast, hide: hideToast };

  /* ——— Search flash ——— */
  function clearFlash() {
    if (activeFlashEl) {
      activeFlashEl.classList.remove(FLASH_CLASS);
      activeFlashEl = null;
    }
    document.querySelectorAll('.' + FLASH_CLASS).forEach(function (el) {
      el.classList.remove(FLASH_CLASS);
    });
  }

  function flashTarget(el) {
    if (!el) return;
    clearFlash();
    activeFlashEl = el;
    el.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'center' });
    if (prefersReducedMotion()) {
      el.classList.add(FLASH_CLASS);
      setTimeout(clearFlash, 1200);
      return;
    }
    el.classList.add(FLASH_CLASS);
    var onEnd = function (ev) {
      if (ev.target !== el) return;
      el.removeEventListener('animationend', onEnd);
      clearFlash();
    };
    el.addEventListener('animationend', onEnd);
    // safety: pulse is 0.7s * 2
    setTimeout(function () {
      if (activeFlashEl === el) clearFlash();
    }, 1600);
  }

  function runHashFlash() {
    var hash = (window.location.hash || '').replace(/^#/, '');
    if (!hash) return;
    var el = document.getElementById(hash) ||
      document.querySelector('[data-settings-search-id="' + CSS.escape(hash) + '"]');
    if (el) flashTarget(el);
  }

  window.SettingsSearchFlash = { flash: flashTarget, clear: clearFlash, run: runHashFlash };

  /* ——— Collapse ——— */
  function initCollapses(root) {
    (root || document).querySelectorAll('[data-sp-collapse]').forEach(function (wrap) {
      if (wrap.dataset.spCollapseBound === '1') return;
      wrap.dataset.spCollapseBound = '1';
      var btn = wrap.querySelector('[data-sp-collapse-toggle]');
      if (!btn) return;
      btn.addEventListener('click', function () {
        var open = wrap.classList.toggle('is-open');
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    });
  }

  /* ——— Tooltips ——— */
  function initTooltips(root) {
    if (!window.bootstrap || !bootstrap.Tooltip) return;
    (root || document).querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
      bootstrap.Tooltip.getOrCreateInstance(el, { container: 'body', trigger: 'hover focus' });
    });
  }

  /* ——— Autosave ——— */
  function getSaveUrl(form) {
    return form.getAttribute('data-sp-save-url') || form.getAttribute('action') || window.location.pathname;
  }

  function collectFormData(form) {
    return new FormData(form);
  }

  function serializeFormAsUrlEncoded(form) {
    var fd = collectFormData(form);
    var params = new URLSearchParams();
    fd.forEach(function (value, key) {
      if (typeof value === 'string') params.append(key, value);
    });
    return params;
  }

  function markRow(el, cls, on) {
    var row = el.closest('.sp-row');
    if (!row) return;
    row.classList.toggle(cls, !!on);
  }

  function saveForm(form, opts) {
    opts = opts || {};
    var url = getSaveUrl(form);
    var silent = !!opts.silent;
    if (!silent) showToast(t('saving', 'Speichern…'), 'saving');

    var headers = {
      'Accept': 'application/json',
      'X-Requested-With': 'XMLHttpRequest'
    };
    var body;
    var method = (form.getAttribute('method') || 'POST').toUpperCase();
    var isMultipart = (form.getAttribute('enctype') || '').indexOf('multipart') !== -1;

    if (form.getAttribute('data-sp-save-json') === '1') {
      headers['Content-Type'] = 'application/json';
      var obj = {};
      var fdJson = collectFormData(form);
      fdJson.forEach(function (value, key) {
        if (Object.prototype.hasOwnProperty.call(obj, key)) {
          if (!Array.isArray(obj[key])) obj[key] = [obj[key]];
          obj[key].push(value);
        } else {
          obj[key] = value;
        }
      });
      form.querySelectorAll('[data-sp-bool]').forEach(function (input) {
        if (!input.name) return;
        if (input.type === 'checkbox' && !input.checked) obj[input.name] = false;
        else if (input.type === 'checkbox') obj[input.name] = true;
      });
      body = JSON.stringify(obj);
    } else if (isMultipart) {
      body = collectFormData(form);
    } else {
      body = serializeFormAsUrlEncoded(form);
      headers['Content-Type'] = 'application/x-www-form-urlencoded;charset=UTF-8';
    }

    return fetch(url, {
      method: method,
      credentials: 'same-origin',
      headers: headers,
      body: method === 'GET' ? undefined : body
    }).then(function (res) {
      return res.json().then(function (data) {
        return { ok: res.ok && data && data.ok !== false, status: res.status, data: data || {} };
      }).catch(function () {
        return { ok: res.ok, status: res.status, data: {} };
      });
    }).then(function (result) {
        if (result.ok) {
          var msg = (result.data && result.data.message) || t('saved', 'Gespeichert');
          showToast(msg, 'success');
          form.dispatchEvent(new CustomEvent('sp:saved', { detail: result.data }));
          if ((result.data && result.data.reload) || form.dataset.spReloadOnSave === '1') {
            setTimeout(function () { window.location.reload(); }, 450);
          } else if (result.data) {
            applyLiveAppearance(result.data);
          }
        } else {
        var err = (result.data && (result.data.message || result.data.error)) || t('error', 'Speichern fehlgeschlagen');
        showToast(err, 'error');
        form.dispatchEvent(new CustomEvent('sp:save-error', { detail: result.data }));
      }
      return result;
    }).catch(function () {
      showToast(t('error', 'Speichern fehlgeschlagen'), 'error');
      return { ok: false };
    });
  }

  function debounce(fn, ms) {
    var timer;
    return function () {
      var ctx = this;
      var args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(ctx, args); }, ms);
    };
  }

  function bindAutosaveForm(form) {
    if (form.dataset.spAutosaveBound === '1') return;
    form.dataset.spAutosaveBound = '1';

    var schedule = debounce(function () {
      saveForm(form);
    }, DEBOUNCE_MS);

    form.addEventListener('change', function (e) {
      var tEl = e.target;
      if (!tEl || !form.contains(tEl)) return;
      if (tEl.closest('[data-sp-no-autosave]')) return;
      if (tEl.matches('input[type="file"]')) {
        saveForm(form);
        return;
      }
      if (tEl.matches('input[type="text"], input[type="number"], input[type="email"], input[type="tel"], input[type="url"], input[type="search"], input[type="color"], textarea')) {
        // color often fires change once — still ok; input handled below
        if (tEl.matches('input[type="color"]')) {
          schedule();
          return;
        }
        schedule();
        return;
      }
      // checkbox, radio, select — immediate
      saveForm(form);
    });

    form.addEventListener('input', function (e) {
      var tEl = e.target;
      if (!tEl || !form.contains(tEl)) return;
      if (tEl.closest('[data-sp-no-autosave]')) return;
      if (tEl.matches('input[type="text"], input[type="number"], input[type="email"], input[type="tel"], input[type="url"], input[type="search"], input[type="color"], textarea')) {
        markRow(tEl, 'is-saving', true);
        schedule();
      }
    });

    form.addEventListener('sp:saved', function () {
      form.querySelectorAll('.sp-row.is-saving').forEach(function (row) {
        row.classList.remove('is-saving');
      });
    });
  }

  function initAutosave(root) {
    (root || document).querySelectorAll('form[data-sp-autosave]').forEach(bindAutosaveForm);
  }

  /* ——— Search UI ——— */
  function initSearch() {
    var catalog = window.SETTINGS_SEARCH_CATALOG || [];
    document.querySelectorAll('[data-settings-search-root]').forEach(function (root) {
      var input = root.querySelector('[data-settings-search-input]');
      var results = root.querySelector('[data-settings-search-results]');
      var clearBtn = root.querySelector('[data-settings-search-clear]');
      if (!input || !results) return;
      var activeIndex = -1;

      function hideResults() {
        results.classList.add('d-none');
        results.innerHTML = '';
        activeIndex = -1;
      }

      function updateClear() {
        if (!clearBtn) return;
        clearBtn.classList.toggle('d-none', !(input.value || '').trim());
      }

      function navigate(url) {
        if (!url) return;
        // same-page hash flash
        try {
          var u = new URL(url, window.location.origin);
          if (u.pathname === window.location.pathname && u.hash) {
            window.history.replaceState(null, '', u.hash);
            runHashFlash();
            hideResults();
            input.blur();
            return;
          }
        } catch (e) { /* ignore */ }
        window.location.href = url;
      }

      function render(query) {
        var q = (query || '').trim().toLowerCase();
        results.innerHTML = '';
        activeIndex = -1;
        updateClear();
        if (!q) {
          hideResults();
          return;
        }
        var matches = catalog.filter(function (item) {
          return (item.title || '').toLowerCase().indexOf(q) !== -1 ||
            (item.keywords || '').indexOf(q) !== -1;
        }).slice(0, 8);
        if (!matches.length) {
          hideResults();
          return;
        }
        matches.forEach(function (item) {
          var btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'settings-search-item';
          btn.textContent = item.title;
          btn.setAttribute('role', 'option');
          btn.addEventListener('click', function () { navigate(item.url); });
          results.appendChild(btn);
        });
        results.classList.remove('d-none');
      }

      input.addEventListener('input', function () { render(input.value); });
      if (clearBtn) {
        clearBtn.addEventListener('click', function () {
          input.value = '';
          hideResults();
          updateClear();
          input.focus();
        });
      }
      input.addEventListener('keydown', function (e) {
        var items = results.querySelectorAll('.settings-search-item');
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          if (!items.length) return;
          activeIndex = Math.min(activeIndex + 1, items.length - 1);
          items.forEach(function (el, i) { el.classList.toggle('active', i === activeIndex); });
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          if (!items.length) return;
          activeIndex = Math.max(activeIndex - 1, 0);
          items.forEach(function (el, i) { el.classList.toggle('active', i === activeIndex); });
        } else if (e.key === 'Enter') {
          e.preventDefault();
          if (activeIndex >= 0 && items[activeIndex]) {
            items[activeIndex].click();
            return;
          }
          var q = (input.value || '').trim().toLowerCase();
          var first = catalog.find(function (item) {
            return (item.title || '').toLowerCase().indexOf(q) !== -1 ||
              (item.keywords || '').indexOf(q) !== -1;
          });
          if (first) navigate(first.url);
        } else if (e.key === 'Escape') {
          hideResults();
        }
      });
      document.addEventListener('click', function (e) {
        if (!root.contains(e.target)) hideResults();
      });
    });
  }

  function init() {
    initCollapses(document);
    initTooltips(document);
    initAutosave(document);
    initSearch();
    runHashFlash();
    window.addEventListener('hashchange', function () {
      clearFlash();
      runHashFlash();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  function applyLiveAppearance(data) {
    if (!data) return;
    if (data.accent_color) {
      document.documentElement.style.setProperty('--accent-color', data.accent_color);
    }
    if (data.accent_gradient) {
      document.documentElement.style.setProperty('--accent-style', data.accent_gradient);
    } else if (data.accent_color) {
      document.documentElement.style.setProperty('--accent-style', data.accent_color);
    }
    if (typeof data.dark_mode === 'boolean') {
      document.documentElement.setAttribute('data-bs-theme', data.dark_mode ? 'dark' : 'light');
      if (document.body) {
        document.body.classList.toggle('theme-dark', !!data.dark_mode);
      }
    }
    if (typeof data.oled_mode === 'boolean') {
      document.documentElement.setAttribute('data-oled-mode', data.oled_mode ? 'true' : 'false');
    }
  }

  window.SettingsUI = {
    init: init,
    initCollapses: initCollapses,
    initTooltips: initTooltips,
    initAutosave: initAutosave,
    saveForm: saveForm,
    showToast: showToast,
    applyLiveAppearance: applyLiveAppearance
  };
})(window, document);
