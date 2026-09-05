/**
 * Protokollführung — chips, agenda reorder, Quill editor / autosave
 */
(function () {
    'use strict';

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function parseNames(raw) {
        return String(raw || '')
            .split(/[\n,;]+/)
            .map(function (s) { return s.trim(); })
            .filter(Boolean);
    }

    function initChipFields() {
        document.querySelectorAll('[data-chip-field]').forEach(function (field) {
            var list = field.querySelector('[data-chip-list]');
            var input = field.querySelector('[data-chip-input]');
            var hidden = field.querySelector('[data-chip-value]');
            if (!list || !input || !hidden) return;

            var names = parseNames(hidden.value);

            function syncHidden() {
                hidden.value = names.join(', ');
            }

            function render() {
                list.innerHTML = names.map(function (name, idx) {
                    return (
                        '<span class="protocols-chip" data-chip-index="' + idx + '">' +
                        '<span class="protocols-chip-label">' + escapeHtml(name) + '</span>' +
                        '<button type="button" class="protocols-chip-remove" data-chip-remove aria-label="Remove">&times;</button>' +
                        '</span>'
                    );
                }).join('');
                syncHidden();
            }

            function addName(raw) {
                var name = String(raw || '').trim();
                if (!name) return;
                // Split pasted "a, b" into multiple chips
                parseNames(name).forEach(function (part) {
                    var exists = names.some(function (n) {
                        return n.toLowerCase() === part.toLowerCase();
                    });
                    if (!exists) names.push(part);
                });
                render();
            }

            function removeAt(idx) {
                if (idx < 0 || idx >= names.length) return;
                names.splice(idx, 1);
                render();
            }

            field.addEventListener('click', function (e) {
                var btn = e.target.closest('[data-chip-remove]');
                if (btn) {
                    e.preventDefault();
                    var chip = btn.closest('[data-chip-index]');
                    if (chip) removeAt(parseInt(chip.getAttribute('data-chip-index'), 10));
                    input.focus();
                    return;
                }
                input.focus();
            });

            input.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ',') {
                    e.preventDefault();
                    addName(input.value);
                    input.value = '';
                    return;
                }
                if (e.key === 'Backspace' && !input.value && names.length) {
                    e.preventDefault();
                    removeAt(names.length - 1);
                }
            });

            input.addEventListener('blur', function () {
                if (input.value.trim()) {
                    addName(input.value);
                    input.value = '';
                }
            });

            input.addEventListener('paste', function (e) {
                var text = (e.clipboardData || window.clipboardData).getData('text');
                if (text && /[,;\n]/.test(text)) {
                    e.preventDefault();
                    addName(text);
                    input.value = '';
                }
            });

            var form = field.closest('form');
            if (form) {
                form.addEventListener('submit', function () {
                    if (input.value.trim()) {
                        addName(input.value);
                        input.value = '';
                    }
                    syncHidden();
                });
            }

            render();
        });
    }

    function initAgenda() {
        var list = document.getElementById('protocolsAgendaList');
        var addBtn = document.getElementById('protocolsAddAgenda');
        var tpl = document.getElementById('protocolsAgendaItemTpl');
        if (!list || !addBtn || !tpl) return;

        function bindRemove(li) {
            var btn = li.querySelector('[data-remove-agenda]');
            if (!btn) return;
            btn.addEventListener('click', function () {
                if (list.querySelectorAll('[data-agenda-item]').length <= 1) {
                    var input = li.querySelector('input[name="titles"]');
                    if (input) input.value = '';
                    return;
                }
                li.remove();
            });
        }

        list.querySelectorAll('[data-agenda-item]').forEach(bindRemove);

        addBtn.addEventListener('click', function () {
            var node = tpl.content.firstElementChild.cloneNode(true);
            list.appendChild(node);
            bindRemove(node);
            node.setAttribute('draggable', 'true');
            var input = node.querySelector('input[name="titles"]');
            if (input) input.focus();
        });

        var dragEl = null;
        list.querySelectorAll('[data-agenda-item]').forEach(function (li) {
            li.setAttribute('draggable', 'true');
        });

        list.addEventListener('dragstart', function (e) {
            var li = e.target.closest('[data-agenda-item]');
            if (!li) return;
            dragEl = li;
            li.classList.add('is-dragging');
            e.dataTransfer.effectAllowed = 'move';
        });
        list.addEventListener('dragend', function () {
            if (dragEl) dragEl.classList.remove('is-dragging');
            dragEl = null;
        });
        list.addEventListener('dragover', function (e) {
            e.preventDefault();
            var li = e.target.closest('[data-agenda-item]');
            if (!li || li === dragEl || !dragEl) return;
            var rect = li.getBoundingClientRect();
            var before = (e.clientY - rect.top) < rect.height / 2;
            list.insertBefore(dragEl, before ? li : li.nextSibling);
        });

        var observer = new MutationObserver(function () {
            list.querySelectorAll('[data-agenda-item]').forEach(function (li) {
                li.setAttribute('draggable', 'true');
            });
        });
        observer.observe(list, { childList: true });
    }

    function initQuillEditor() {
        var editorEl = document.getElementById('protocolsEditor');
        var form = document.getElementById('protocolsItemForm');
        var hidden = document.getElementById('contentHtml');
        if (!editorEl || !form || !hidden || typeof Quill === 'undefined') return;

        var quill = new Quill('#protocolsEditor', {
            theme: 'snow',
            modules: {
                toolbar: [
                    ['bold', 'italic', 'underline'],
                    [{ list: 'ordered' }, { list: 'bullet' }],
                ],
            },
            placeholder: '',
        });

        var initial = window.PROTOCOLS_INITIAL_HTML || '';
        if (initial) {
            try {
                quill.clipboard.dangerouslyPasteHTML(initial);
            } catch (e) {
                quill.root.innerHTML = initial;
            }
        }

        function syncHidden() {
            hidden.value = quill.root.innerHTML;
        }

        syncHidden();

        var statusEl = document.getElementById('protocolsAutosaveStatus');
        var autosaveUrl = form.getAttribute('data-autosave-url');
        var timer = null;
        var i18n = window.PROTOCOLS_I18N || {};

        function autosave() {
            if (!autosaveUrl) return;
            syncHidden();
            if (statusEl) statusEl.textContent = i18n.saving || '';
            var titleInput = document.getElementById('itemTitle');
            fetch(autosaveUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: JSON.stringify({
                    title: titleInput ? titleInput.value : '',
                    content_html: hidden.value,
                }),
                credentials: 'same-origin',
            })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (statusEl && data && data.ok) {
                        statusEl.textContent = i18n.autosaved || '';
                    }
                })
                .catch(function () { /* ignore */ });
        }

        function scheduleAutosave() {
            if (timer) clearTimeout(timer);
            timer = setTimeout(autosave, 1200);
        }

        quill.on('text-change', scheduleAutosave);
        var titleInput = document.getElementById('itemTitle');
        if (titleInput) titleInput.addEventListener('input', scheduleAutosave);

        form.addEventListener('submit', function (e) {
            syncHidden();
            var submitter = e.submitter;
            if (submitter && submitter.getAttribute('data-confirm-finalize')) {
                if (!window.confirm(submitter.getAttribute('data-confirm-finalize'))) {
                    e.preventDefault();
                }
            }
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        initChipFields();
        initAgenda();
        initQuillEditor();
    });
})();
