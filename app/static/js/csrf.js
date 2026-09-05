/**
 * CSRF helpers: inject token into forms and same-origin mutating fetch/XHR.
 */
(function () {
  function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    var input = document.querySelector('input[name="csrf_token"]');
    return input && input.value ? input.value : '';
  }

  function ensureFormToken(form) {
    if (!(form instanceof HTMLFormElement)) return;
    var method = (form.getAttribute('method') || 'get').toLowerCase();
    if (method === 'get') return;
    if (form.querySelector('input[name="csrf_token"]')) return;
    var token = getCsrfToken();
    if (!token) return;
    var input = document.createElement('input');
    input.type = 'hidden';
    input.name = 'csrf_token';
    input.value = token;
    form.appendChild(input);
  }

  document.addEventListener(
    'submit',
    function (event) {
      ensureFormToken(event.target);
    },
    true
  );

  var mutating = { POST: 1, PUT: 1, PATCH: 1, DELETE: 1 };

  if (typeof window.fetch === 'function') {
    var originalFetch = window.fetch;
    window.fetch = function (input, init) {
      init = init || {};
      var method = (init.method || 'GET').toUpperCase();
      if (mutating[method]) {
        var headers = new Headers(init.headers || {});
        if (!headers.has('X-CSRFToken') && !headers.has('X-CSRF-Token')) {
          var token = getCsrfToken();
          if (token) headers.set('X-CSRFToken', token);
        }
        init.headers = headers;
      }
      return originalFetch.call(this, input, init);
    };
  }

  if (typeof XMLHttpRequest !== 'undefined') {
    var originalOpen = XMLHttpRequest.prototype.open;
    var originalSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method) {
      this._ptCsrfMethod = (method || 'GET').toUpperCase();
      return originalOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function () {
      if (mutating[this._ptCsrfMethod || '']) {
        try {
          if (!this.getRequestHeader || true) {
            var token = getCsrfToken();
            if (token) this.setRequestHeader('X-CSRFToken', token);
          }
        } catch (err) {
          /* header may already be set */
        }
      }
      return originalSend.apply(this, arguments);
    };
  }

  window.PrismateamsCsrf = { getToken: getCsrfToken, ensureFormToken: ensureFormToken };
})();
