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

            var animateNext = false;

            function render() {
                var prevCount = list.querySelectorAll('.protocols-chip').length;
                list.innerHTML = names.map(function (name, idx) {
                    var enterClass = (animateNext && idx >= prevCount) ? ' is-entering' : '';
                    return (
                        '<span class="protocols-chip' + enterClass + '" data-chip-index="' + idx + '">' +
                        '<span class="protocols-chip-label">' + escapeHtml(name) + '</span>' +
                        '<button type="button" class="protocols-chip-remove" data-chip-remove aria-label="Remove">&times;</button>' +
                        '</span>'
                    );
                }).join('');
                animateNext = false;
                syncHidden();
            }

            function addName(raw) {
                var name = String(raw || '').trim();
                if (!name) return;
                // Split pasted "a, b" into multiple chips
                var added = false;
                parseNames(name).forEach(function (part) {
                    var exists = names.some(function (n) {
                        return n.toLowerCase() === part.toLowerCase();
                    });
                    if (!exists) {
                        names.push(part);
                        added = true;
                    }
                });
                if (added) animateNext = true;
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
            node.classList.add('is-entering');
            list.appendChild(node);
            bindRemove(node);
            node.setAttribute('draggable', 'true');
            var input = node.querySelector('input[name="titles"]');
            if (input) input.focus();
            window.setTimeout(function () {
                node.classList.remove('is-entering');
            }, 320);
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

        var hasBetterTable = typeof quillBetterTable !== 'undefined';
        if (hasBetterTable) {
            Quill.register({ 'modules/better-table': quillBetterTable }, true);
        }

        var toolbarOptions = [
            [{ size: ['small', false, 'large', 'huge'] }],
            ['bold', 'italic', 'underline', 'strike'],
            [{ color: [] }, { background: [] }],
            [{ list: 'ordered' }, { list: 'bullet' }],
            [{ align: [] }],
            ['blockquote'],
            ['table'],
            ['clean'],
        ];

        var toolbarEl = document.getElementById('protocolsEditorToolbar');
        var modules = {
            toolbar: {
                container: toolbarEl || toolbarOptions,
                handlers: {
                    table: function () {
                        if (!hasBetterTable) {
                            insertFallbackTable(this.quill);
                            return;
                        }
                        var tableModule = this.quill.getModule('better-table');
                        if (tableModule) tableModule.insertTable(3, 3);
                    },
                },
            },
        };

        if (toolbarEl) {
            // Build toolbar DOM from config into our dedicated pill surface
            toolbarEl.innerHTML = '';
            toolbarOptions.forEach(function (group) {
                var formats = document.createElement('span');
                formats.className = 'ql-formats';
                group.forEach(function (item) {
                    if (typeof item === 'string') {
                        var btn = document.createElement('button');
                        btn.type = 'button';
                        btn.className = 'ql-' + item;
                        formats.appendChild(btn);
                    } else if (item && typeof item === 'object') {
                        Object.keys(item).forEach(function (key) {
                            var val = item[key];
                            if (Array.isArray(val)) {
                                var select = document.createElement('select');
                                select.className = 'ql-' + key;
                                val.forEach(function (v) {
                                    var opt = document.createElement('option');
                                    if (v === false) {
                                        opt.setAttribute('selected', 'selected');
                                    } else {
                                        opt.setAttribute('value', v);
                                    }
                                    select.appendChild(opt);
                                });
                                formats.appendChild(select);
                            } else {
                                var b = document.createElement('button');
                                b.type = 'button';
                                b.className = 'ql-' + key;
                                if (val !== true && val != null) b.setAttribute('value', val);
                                formats.appendChild(b);
                            }
                        });
                    }
                });
                toolbarEl.appendChild(formats);
            });
        }

        if (hasBetterTable) {
            modules.table = false;
            modules['better-table'] = {
                operationMenu: {
                    items: {
                        insertColumnRight: { text: 'Spalte rechts' },
                        insertColumnLeft: { text: 'Spalte links' },
                        insertRowUp: { text: 'Zeile darüber' },
                        insertRowDown: { text: 'Zeile darunter' },
                        mergeCells: { text: 'Zellen verbinden' },
                        unmergeCells: { text: 'Zellen trennen' },
                        deleteColumn: { text: 'Spalte löschen' },
                        deleteRow: { text: 'Zeile löschen' },
                        deleteTable: { text: 'Tabelle löschen' },
                    },
                },
            };
            if (quillBetterTable.keyboardBindings) {
                modules.keyboard = {
                    bindings: quillBetterTable.keyboardBindings,
                };
            }
        }

        var quill = new Quill('#protocolsEditor', {
            theme: 'snow',
            modules: modules,
            placeholder: '',
        });

        styleToolbarIcons(quill);
        polishToolbarChrome(quill);

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

        form.addEventListener('submit', function () {
            syncHidden();
        });
    }

    function insertFallbackTable(quill) {
        var range = quill.getSelection(true) || { index: quill.getLength(), length: 0 };
        var html =
            '<table class="protocols-ql-table"><tbody>' +
            '<tr><td><br></td><td><br></td><td><br></td></tr>' +
            '<tr><td><br></td><td><br></td><td><br></td></tr>' +
            '<tr><td><br></td><td><br></td><td><br></td></tr>' +
            '</tbody></table><p><br></p>';
        quill.clipboard.dangerouslyPasteHTML(range.index, html, 'user');
        quill.setSelection(range.index + 1, 0, 'silent');
    }

    function styleToolbarIcons(quill) {
        var toolbar = quill.getModule('toolbar');
        if (!toolbar || !toolbar.container) return;
        var i18n = window.PROTOCOLS_I18N || {};
        var tableBtn = toolbar.container.querySelector('.ql-table');
        if (tableBtn && !tableBtn.querySelector('svg, i')) {
            tableBtn.setAttribute('title', i18n.table || 'Tabelle');
            tableBtn.innerHTML = '<i class="bi bi-table" aria-hidden="true"></i>';
        }
        var colorBtn = toolbar.container.querySelector('.ql-color .ql-picker-label');
        if (colorBtn) colorBtn.setAttribute('title', i18n.color || 'Schriftfarbe');
        var bgBtn = toolbar.container.querySelector('.ql-background .ql-picker-label');
        if (bgBtn) bgBtn.setAttribute('title', i18n.highlight || 'Textmarker');
        var sizeBtn = toolbar.container.querySelector('.ql-size .ql-picker-label');
        if (sizeBtn) sizeBtn.setAttribute('title', i18n.size || 'Schriftgröße');

        // Localized size picker labels (Quill uses CSS ::before content)
        var styleId = 'protocols-ql-size-i18n';
        if (!document.getElementById(styleId)) {
            var style = document.createElement('style');
            style.id = styleId;
            var normal = i18n.size_normal || 'Normal';
            var small = i18n.size_small || 'Klein';
            var large = i18n.size_large || 'Groß';
            var huge = i18n.size_huge || 'Sehr groß';
            style.textContent =
                '.protocols-editor-surface .ql-toolbar .ql-picker.ql-size .ql-picker-label::before,' +
                '.protocols-editor-surface .ql-toolbar .ql-picker.ql-size .ql-picker-item::before,' +
                '#protocolsEditorToolbar .ql-picker.ql-size .ql-picker-label::before,' +
                '#protocolsEditorToolbar .ql-picker.ql-size .ql-picker-item::before{content:' + JSON.stringify(normal) + ';}' +
                '.protocols-editor-surface .ql-toolbar .ql-picker.ql-size .ql-picker-label[data-value="small"]::before,' +
                '.protocols-editor-surface .ql-toolbar .ql-picker.ql-size .ql-picker-item[data-value="small"]::before,' +
                '#protocolsEditorToolbar .ql-picker.ql-size .ql-picker-label[data-value="small"]::before,' +
                '#protocolsEditorToolbar .ql-picker.ql-size .ql-picker-item[data-value="small"]::before{content:' + JSON.stringify(small) + ';}' +
                '.protocols-editor-surface .ql-toolbar .ql-picker.ql-size .ql-picker-label[data-value="large"]::before,' +
                '.protocols-editor-surface .ql-toolbar .ql-picker.ql-size .ql-picker-item[data-value="large"]::before,' +
                '#protocolsEditorToolbar .ql-picker.ql-size .ql-picker-label[data-value="large"]::before,' +
                '#protocolsEditorToolbar .ql-picker.ql-size .ql-picker-item[data-value="large"]::before{content:' + JSON.stringify(large) + ';}' +
                '.protocols-editor-surface .ql-toolbar .ql-picker.ql-size .ql-picker-label[data-value="huge"]::before,' +
                '.protocols-editor-surface .ql-toolbar .ql-picker.ql-size .ql-picker-item[data-value="huge"]::before,' +
                '#protocolsEditorToolbar .ql-picker.ql-size .ql-picker-label[data-value="huge"]::before,' +
                '#protocolsEditorToolbar .ql-picker.ql-size .ql-picker-item[data-value="huge"]::before{content:' + JSON.stringify(huge) + ';}';
            document.head.appendChild(style);
        }
    }

    function polishToolbarChrome(quill) {
        var toolbar = quill.getModule('toolbar');
        var el = (toolbar && toolbar.container) || document.getElementById('protocolsEditorToolbar');
        if (!el) return;
        el.classList.add('protocols-ql-toolbar', 'ql-toolbar', 'ql-snow');
    }

    document.addEventListener('DOMContentLoaded', function () {
        initChipFields();
        initAgenda();
        initQuillEditor();
    });
})();
