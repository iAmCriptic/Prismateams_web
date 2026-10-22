/**
 * Inline editing for duty roster table cells and day notes.
 */
(function () {
    'use strict';

    var cfg = window.DUTY_ROSTER;
    if (!cfg || !cfg.cellUrl) return;

    var i18n = cfg.i18n || {};

    function csrfHeaders() {
        return {
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': cfg.csrfToken || '',
        };
    }

    function notify(message, category) {
        var msg = String(message || '');
        if (!msg) return;
        if (typeof window.showAppBanner === 'function') {
            window.showAppBanner(msg, category || 'danger');
            return;
        }
        console.warn(msg);
    }

    function parseJsonResponse(r) {
        return r.text().then(function (text) {
            var data = null;
            if (text) {
                try {
                    data = JSON.parse(text);
                } catch (err) {
                    data = null;
                }
            }
            return { okHttp: r.ok, status: r.status, data: data };
        });
    }

    function postForm(url, data) {
        var body = new URLSearchParams();
        Object.keys(data).forEach(function (k) {
            body.append(k, data[k] == null ? '' : String(data[k]));
        });
        if (cfg.csrfToken) body.append('csrf_token', cfg.csrfToken);
        return fetch(url, {
            method: 'POST',
            headers: Object.assign({
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json',
            }, csrfHeaders()),
            body: body.toString(),
            credentials: 'same-origin',
        }).then(parseJsonResponse);
    }

    function errorMessage(result, fallback) {
        if (result && result.data && result.data.message) {
            return String(result.data.message);
        }
        if (result && result.data && result.data.error) {
            var code = String(result.data.error);
            if (code === 'denied' && i18n.cellDenied) return i18n.cellDenied;
            if (code === 'not_found' && i18n.cellNotFound) return i18n.cellNotFound;
            if (code === 'inactive' && i18n.cellInactive) return i18n.cellInactive;
        }
        if (result && result.status === 403 && i18n.cellDenied) return i18n.cellDenied;
        if (result && result.status === 404 && i18n.cellNotFound) return i18n.cellNotFound;
        return fallback || i18n.cellSaveFailed || 'Speichern fehlgeschlagen.';
    }

    function updateKwHours(columnId, week, hours) {
        document.querySelectorAll(
            'td.duty-kw-hours-cell[data-kw-hours-col="' + columnId + '"][data-week="' + week + '"] .duty-kw-hours-val,' +
            '[data-kw-hours-col="' + columnId + '"][data-week="' + week + '"] .duty-kw-hours-val'
        ).forEach(function (el) {
            el.textContent = hours;
        });
    }

    function updateVacationPill(columnId, remaining) {
        if (remaining == null || columnId == null) return;
        document.querySelectorAll(
            '.duty-vacation-pill[data-vacation-col="' + columnId + '"]'
        ).forEach(function (el) {
            el.textContent = remaining + 'U';
        });
    }

    document.querySelectorAll('.duty-cell-input').forEach(function (input) {
        var cell = input.closest('.duty-cell');
        if (!cell) return;
        var last = input.value;
        var saving = false;

        function save() {
            if (saving || input.value === last) return;
            var dayId = cell.getAttribute('data-day-id');
            var columnId = cell.getAttribute('data-column-id');
            var attempted = input.value;
            saving = true;
            input.classList.add('is-saving');
            postForm(cfg.cellUrl, {
                day_id: dayId,
                column_id: columnId,
                value: attempted,
            }).then(function (result) {
                var res = result && result.data;
                if (!result.okHttp || !res || !res.ok) {
                    input.value = last;
                    notify(errorMessage(result, i18n.cellSaveFailed), 'danger');
                    return;
                }
                last = res.display || '';
                input.value = last;
                if (typeof res.week_hours === 'number' && res.week != null) {
                    updateKwHours(columnId, res.week, res.week_hours);
                }
                if (Object.prototype.hasOwnProperty.call(res, 'vacation_remaining')) {
                    updateVacationPill(columnId, res.vacation_remaining);
                }
            }).catch(function () {
                input.value = last;
                notify(i18n.cellSaveFailed || 'Speichern fehlgeschlagen.', 'danger');
            }).then(function () {
                saving = false;
                input.classList.remove('is-saving');
            });
        }

        input.addEventListener('blur', save);
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                input.blur();
            }
        });
    });

    document.querySelectorAll('.duty-whats-input').forEach(function (input) {
        var last = input.value;
        var dayId = input.getAttribute('data-day-id');
        var saving = false;

        function save() {
            if (saving || input.value === last || !dayId) return;
            var url = (cfg.dayUrlBase || '').replace(/\/0(\/?)$/, '/' + dayId + '$1');
            if (!url || url.indexOf(String(dayId)) === -1) {
                url = '/duty-roster/team/' + cfg.rosterId + '/day/' + dayId;
            }
            var attempted = input.value;
            saving = true;
            input.classList.add('is-saving');
            postForm(url, { whats_happening: attempted }).then(function (result) {
                var res = result && result.data;
                if (!result.okHttp || !res || !res.ok) {
                    input.value = last;
                    notify(errorMessage(result, i18n.daySaveFailed), 'danger');
                    return;
                }
                last = attempted;
            }).catch(function () {
                input.value = last;
                notify(i18n.daySaveFailed || 'Speichern fehlgeschlagen.', 'danger');
            }).then(function () {
                saving = false;
                input.classList.remove('is-saving');
            });
        }

        input.addEventListener('blur', save);
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                input.blur();
            }
        });
    });
})();
