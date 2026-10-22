/**
 * Inline editing for duty roster table cells and day notes.
 */
(function () {
    'use strict';

    var cfg = window.DUTY_ROSTER;
    if (!cfg || !cfg.cellUrl) return;

    function csrfHeaders() {
        return {
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': cfg.csrfToken || '',
        };
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
        }).then(function (r) { return r.json(); });
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

        function save() {
            if (input.value === last) return;
            var dayId = cell.getAttribute('data-day-id');
            var columnId = cell.getAttribute('data-column-id');
            postForm(cfg.cellUrl, {
                day_id: dayId,
                column_id: columnId,
                value: input.value,
            }).then(function (res) {
                if (!res || !res.ok) return;
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

        function save() {
            if (input.value === last || !dayId) return;
            var url = (cfg.dayUrlBase || '').replace(/\/0(\/?)$/, '/' + dayId + '$1');
            if (!url || url.indexOf(String(dayId)) === -1) {
                url = '/duty-roster/team/' + cfg.rosterId + '/day/' + dayId;
            }
            postForm(url, { whats_happening: input.value }).then(function (res) {
                if (res && res.ok) last = input.value;
            }).catch(function () {
                input.value = last;
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
