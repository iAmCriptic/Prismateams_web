/**
 * Visual GFM/HTML table widgets inside the shared Markdown editor.
 * Splits the source textarea into text segments + interactive tables.
 */
(function (window, document) {
    'use strict';

    const instances = {};
    let openMenu = null;
    let resizing = null;

    const GFM_ROW = /^\s*\|.*\|\s*$/;
    const GFM_SEP = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/;
    const FENCE_OPEN = /^(\s*)(`{3,}|~{3,})/;

    function t(i18n, path, fallback) {
        const parts = String(path).split('.');
        let cur = i18n;
        for (let i = 0; i < parts.length; i++) {
            if (!cur || typeof cur !== 'object') return fallback;
            cur = cur[parts[i]];
        }
        return typeof cur === 'string' && cur ? cur : fallback;
    }

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function escapeMdCell(str) {
        return String(str).replace(/\n/g, ' ').replace(/\|/g, '\\|');
    }

    function colLabel(i18n, index) {
        const base = t(i18n, 'table.column', 'Spalte');
        return base + ' ' + (index + 1);
    }

    function isFenceLine(line) {
        return FENCE_OPEN.test(line);
    }

    function splitRow(line) {
        let s = String(line).trim();
        if (s.charAt(0) === '|') s = s.slice(1);
        if (s.charAt(s.length - 1) === '|') s = s.slice(0, -1);
        return s.split('|').map(function (cell) {
            return cell.replace(/\\\|/g, '\u0000').trim().replace(/\u0000/g, '|');
        });
    }

    function parseSepAligns(line, colCount) {
        const cells = splitRow(line);
        const aligns = [];
        for (let i = 0; i < colCount; i++) {
            const raw = (cells[i] || '').replace(/\s/g, '');
            if (/^:-+:$/.test(raw)) aligns.push('center');
            else if (/^-+:$/.test(raw)) aligns.push('right');
            else if (/^:-+$/.test(raw)) aligns.push('left');
            else aligns.push('');
        }
        return aligns;
    }

    function padRow(row, cols) {
        const next = row.slice();
        while (next.length < cols) next.push('');
        return next.slice(0, cols);
    }

    function parseHtmlTable(html) {
        let doc;
        try {
            doc = new DOMParser().parseFromString(html, 'text/html');
        } catch (err) {
            return null;
        }
        const table = doc.querySelector('table');
        if (!table) return null;
        const trs = Array.prototype.slice.call(table.querySelectorAll('tr'));
        if (!trs.length) return null;
        const rows = trs.map(function (tr) {
            return Array.prototype.slice.call(tr.querySelectorAll('th,td')).map(function (cell) {
                return (cell.textContent || '').replace(/\s+/g, ' ').trim();
            });
        }).filter(function (row) {
            return row.length;
        });
        if (!rows.length) return null;
        const colCount = rows.reduce(function (max, row) {
            return Math.max(max, row.length);
        }, 0);
        const aligned = rows.map(function (row) {
            return padRow(row, colCount);
        });
        const aligns = [];
        const firstCells = trs[0] ? trs[0].querySelectorAll('th,td') : [];
        for (let c = 0; c < colCount; c++) {
            const cell = firstCells[c];
            const align = cell ? (cell.getAttribute('align') || '') : '';
            aligns.push(align === 'center' || align === 'right' || align === 'left' ? align : '');
        }
        const widths = [];
        const cols = table.querySelectorAll('col');
        let customWidths = false;
        for (let c = 0; c < colCount; c++) {
            const col = cols[c];
            let w = null;
            if (col) {
                const attr = col.getAttribute('width') || '';
                const num = parseFloat(attr);
                if (!isNaN(num) && num > 0) {
                    w = num;
                    customWidths = true;
                }
            }
            widths.push(w);
        }
        return {
            type: 'table',
            rows: aligned,
            aligns: aligns,
            widths: widths,
            customWidths: customWidths
        };
    }

    function tryParseGfmAt(lines, start) {
        if (start + 1 >= lines.length) return null;
        if (!GFM_ROW.test(lines[start]) && !/\|/.test(lines[start])) return null;
        if (!GFM_SEP.test(lines[start + 1])) return null;
        const header = splitRow(lines[start]);
        if (header.length < 2) return null;
        const aligns = parseSepAligns(lines[start + 1], header.length);
        const rows = [padRow(header, header.length)];
        let i = start + 2;
        while (i < lines.length && (GFM_ROW.test(lines[i]) || (/\|/.test(lines[i]) && lines[i].trim() && !isFenceLine(lines[i])))) {
            if (!lines[i].trim()) break;
            if (isFenceLine(lines[i])) break;
            if (lines[i].trim().indexOf('<table') === 0) break;
            rows.push(padRow(splitRow(lines[i]), header.length));
            i += 1;
        }
        return {
            block: {
                type: 'table',
                rows: rows,
                aligns: aligns,
                widths: header.map(function () { return null; }),
                customWidths: false
            },
            end: i
        };
    }

    function parseBlocks(markdown) {
        const text = markdown == null ? '' : String(markdown);
        const lines = text.split('\n');
        const blocks = [];
        let i = 0;
        let inFence = false;
        let fenceMarker = '';
        let fenceLen = 0;
        let textBuf = [];

        function flushText() {
            if (!textBuf.length) return;
            const value = textBuf.join('\n');
            textBuf = [];
            if (blocks.length && blocks[blocks.length - 1].type === 'text') {
                blocks[blocks.length - 1].value += '\n' + value;
            } else {
                blocks.push({ type: 'text', value: value });
            }
        }

        function fenceCloses(line) {
            const m = line.match(FENCE_OPEN);
            if (!m) return false;
            const marker = m[2].charAt(0);
            const len = m[2].length;
            if (marker !== fenceMarker || len < fenceLen) return false;
            return line.trim().slice(len).trim() === '';
        }

        while (i < lines.length) {
            const line = lines[i];
            const fence = line.match(FENCE_OPEN);
            if (fence && !inFence) {
                inFence = true;
                fenceMarker = fence[2].charAt(0);
                fenceLen = fence[2].length;
                textBuf.push(line);
                i += 1;
                continue;
            }
            if (inFence) {
                if (fenceCloses(line)) inFence = false;
                textBuf.push(line);
                i += 1;
                continue;
            }

            if (line.trim().toLowerCase().indexOf('<table') === 0) {
                const rest = lines.slice(i).join('\n');
                const closeAt = rest.toLowerCase().indexOf('</table>');
                if (closeAt !== -1) {
                    const html = rest.slice(0, closeAt + 8);
                    const parsed = parseHtmlTable(html);
                    if (parsed) {
                        flushText();
                        blocks.push(parsed);
                        const consumed = html.split('\n').length;
                        i += consumed;
                        continue;
                    }
                }
            }

            const gfm = tryParseGfmAt(lines, i);
            if (gfm) {
                flushText();
                blocks.push(gfm.block);
                i = gfm.end;
                continue;
            }

            textBuf.push(line);
            i += 1;
        }
        flushText();

        if (!blocks.length) {
            blocks.push({ type: 'text', value: text });
        }
        return blocks;
    }

    function serializeGfm(model) {
        const cols = model.rows[0] ? model.rows[0].length : 0;
        if (!cols) return '';
        function rowLine(cells) {
            return '| ' + cells.map(escapeMdCell).join(' | ') + ' |';
        }
        function sepCell(align) {
            if (align === 'center') return ':---:';
            if (align === 'right') return '---:';
            if (align === 'left') return ':---';
            return '---';
        }
        const lines = [rowLine(padRow(model.rows[0], cols))];
        lines.push('| ' + (model.aligns || []).concat([]).slice(0, cols)
            .concat(new Array(cols).fill('')).slice(0, cols)
            .map(sepCell).join(' | ') + ' |');
        for (let r = 1; r < model.rows.length; r++) {
            lines.push(rowLine(padRow(model.rows[r], cols)));
        }
        return lines.join('\n');
    }

    function serializeHtml(model) {
        const cols = model.rows[0] ? model.rows[0].length : 0;
        if (!cols) return '';
        const aligns = model.aligns || [];
        let html = '<table>\n';
        if (model.customWidths && model.widths && model.widths.length) {
            html += '<colgroup>\n';
            for (let c = 0; c < cols; c++) {
                const w = model.widths[c];
                if (w != null && !isNaN(Number(w))) {
                    html += '<col width="' + Number(w) + '%">\n';
                } else {
                    html += '<col>\n';
                }
            }
            html += '</colgroup>\n';
        }
        html += '<thead>\n<tr>\n';
        for (let c = 0; c < cols; c++) {
            const align = aligns[c];
            const attr = align ? ' align="' + align + '"' : '';
            html += '<th' + attr + '>' + escapeHtml(model.rows[0][c] || '') + '</th>\n';
        }
        html += '</tr>\n</thead>\n<tbody>\n';
        for (let r = 1; r < model.rows.length; r++) {
            html += '<tr>\n';
            for (let c = 0; c < cols; c++) {
                const align = aligns[c];
                const attr = align ? ' align="' + align + '"' : '';
                html += '<td' + attr + '>' + escapeHtml(model.rows[r][c] || '') + '</td>\n';
            }
            html += '</tr>\n';
        }
        html += '</tbody>\n</table>';
        return html;
    }

    function serializeTable(model) {
        const hasAlign = (model.aligns || []).some(function (a) { return !!a; });
        if (model.customWidths || hasAlign) return serializeHtml(model);
        return serializeGfm(model);
    }

    function serializeBlocks(blocks) {
        return blocks.map(function (block) {
            if (block.type === 'table') return serializeTable(block);
            return block.value == null ? '' : String(block.value);
        }).join('\n\n').replace(/\n{3,}/g, '\n\n');
    }

    function defaultTable(i18n) {
        return {
            type: 'table',
            rows: [
                [colLabel(i18n, 0), colLabel(i18n, 1), colLabel(i18n, 2)],
                ['', '', ''],
                ['', '', '']
            ],
            aligns: ['', '', ''],
            widths: [null, null, null],
            customWidths: false
        };
    }

    function closeMenu() {
        const had = !!openMenu;
        if (openMenu && openMenu.parentNode) {
            openMenu.parentNode.removeChild(openMenu);
        }
        openMenu = null;
        return had;
    }

    function placeMenu(anchor, items) {
        closeMenu();
        const menu = document.createElement('div');
        menu.className = 'md-table-menu';
        menu.setAttribute('role', 'menu');
        items.forEach(function (item) {
            if (item.sep) {
                const hr = document.createElement('div');
                hr.className = 'md-table-menu-sep';
                menu.appendChild(hr);
                return;
            }
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'md-table-menu-item' + (item.danger ? ' is-danger' : '');
            btn.setAttribute('role', 'menuitem');
            btn.textContent = item.label;
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                closeMenu();
                item.onClick();
            });
            menu.appendChild(btn);
        });
        document.body.appendChild(menu);
        const rect = anchor.getBoundingClientRect();
        const mw = menu.offsetWidth;
        const mh = menu.offsetHeight;
        let left = rect.left;
        let top = rect.bottom + 4;
        if (left + mw > window.innerWidth - 8) left = window.innerWidth - mw - 8;
        if (top + mh > window.innerHeight - 8) top = rect.top - mh - 4;
        menu.style.left = Math.max(8, left) + 'px';
        menu.style.top = Math.max(8, top) + 'px';
        openMenu = menu;
    }

    function autosize(ta) {
        ta.style.height = 'auto';
        const min = ta.classList.contains('md-segment-textarea--solo') ? 120 : 36;
        ta.style.height = Math.max(ta.scrollHeight, min) + 'px';
    }

    function stopResize() {
        if (!resizing) return;
        document.removeEventListener('mousemove', resizing.move);
        document.removeEventListener('mouseup', resizing.up);
        document.body.classList.remove('md-table-resizing');
        resizing = null;
    }

    function createInstance(editorId, options) {
        const textarea = document.getElementById(editorId);
        if (!textarea) return null;

        const i18n = options.i18n || {};
        const locked = !!options.locked;

        if (textarea.dataset.mdTableMounted === '1') {
            return instances[editorId] || null;
        }

        const wrap = document.createElement('div');
        wrap.className = 'md-editor-wrap';
        textarea.parentNode.insertBefore(wrap, textarea);
        wrap.appendChild(textarea);
        textarea.classList.add('md-editor-source');
        textarea.setAttribute('aria-hidden', 'true');
        textarea.tabIndex = -1;

        const doc = document.createElement('div');
        doc.className = 'md-editor-doc';
        wrap.appendChild(doc);

        const inst = {
            id: editorId,
            textarea: textarea,
            wrap: wrap,
            doc: doc,
            i18n: i18n,
            locked: locked,
            activeTextarea: null,
            activeCell: null,
            widgets: []
        };

        function readBlocksFromDom() {
            const blocks = [];
            Array.prototype.forEach.call(doc.children, function (child) {
                if (child.classList.contains('md-segment-textarea')) {
                    blocks.push({ type: 'text', value: child.value });
                    return;
                }
                if (child.classList.contains('md-table-widget')) {
                    const idx = Number(child.getAttribute('data-widget-index'));
                    if (inst.widgets[idx]) blocks.push(inst.widgets[idx].model);
                }
            });
            return blocks;
        }

        function sync() {
            const value = serializeBlocks(readBlocksFromDom());
            if (textarea.value !== value) {
                textarea.value = value;
                textarea.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }

        function setActiveCell(widgetIndex, row, col) {
            inst.activeCell = { widgetIndex: widgetIndex, row: row, col: col };
            inst.activeTextarea = null;
            doc.querySelectorAll('.md-table-widget').forEach(function (el) {
                el.classList.toggle('is-active', Number(el.getAttribute('data-widget-index')) === widgetIndex);
            });
        }

        function highlightColumn(widgetEl, col, on) {
            widgetEl.querySelectorAll('[data-col="' + col + '"]').forEach(function (el) {
                el.classList.toggle('is-col-hi', on);
            });
        }

        function rebuildWidget(widgetIndex) {
            const widget = inst.widgets[widgetIndex];
            if (!widget) return;
            const oldEl = widget.el;
            const next = renderTableWidget(widget.model, widgetIndex);
            inst.widgets[widgetIndex].el = next;
            if (oldEl && oldEl.parentNode) {
                oldEl.parentNode.replaceChild(next, oldEl);
            }
            sync();
        }

        function deleteWidget(widgetIndex) {
            inst.widgets[widgetIndex] = null;
            remount();
        }

        function insertCol(model, at) {
            model.rows.forEach(function (row, r) {
                row.splice(at, 0, r === 0 ? colLabel(i18n, at) : '');
            });
            model.aligns.splice(at, 0, '');
            if (model.widths) model.widths.splice(at, 0, null);
        }

        function insertRow(model, at) {
            const cols = model.rows[0] ? model.rows[0].length : 1;
            const row = [];
            for (let c = 0; c < cols; c++) row.push('');
            model.rows.splice(at, 0, row);
        }

        function renderTableWidget(model, widgetIndex) {
            const cols = model.rows[0] ? model.rows[0].length : 0;
            const widgetEl = document.createElement('div');
            widgetEl.className = 'md-table-widget';
            widgetEl.setAttribute('data-widget-index', String(widgetIndex));

            const chrome = document.createElement('div');
            chrome.className = 'md-table-chrome';

            const colBar = document.createElement('div');
            colBar.className = 'md-table-colbar';
            colBar.style.gridTemplateColumns = '2rem repeat(' + cols + ', minmax(4rem, 1fr)) 2rem';

            const colBarSpacer = document.createElement('span');
            colBar.appendChild(colBarSpacer);

            for (let c = 0; c < cols; c++) {
                (function (col) {
                    const cell = document.createElement('div');
                    cell.className = 'md-table-colctl';
                    cell.setAttribute('data-col', String(col));
                    if (!locked) {
                        const add = document.createElement('button');
                        add.type = 'button';
                        add.className = 'md-table-add';
                        add.title = t(i18n, 'table.insert_col_before', 'Spalte davor einfügen');
                        add.setAttribute('aria-label', add.title);
                        add.innerHTML = '<i class="bi bi-plus" aria-hidden="true"></i>';
                        add.addEventListener('click', function (e) {
                            e.preventDefault();
                            insertCol(model, col);
                            rebuildWidget(widgetIndex);
                        });
                        const menuBtn = document.createElement('button');
                        menuBtn.type = 'button';
                        menuBtn.className = 'md-table-kebab';
                        menuBtn.title = t(i18n, 'table.column_menu', 'Spalte');
                        menuBtn.setAttribute('aria-label', menuBtn.title);
                        menuBtn.innerHTML = '<i class="bi bi-three-dots" aria-hidden="true"></i>';
                        menuBtn.addEventListener('click', function (e) {
                            e.preventDefault();
                            e.stopPropagation();
                            placeMenu(menuBtn, [
                                {
                                    label: t(i18n, 'table.insert_col_before', 'Spalte davor einfügen'),
                                    onClick: function () { insertCol(model, col); rebuildWidget(widgetIndex); }
                                },
                                {
                                    label: t(i18n, 'table.insert_col_after', 'Spalte danach einfügen'),
                                    onClick: function () { insertCol(model, col + 1); rebuildWidget(widgetIndex); }
                                },
                                { sep: true },
                                {
                                    label: t(i18n, 'table.align_left', 'Linksbündig'),
                                    onClick: function () { model.aligns[col] = 'left'; rebuildWidget(widgetIndex); }
                                },
                                {
                                    label: t(i18n, 'table.align_center', 'Zentriert'),
                                    onClick: function () { model.aligns[col] = 'center'; rebuildWidget(widgetIndex); }
                                },
                                {
                                    label: t(i18n, 'table.align_right', 'Rechtsbündig'),
                                    onClick: function () { model.aligns[col] = 'right'; rebuildWidget(widgetIndex); }
                                },
                                { sep: true },
                                {
                                    label: t(i18n, 'table.delete_col', 'Spalte löschen'),
                                    danger: true,
                                    onClick: function () {
                                        if (cols <= 1) return;
                                        model.rows.forEach(function (row) { row.splice(col, 1); });
                                        model.aligns.splice(col, 1);
                                        if (model.widths) model.widths.splice(col, 1);
                                        rebuildWidget(widgetIndex);
                                    }
                                }
                            ]);
                        });
                        cell.appendChild(add);
                        cell.appendChild(menuBtn);
                    }
                    cell.addEventListener('mouseenter', function () { highlightColumn(widgetEl, col, true); });
                    cell.addEventListener('mouseleave', function () { highlightColumn(widgetEl, col, false); });
                    colBar.appendChild(cell);
                })(c);
            }

            const addColEnd = document.createElement('div');
            addColEnd.className = 'md-table-colctl md-table-colctl--end';
            if (!locked) {
                const addEnd = document.createElement('button');
                addEnd.type = 'button';
                addEnd.className = 'md-table-add';
                addEnd.title = t(i18n, 'table.add_col', 'Spalte hinzufügen');
                addEnd.setAttribute('aria-label', addEnd.title);
                addEnd.innerHTML = '<i class="bi bi-plus" aria-hidden="true"></i>';
                addEnd.addEventListener('click', function (e) {
                    e.preventDefault();
                    insertCol(model, cols);
                    rebuildWidget(widgetIndex);
                });
                addColEnd.appendChild(addEnd);
            }
            colBar.appendChild(addColEnd);

            const bodyRow = document.createElement('div');
            bodyRow.className = 'md-table-bodyrow';

            const rowBar = document.createElement('div');
            rowBar.className = 'md-table-rowbar';

            for (let r = 0; r < model.rows.length; r++) {
                (function (row) {
                    const cell = document.createElement('div');
                    cell.className = 'md-table-rowctl' + (row === 0 ? ' is-head' : '');
                    if (!locked) {
                        const add = document.createElement('button');
                        add.type = 'button';
                        add.className = 'md-table-add';
                        add.title = t(i18n, 'table.insert_row_before', 'Zeile davor einfügen');
                        add.setAttribute('aria-label', add.title);
                        add.innerHTML = '<i class="bi bi-plus" aria-hidden="true"></i>';
                        add.addEventListener('click', function (e) {
                            e.preventDefault();
                            insertRow(model, row === 0 ? 1 : row);
                            rebuildWidget(widgetIndex);
                        });
                        const menuBtn = document.createElement('button');
                        menuBtn.type = 'button';
                        menuBtn.className = 'md-table-kebab';
                        menuBtn.title = t(i18n, 'table.row_menu', 'Zeile');
                        menuBtn.setAttribute('aria-label', menuBtn.title);
                        menuBtn.innerHTML = '<i class="bi bi-three-dots-vertical" aria-hidden="true"></i>';
                        menuBtn.addEventListener('click', function (e) {
                            e.preventDefault();
                            e.stopPropagation();
                            const items = [
                                {
                                    label: t(i18n, 'table.insert_row_before', 'Zeile davor einfügen'),
                                    onClick: function () {
                                        insertRow(model, row === 0 ? 1 : row);
                                        rebuildWidget(widgetIndex);
                                    }
                                },
                                {
                                    label: t(i18n, 'table.insert_row_after', 'Zeile danach einfügen'),
                                    onClick: function () {
                                        insertRow(model, row + 1);
                                        rebuildWidget(widgetIndex);
                                    }
                                }
                            ];
                            if (row > 0) {
                                items.push({ sep: true });
                                items.push({
                                    label: t(i18n, 'table.delete_row', 'Zeile löschen'),
                                    danger: true,
                                    onClick: function () {
                                        if (model.rows.length <= 2) return;
                                        model.rows.splice(row, 1);
                                        rebuildWidget(widgetIndex);
                                    }
                                });
                            }
                            placeMenu(menuBtn, items);
                        });
                        cell.appendChild(add);
                        cell.appendChild(menuBtn);
                    }
                    rowBar.appendChild(cell);
                })(r);
            }

            const scroll = document.createElement('div');
            scroll.className = 'md-table-scroll';

            const table = document.createElement('table');
            table.className = 'md-table-grid';
            if (model.customWidths) table.classList.add('has-col-widths');

            const colgroup = document.createElement('colgroup');
            for (let c = 0; c < cols; c++) {
                const colEl = document.createElement('col');
                if (model.customWidths && model.widths && model.widths[c] != null) {
                    colEl.setAttribute('width', String(model.widths[c]) + '%');
                }
                colgroup.appendChild(colEl);
            }
            table.appendChild(colgroup);

            model.rows.forEach(function (row, r) {
                const tr = document.createElement('tr');
                row.forEach(function (value, c) {
                    const cell = document.createElement(r === 0 ? 'th' : 'td');
                    cell.setAttribute('data-col', String(c));
                    cell.setAttribute('data-row', String(r));
                    if (model.aligns[c]) cell.setAttribute('align', model.aligns[c]);
                    cell.contentEditable = locked ? 'false' : 'true';
                    cell.spellcheck = true;
                    cell.textContent = value || '';
                    cell.addEventListener('focus', function () {
                        setActiveCell(widgetIndex, r, c);
                        highlightColumn(widgetEl, c, true);
                    });
                    cell.addEventListener('blur', function () {
                        highlightColumn(widgetEl, c, false);
                        model.rows[r][c] = cell.textContent || '';
                        sync();
                    });
                    cell.addEventListener('input', function () {
                        model.rows[r][c] = cell.textContent || '';
                        sync();
                    });
                    cell.addEventListener('keydown', function (e) {
                        if (e.key === 'Tab') {
                            e.preventDefault();
                            const dir = e.shiftKey ? -1 : 1;
                            let nr = r;
                            let nc = c + dir;
                            if (nc >= cols) {
                                nc = 0;
                                nr += 1;
                            } else if (nc < 0) {
                                nc = cols - 1;
                                nr -= 1;
                            }
                            if (nr >= model.rows.length && !e.shiftKey && !locked) {
                                insertRow(model, model.rows.length);
                                rebuildWidget(widgetIndex);
                                const next = inst.widgets[widgetIndex] && inst.widgets[widgetIndex].el;
                                const target = next && next.querySelector('[data-row="' + nr + '"][data-col="0"]');
                                if (target) target.focus();
                                return;
                            }
                            const target = widgetEl.querySelector('[data-row="' + nr + '"][data-col="' + nc + '"]');
                            if (target) target.focus();
                            return;
                        }
                        if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault();
                            let nr = r + 1;
                            if (nr >= model.rows.length && !locked) {
                                insertRow(model, model.rows.length);
                                rebuildWidget(widgetIndex);
                                const next = inst.widgets[widgetIndex] && inst.widgets[widgetIndex].el;
                                const target = next && next.querySelector('[data-row="' + nr + '"][data-col="' + c + '"]');
                                if (target) target.focus();
                                return;
                            }
                            const target = widgetEl.querySelector('[data-row="' + nr + '"][data-col="' + c + '"]');
                            if (target) target.focus();
                        }
                    });
                    if (!locked) {
                        const handle = document.createElement('span');
                        handle.className = 'md-table-resize';
                        handle.setAttribute('data-resize-col', String(c));
                        handle.addEventListener('mousedown', function (e) {
                            e.preventDefault();
                            e.stopPropagation();
                            const startX = e.clientX;
                            const colEls = table.querySelectorAll('col');
                            const start = Array.prototype.map.call(colEls, function (el) {
                                return el.getBoundingClientRect ? el.getBoundingClientRect().width : 80;
                            });
                            if (!start.length) {
                                Array.prototype.forEach.call(table.querySelector('tr').children, function (td) {
                                    start.push(td.getBoundingClientRect().width);
                                });
                            }
                            const total = start.reduce(function (a, b) { return a + b; }, 0) || 1;
                            function move(ev) {
                                const dx = ev.clientX - startX;
                                const next = start.slice();
                                next[c] = Math.max(48, start[c] + dx);
                                if (c + 1 < next.length) {
                                    next[c + 1] = Math.max(48, start[c + 1] - dx);
                                }
                                const sum = next.reduce(function (a, b) { return a + b; }, 0) || 1;
                                model.widths = next.map(function (w) {
                                    return Math.round((w / sum) * 1000) / 10;
                                });
                                model.customWidths = true;
                                Array.prototype.forEach.call(table.querySelectorAll('col'), function (el, idx) {
                                    if (model.widths[idx] != null) {
                                        el.setAttribute('width', String(model.widths[idx]) + '%');
                                    }
                                });
                                table.classList.add('has-col-widths');
                            }
                            function up() {
                                stopResize();
                                sync();
                            }
                            stopResize();
                            resizing = { move: move, up: up };
                            document.body.classList.add('md-table-resizing');
                            document.addEventListener('mousemove', move);
                            document.addEventListener('mouseup', up);
                        });
                        cell.appendChild(handle);
                    }
                    tr.appendChild(cell);
                });
                table.appendChild(tr);
            });

            scroll.appendChild(table);

            const addColSide = document.createElement('div');
            addColSide.className = 'md-table-side-add';
            if (!locked) {
                const sideBtn = document.createElement('button');
                sideBtn.type = 'button';
                sideBtn.className = 'md-table-add md-table-add--lg';
                sideBtn.title = t(i18n, 'table.add_col', 'Spalte hinzufügen');
                sideBtn.setAttribute('aria-label', sideBtn.title);
                sideBtn.innerHTML = '<i class="bi bi-plus" aria-hidden="true"></i>';
                sideBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    insertCol(model, cols);
                    rebuildWidget(widgetIndex);
                });
                addColSide.appendChild(sideBtn);
            }

            bodyRow.appendChild(rowBar);
            bodyRow.appendChild(scroll);
            bodyRow.appendChild(addColSide);

            const foot = document.createElement('div');
            foot.className = 'md-table-foot';
            if (!locked) {
                const addRow = document.createElement('button');
                addRow.type = 'button';
                addRow.className = 'md-table-add md-table-add--lg';
                addRow.title = t(i18n, 'table.add_row', 'Zeile hinzufügen');
                addRow.setAttribute('aria-label', addRow.title);
                addRow.innerHTML = '<i class="bi bi-plus" aria-hidden="true"></i>';
                addRow.addEventListener('click', function (e) {
                    e.preventDefault();
                    insertRow(model, model.rows.length);
                    rebuildWidget(widgetIndex);
                });
                foot.appendChild(addRow);

                const delTable = document.createElement('button');
                delTable.type = 'button';
                delTable.className = 'md-table-delete';
                delTable.title = t(i18n, 'table.delete_table', 'Tabelle löschen');
                delTable.setAttribute('aria-label', delTable.title);
                delTable.innerHTML = '<i class="bi bi-trash" aria-hidden="true"></i>';
                delTable.addEventListener('click', function (e) {
                    e.preventDefault();
                    deleteWidget(widgetIndex);
                });
                foot.appendChild(delTable);
            }

            chrome.appendChild(colBar);
            chrome.appendChild(bodyRow);
            chrome.appendChild(foot);
            widgetEl.appendChild(chrome);
            return widgetEl;
        }

        function bindSegment(ta) {
            ta.addEventListener('focus', function () {
                inst.activeTextarea = ta;
                inst.activeCell = null;
                doc.querySelectorAll('.md-table-widget.is-active').forEach(function (el) {
                    el.classList.remove('is-active');
                });
            });
            ta.addEventListener('input', function () {
                autosize(ta);
                sync();
            });
            ta.addEventListener('paste', function () {
                window.setTimeout(function () {
                    autosize(ta);
                    sync();
                    const blocks = parseBlocks(ta.value);
                    const hasTable = blocks.some(function (b) { return b.type === 'table'; });
                    if (hasTable) remount(ta);
                }, 0);
            });
            ta.addEventListener('blur', function () {
                const blocks = parseBlocks(ta.value);
                if (blocks.some(function (b) { return b.type === 'table'; })) {
                    remount(ta);
                }
            });
        }

        function remount(focusTa) {
            const selStart = focusTa && typeof focusTa.selectionStart === 'number' ? focusTa.selectionStart : null;
            const focusPos = focusTa ? offsetOfTextarea(focusTa) : null;
            sync();
            const blocks = parseBlocks(textarea.value);
            renderBlocks(blocks);
            if (focusPos != null && selStart != null) {
                restoreTextFocus(focusPos + selStart);
            }
        }

        function offsetOfTextarea(ta) {
            let offset = 0;
            const children = Array.prototype.slice.call(doc.children);
            for (let i = 0; i < children.length; i++) {
                const child = children[i];
                if (child === ta) return offset;
                if (child.classList.contains('md-segment-textarea')) {
                    offset += child.value.length + 2;
                } else if (child.classList.contains('md-table-widget')) {
                    const idx = Number(child.getAttribute('data-widget-index'));
                    const model = inst.widgets[idx] && inst.widgets[idx].model;
                    offset += (model ? serializeTable(model).length : 0) + 2;
                }
            }
            return offset;
        }

        function restoreTextFocus(absPos) {
            let offset = 0;
            const children = Array.prototype.slice.call(doc.children);
            for (let i = 0; i < children.length; i++) {
                const child = children[i];
                if (!child.classList.contains('md-segment-textarea')) {
                    const idx = Number(child.getAttribute('data-widget-index'));
                    const model = inst.widgets[idx] && inst.widgets[idx].model;
                    offset += (model ? serializeTable(model).length : 0) + 2;
                    continue;
                }
                const len = child.value.length;
                if (absPos <= offset + len) {
                    const local = Math.max(0, Math.min(len, absPos - offset));
                    child.focus();
                    child.setSelectionRange(local, local);
                    inst.activeTextarea = child;
                    return;
                }
                offset += len + 2;
            }
        }

        function renderBlocks(blocks) {
            inst.widgets = [];
            doc.innerHTML = '';
            const onlyText = blocks.length === 1 && blocks[0].type === 'text';
            if (blocks.length && blocks[0].type === 'table') {
                const lead = document.createElement('textarea');
                lead.className = 'md-segment-textarea';
                lead.value = '';
                lead.placeholder = textarea.placeholder || '';
                if (locked) lead.readOnly = true;
                bindSegment(lead);
                doc.appendChild(lead);
                autosize(lead);
            }
            blocks.forEach(function (block) {
                if (block.type === 'table') {
                    const idx = inst.widgets.length;
                    const el = renderTableWidget(block, idx);
                    inst.widgets.push({ model: block, el: el });
                    doc.appendChild(el);
                    return;
                }
                const ta = document.createElement('textarea');
                ta.className = 'md-segment-textarea' + (onlyText ? ' md-segment-textarea--solo' : '');
                ta.value = block.value || '';
                ta.placeholder = textarea.placeholder || '';
                if (locked) {
                    ta.readOnly = true;
                }
                bindSegment(ta);
                doc.appendChild(ta);
                autosize(ta);
            });
            if (!blocks.length || (blocks.length && blocks[blocks.length - 1].type === 'table')) {
                const ta = document.createElement('textarea');
                ta.className = 'md-segment-textarea';
                ta.value = '';
                ta.placeholder = textarea.placeholder || '';
                if (locked) ta.readOnly = true;
                bindSegment(ta);
                doc.appendChild(ta);
                autosize(ta);
            }
        }

        function insertTableAtCursor() {
            sync();
            const active = inst.activeTextarea || doc.querySelector('.md-segment-textarea');
            let pos = textarea.value.length;
            if (active) {
                pos = offsetOfTextarea(active) + (typeof active.selectionStart === 'number' ? active.selectionStart : active.value.length);
            }
            const tableMd = serializeGfm(defaultTable(i18n));
            const before = textarea.value.slice(0, pos).replace(/\s*$/, '');
            const after = textarea.value.slice(pos).replace(/^\s*/, '');
            const glueBefore = before && !before.endsWith('\n') ? '\n\n' : (before ? '\n' : '');
            const glueAfter = after ? '\n\n' : '\n';
            textarea.value = before + glueBefore + tableMd + glueAfter + after;
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
            renderBlocks(parseBlocks(textarea.value));
            const lastWidget = doc.querySelector('.md-table-widget:last-of-type [data-row="1"][data-col="0"]')
                || doc.querySelector('.md-table-widget:last-of-type [contenteditable="true"]');
            if (lastWidget) lastWidget.focus();
            return true;
        }

        wrap.addEventListener('keydown', function (e) {
            if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) {
                e.preventDefault();
                sync();
                if (typeof window.saveFile === 'function' && editorId === 'markdownEditor') {
                    window.saveFile();
                } else if (typeof window.savePage === 'function') {
                    window.savePage();
                }
            }
        });

        textarea.dataset.mdTableMounted = '1';
        renderBlocks(parseBlocks(textarea.value));

        inst.sync = sync;
        inst.insertTableAtCursor = insertTableAtCursor;
        inst.remount = remount;
        inst.getActiveTextarea = function () {
            if (inst.activeTextarea && inst.doc.contains(inst.activeTextarea)) {
                return inst.activeTextarea;
            }
            const focused = document.activeElement;
            if (focused && focused.classList && focused.classList.contains('md-segment-textarea') && inst.doc.contains(focused)) {
                return focused;
            }
            return null;
        };
        inst.getActiveCellApi = function () {
            const focused = document.activeElement;
            if (!focused || !inst.doc.contains(focused)) return null;
            if (!focused.hasAttribute('data-row') || !focused.hasAttribute('data-col')) return null;
            const widgetEl = focused.closest('.md-table-widget');
            if (!widgetEl) return null;
            const idx = Number(widgetEl.getAttribute('data-widget-index'));
            const r = Number(focused.getAttribute('data-row'));
            const c = Number(focused.getAttribute('data-col'));
            const widget = inst.widgets[idx];
            if (!widget) return null;
            return {
                getText: function () {
                    return focused.textContent || '';
                },
                setText: function (value) {
                    focused.textContent = value;
                    widget.model.rows[r][c] = value;
                    sync();
                }
            };
        };

        instances[editorId] = inst;
        return inst;
    }

    document.addEventListener('click', function (e) {
        if (openMenu && !openMenu.contains(e.target) && !e.target.closest('.md-table-kebab')) {
            closeMenu();
        }
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && openMenu) {
            closeMenu();
        }
    });

    window.MarkdownTableEditor = {
        mount: function (editorId, options) {
            if (!editorId) return null;
            if (instances[editorId]) return instances[editorId];
            return createInstance(editorId, options || {});
        },
        getActiveTextarea: function (editorId) {
            const inst = instances[editorId];
            return inst ? inst.getActiveTextarea() : null;
        },
        getActiveCell: function (editorId) {
            const inst = instances[editorId];
            return inst ? inst.getActiveCellApi() : null;
        },
        insertTable: function (editorId) {
            const inst = instances[editorId];
            if (!inst) return false;
            return inst.insertTableAtCursor();
        },
        sync: function (editorId) {
            const inst = instances[editorId];
            if (inst) inst.sync();
        },
        getContent: function (editorId) {
            const inst = instances[editorId];
            if (inst) {
                inst.sync();
                return inst.textarea.value;
            }
            const el = document.getElementById(editorId);
            return el ? el.value : '';
        },
        closeMenus: closeMenu,
        parseBlocks: parseBlocks
    };
})(window, document);
