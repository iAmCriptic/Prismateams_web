/**
 * Shared Markdown editor toolbar: formatting, visual tables, link popover, mobile sheet.
 */
(function (window, document) {
    'use strict';

    const DEFAULT_LABELS = {
        text: 'Text',
        heading: 'Überschrift',
        link_text: 'Link-Text',
        code: 'Code',
        list_item: 'Listenpunkt',
        page_name: 'Seitenname',
        quote: 'Zitat',
        alt_text: 'Alt-Text',
        math: 'Formel',
        mermaid: 'graph TD\n    A --> B'
    };

    const MD_LINK_RE = /\[([^\]]*)\]\(([^)\s]*)(?:\s+"([^"]*)")?\)/g;

    let state = {
        editorId: null,
        locked: false,
        labels: Object.assign({}, DEFAULT_LABELS),
        extras: { wikilink: false },
        i18n: {}
    };

    let caretChipTimer = null;

    function t(path, fallback) {
        const parts = String(path).split('.');
        let cur = state.i18n;
        for (let i = 0; i < parts.length; i++) {
            if (!cur || typeof cur !== 'object') return fallback;
            cur = cur[parts[i]];
        }
        return typeof cur === 'string' && cur ? cur : fallback;
    }

    function getSourceEditor() {
        if (!state.editorId) return null;
        return document.getElementById(state.editorId);
    }

    function getEditor() {
        if (state.editorId && window.MarkdownTableEditor) {
            const vis = window.MarkdownTableEditor.getActiveTextarea(state.editorId);
            if (vis) return vis;
        }
        return getSourceEditor();
    }

    function syncVisual() {
        if (state.editorId && window.MarkdownTableEditor) {
            window.MarkdownTableEditor.sync(state.editorId);
        }
    }

    function label(key) {
        return state.labels[key] || DEFAULT_LABELS[key] || key;
    }

    function applyReplacement(editor, start, end, replacement, cursorPos) {
        const textBefore = editor.value.substring(0, start);
        const textAfter = editor.value.substring(end);
        editor.value = textBefore + replacement + textAfter;
        const pos = typeof cursorPos === 'number' ? cursorPos : start + replacement.length;
        editor.setSelectionRange(pos, pos);
        editor.focus();
        editor.dispatchEvent(new Event('input', { bubbles: true }));
        syncVisual();
    }

    function wrapActiveCell(prefix, suffix) {
        if (!state.editorId || !window.MarkdownTableEditor) return false;
        const cell = window.MarkdownTableEditor.getActiveCell(state.editorId);
        if (!cell) return false;
        const text = cell.getText() || label('text');
        cell.setText(prefix + text + suffix);
        return true;
    }

    function findLinkAtCursor(editor) {
        if (!editor || typeof editor.value !== 'string') return null;
        const pos = typeof editor.selectionStart === 'number' ? editor.selectionStart : 0;
        const text = editor.value;
        MD_LINK_RE.lastIndex = 0;
        let match;
        while ((match = MD_LINK_RE.exec(text))) {
            const start = match.index;
            const end = start + match[0].length;
            if (pos >= start && pos <= end) {
                return {
                    start: start,
                    end: end,
                    text: match[1],
                    url: match[2]
                };
            }
        }
        return null;
    }

    function normalizeUrl(url) {
        const raw = String(url || '').trim();
        if (!raw) return raw;
        if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(raw)) return raw;
        if (raw.charAt(0) === '/' || raw.charAt(0) === '#' || raw.charAt(0) === '.') return raw;
        return 'https://' + raw;
    }

    function ensureLinkPopover() {
        let pop = document.getElementById('markdownLinkPopover');
        if (pop) return pop;
        pop = document.createElement('div');
        pop.id = 'markdownLinkPopover';
        pop.className = 'md-link-popover';
        pop.hidden = true;
        pop.innerHTML =
            '<div class="md-link-popover-head">' +
                '<span class="md-link-popover-title" data-md-link-title></span>' +
                '<button type="button" class="md-link-popover-x" data-md-link-cancel aria-label="">' +
                    '<i class="bi bi-x-lg" aria-hidden="true"></i>' +
                '</button>' +
            '</div>' +
            '<label class="md-link-field">' +
                '<span data-md-link-text-label></span>' +
                '<input type="text" class="form-control" id="markdownLinkText" autocomplete="off">' +
            '</label>' +
            '<label class="md-link-field">' +
                '<span data-md-link-url-label></span>' +
                '<input type="url" class="form-control" id="markdownLinkUrl" inputmode="url" autocomplete="off">' +
            '</label>' +
            '<div class="md-link-popover-actions">' +
                '<button type="button" class="btn btn-outline-secondary mod-pill-btn" data-md-link-cancel></button>' +
                '<button type="button" class="btn btn-accent mod-pill-btn" data-md-link-apply></button>' +
            '</div>';
        document.body.appendChild(pop);
        pop.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                closeLinkPopover();
            }
            if (e.key === 'Enter' && e.target && e.target.tagName === 'INPUT') {
                e.preventDefault();
                applyLinkPopover();
            }
        });
        pop.querySelectorAll('[data-md-link-cancel]').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                closeLinkPopover();
            });
        });
        const applyBtn = pop.querySelector('[data-md-link-apply]');
        if (applyBtn) {
            applyBtn.addEventListener('click', function (e) {
                e.preventDefault();
                applyLinkPopover();
            });
        }
        return pop;
    }

    function fillLinkPopoverLabels(pop, isEdit) {
        const title = pop.querySelector('[data-md-link-title]');
        const textLabel = pop.querySelector('[data-md-link-text-label]');
        const urlLabel = pop.querySelector('[data-md-link-url-label]');
        const applyBtn = pop.querySelector('[data-md-link-apply]');
        const cancelBtns = pop.querySelectorAll('[data-md-link-cancel]');
        if (title) {
            title.textContent = isEdit
                ? t('link.edit_title', 'Link bearbeiten')
                : t('link.insert_title', 'Link einfügen');
        }
        if (textLabel) textLabel.textContent = t('link.text', 'Linktext');
        if (urlLabel) urlLabel.textContent = t('link.url', 'URL');
        if (applyBtn) {
            applyBtn.textContent = isEdit ? t('link.save', 'Übernehmen') : t('link.insert', 'Einfügen');
        }
        cancelBtns.forEach(function (btn) {
            if (btn.classList.contains('md-link-popover-x')) {
                btn.setAttribute('aria-label', t('link.cancel', 'Abbrechen'));
            } else {
                btn.textContent = t('link.cancel', 'Abbrechen');
            }
        });
    }

    let linkPopoverCtx = null;
    let linkPopoverIgnoreClick = false;

    function openLinkPopover() {
        if (state.locked) return;
        const cell = state.editorId && window.MarkdownTableEditor
            ? window.MarkdownTableEditor.getActiveCell(state.editorId)
            : null;
        const editor = getEditor();
        const pop = ensureLinkPopover();
        const textInput = pop.querySelector('#markdownLinkText');
        const urlInput = pop.querySelector('#markdownLinkUrl');

        let existing = null;
        let selectedText = '';
        if (cell) {
            const cellText = cell.getText();
            MD_LINK_RE.lastIndex = 0;
            const m = MD_LINK_RE.exec(cellText);
            if (m && m[0] === cellText.trim()) {
                existing = { text: m[1], url: m[2], cell: true };
            } else {
                selectedText = cellText;
            }
        } else if (editor) {
            existing = findLinkAtCursor(editor);
            selectedText = editor.value.substring(editor.selectionStart, editor.selectionEnd);
        }

        fillLinkPopoverLabels(pop, !!existing);
        textInput.value = existing ? existing.text : (selectedText || '');
        urlInput.value = existing ? existing.url : '';
        linkPopoverCtx = {
            editor: editor,
            cell: cell,
            existing: existing
        };
        pop.hidden = false;
        linkPopoverIgnoreClick = true;
        window.setTimeout(function () {
            linkPopoverIgnoreClick = false;
        }, 0);
        positionLinkPopover(pop);
        window.setTimeout(function () {
            if (textInput.value) urlInput.focus();
            else textInput.focus();
        }, 0);
    }

    function positionLinkPopover(pop) {
        const toolbarBtn = document.querySelector('.markdown-editor-toolbar [onclick*="link"], .markdown-editor-toolbar [data-md-action="link"]');
        const editor = getEditor();
        let rect = null;
        if (document.activeElement && document.activeElement.getBoundingClientRect) {
            const active = document.activeElement;
            if (active.closest && (active.closest('.md-table-widget') || active.classList.contains('md-segment-textarea'))) {
                rect = active.getBoundingClientRect();
            }
        }
        if (!rect && toolbarBtn) rect = toolbarBtn.getBoundingClientRect();
        if (!rect && editor) rect = editor.getBoundingClientRect();
        if (!rect) {
            pop.style.left = '50%';
            pop.style.top = '4.5rem';
            pop.style.transform = 'translateX(-50%)';
            return;
        }
        pop.style.transform = '';
        const width = pop.offsetWidth || 320;
        let left = rect.left;
        let top = rect.bottom + 8;
        if (left + width > window.innerWidth - 12) left = window.innerWidth - width - 12;
        if (top + 240 > window.innerHeight) top = Math.max(12, rect.top - 240);
        pop.style.left = Math.max(12, left) + 'px';
        pop.style.top = Math.max(12, top) + 'px';
    }

    function closeLinkPopover() {
        const pop = document.getElementById('markdownLinkPopover');
        if (pop) pop.hidden = true;
        linkPopoverCtx = null;
        const editor = getEditor();
        if (editor) editor.focus();
    }

    function isLinkPopoverOpen() {
        const pop = document.getElementById('markdownLinkPopover');
        return !!(pop && !pop.hidden);
    }

    function applyLinkPopover() {
        const pop = document.getElementById('markdownLinkPopover');
        if (!pop || !linkPopoverCtx) return;
        const textInput = pop.querySelector('#markdownLinkText');
        const urlInput = pop.querySelector('#markdownLinkUrl');
        const linkText = (textInput.value || '').trim() || label('link_text');
        const url = normalizeUrl(urlInput.value || '');
        if (!url) {
            urlInput.focus();
            return;
        }
        const md = '[' + linkText + '](' + url + ')';
        if (linkPopoverCtx.cell) {
            linkPopoverCtx.cell.setText(md);
            closeLinkPopover();
            return;
        }
        const editor = linkPopoverCtx.editor || getEditor();
        if (!editor) {
            closeLinkPopover();
            return;
        }
        const existing = linkPopoverCtx.existing;
        if (existing && typeof existing.start === 'number') {
            applyReplacement(editor, existing.start, existing.end, md, existing.start + md.length);
        } else {
            const start = editor.selectionStart;
            const end = editor.selectionEnd;
            applyReplacement(editor, start, end, md, start + md.length);
        }
        closeLinkPopover();
    }

    function getCaretCoordinates(textarea, position) {
        const div = document.createElement('div');
        const style = window.getComputedStyle(textarea);
        const props = [
            'boxSizing', 'width', 'height', 'overflowX', 'overflowY',
            'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth',
            'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
            'fontStyle', 'fontVariant', 'fontWeight', 'fontStretch', 'fontSize',
            'fontSizeAdjust', 'lineHeight', 'fontFamily', 'textAlign', 'textTransform',
            'textIndent', 'textDecoration', 'letterSpacing', 'wordSpacing',
            'whiteSpace', 'wordBreak', 'tabSize'
        ];
        div.style.position = 'absolute';
        div.style.visibility = 'hidden';
        div.style.whiteSpace = 'pre-wrap';
        div.style.wordWrap = 'break-word';
        props.forEach(function (prop) {
            div.style[prop] = style[prop];
        });
        div.textContent = textarea.value.substring(0, position);
        const span = document.createElement('span');
        span.textContent = textarea.value.substring(position) || '.';
        div.appendChild(span);
        document.body.appendChild(div);
        const rect = textarea.getBoundingClientRect();
        const coords = {
            top: span.offsetTop - textarea.scrollTop + rect.top,
            left: span.offsetLeft - textarea.scrollLeft + rect.left
        };
        document.body.removeChild(div);
        return coords;
    }

    function ensureCaretChip() {
        let chip = document.getElementById('markdownLinkCaretChip');
        if (chip) return chip;
        chip = document.createElement('div');
        chip.id = 'markdownLinkCaretChip';
        chip.className = 'md-link-caret-chip';
        chip.hidden = true;
        chip.innerHTML =
            '<span class="md-link-caret-url"></span>' +
            '<button type="button" class="md-link-caret-btn" data-md-caret-open title="">' +
                '<i class="bi bi-box-arrow-up-right" aria-hidden="true"></i>' +
            '</button>' +
            '<button type="button" class="md-link-caret-btn" data-md-caret-edit title="">' +
                '<i class="bi bi-pencil" aria-hidden="true"></i>' +
            '</button>';
        document.body.appendChild(chip);
        chip.querySelector('[data-md-caret-open]').addEventListener('click', function (e) {
            e.preventDefault();
            const url = chip.getAttribute('data-url');
            if (url) window.open(url, '_blank', 'noopener');
        });
        chip.querySelector('[data-md-caret-edit]').addEventListener('click', function (e) {
            e.preventDefault();
            openLinkPopover();
        });
        return chip;
    }

    function hideCaretChip() {
        const chip = document.getElementById('markdownLinkCaretChip');
        if (chip) chip.hidden = true;
    }

    function updateCaretChip() {
        if (state.locked || isLinkPopoverOpen()) {
            hideCaretChip();
            return;
        }
        const editor = getEditor();
        if (!editor || document.activeElement !== editor) {
            hideCaretChip();
            return;
        }
        const found = findLinkAtCursor(editor);
        if (!found) {
            hideCaretChip();
            return;
        }
        const chip = ensureCaretChip();
        const urlEl = chip.querySelector('.md-link-caret-url');
        const openBtn = chip.querySelector('[data-md-caret-open]');
        const editBtn = chip.querySelector('[data-md-caret-edit]');
        if (urlEl) urlEl.textContent = found.url;
        chip.setAttribute('data-url', found.url);
        if (openBtn) openBtn.title = t('link.open', 'Öffnen');
        if (editBtn) editBtn.title = t('link.edit', 'Bearbeiten');
        const coords = getCaretCoordinates(editor, found.start);
        chip.hidden = false;
        chip.style.left = Math.max(8, coords.left) + 'px';
        chip.style.top = Math.max(8, coords.top + 22) + 'px';
    }

    function formatText(type) {
        if (state.locked) return;
        if (type === 'link') {
            openLinkPopover();
            return;
        }
        if (type === 'table') {
            insertTable();
            return;
        }
        if (type === 'hr') {
            insertHorizontalRule();
            return;
        }

        if (['bold', 'italic', 'strikethrough', 'code'].indexOf(type) !== -1) {
            const wraps = {
                bold: ['**', '**'],
                italic: ['*', '*'],
                strikethrough: ['~~', '~~'],
                code: ['`', '`']
            };
            if (wrapActiveCell(wraps[type][0], wraps[type][1])) return;
        }

        const editor = getEditor();
        if (!editor) return;

        const start = editor.selectionStart;
        const end = editor.selectionEnd;
        const selectedText = editor.value.substring(start, end);
        const textBefore = editor.value.substring(0, start);
        const lineStart = textBefore.lastIndexOf('\n') + 1;
        const currentLine = editor.value.substring(lineStart, end);

        let replacement = '';
        let newCursorPos = start;

        switch (type) {
            case 'bold':
                replacement = `**${selectedText || label('text')}**`;
                newCursorPos = start + replacement.length;
                break;
            case 'italic':
                replacement = `*${selectedText || label('text')}*`;
                newCursorPos = start + replacement.length;
                break;
            case 'strikethrough':
                replacement = `~~${selectedText || label('text')}~~`;
                newCursorPos = start + replacement.length;
                break;
            case 'heading1':
                replacement = `# ${selectedText || label('heading')}`;
                newCursorPos = start + replacement.length;
                break;
            case 'heading2':
                replacement = `## ${selectedText || label('heading')}`;
                newCursorPos = start + replacement.length;
                break;
            case 'heading3':
                replacement = `### ${selectedText || label('heading')}`;
                newCursorPos = start + replacement.length;
                break;
            case 'image':
                replacement = `![${selectedText || label('alt_text')}](URL)`;
                newCursorPos = start + replacement.length - 4;
                break;
            case 'code':
                replacement = `\`${selectedText || label('code')}\``;
                newCursorPos = start + replacement.length;
                break;
            case 'codeBlock':
                replacement = `\`\`\`\n${selectedText || label('code')}\n\`\`\``;
                newCursorPos = start + 4;
                break;
            case 'list':
                if (currentLine.trim().startsWith('- ') || currentLine.trim().startsWith('* ')) {
                    replacement = selectedText || label('list_item');
                } else {
                    replacement = `- ${selectedText || label('list_item')}`;
                }
                newCursorPos = start + replacement.length;
                break;
            case 'orderedList':
                if (/^\d+\.\s/.test(currentLine.trim())) {
                    replacement = selectedText || label('list_item');
                } else {
                    replacement = `1. ${selectedText || label('list_item')}`;
                }
                newCursorPos = start + replacement.length;
                break;
            case 'blockquote':
                if (currentLine.trim().startsWith('> ')) {
                    replacement = selectedText || label('quote');
                } else {
                    replacement = `> ${selectedText || label('quote')}`;
                }
                newCursorPos = start + replacement.length;
                break;
            case 'superscript':
                replacement = `^${selectedText || label('text')}^`;
                newCursorPos = start + replacement.length;
                break;
            case 'subscript':
                replacement = `~${selectedText || label('text')}~`;
                newCursorPos = start + replacement.length;
                break;
            case 'footnote':
                replacement = `[^${selectedText || '1'}]`;
                newCursorPos = start + replacement.length;
                break;
            case 'wikilink':
                if (!state.extras.wikilink) return;
                replacement = `[[${selectedText || label('page_name')}]]`;
                newCursorPos = start + replacement.length;
                break;
            case 'mathInline':
                replacement = `$${selectedText || label('math')}$`;
                newCursorPos = start + 1;
                if (selectedText) {
                    newCursorPos = start + replacement.length;
                } else {
                    applyReplacement(editor, start, end, replacement, newCursorPos);
                    editor.setSelectionRange(start + 1, start + 1 + label('math').length);
                    return;
                }
                break;
            case 'mathBlock': {
                const body = selectedText || label('math');
                replacement = `$$\n${body}\n$$`;
                newCursorPos = start + 3;
                applyReplacement(editor, start, end, replacement, newCursorPos);
                if (!selectedText) {
                    editor.setSelectionRange(start + 3, start + 3 + body.length);
                }
                return;
            }
            case 'mermaid': {
                const body = selectedText || label('mermaid');
                replacement = `\`\`\`mermaid\n${body}\n\`\`\``;
                newCursorPos = start + 12;
                applyReplacement(editor, start, end, replacement, newCursorPos);
                if (!selectedText) {
                    editor.setSelectionRange(start + 12, start + 12 + body.length);
                }
                return;
            }
            default:
                return;
        }

        applyReplacement(editor, start, end, replacement, newCursorPos);
    }

    function insertTable() {
        if (state.locked) return;
        if (state.editorId && window.MarkdownTableEditor && window.MarkdownTableEditor.insertTable(state.editorId)) {
            return;
        }
        const editor = getEditor();
        if (!editor) return;
        const start = editor.selectionStart;
        const end = editor.selectionEnd;
        const col = t('table.column', 'Spalte');
        const row = t('table.row', 'Zeile');
        const tableTemplate =
            '| ' + col + ' 1 | ' + col + ' 2 | ' + col + ' 3 |\n|----------|----------|----------|\n| ' +
            row + ' 1  |  |  |\n| ' + row + ' 2  |  |  |\n';
        applyReplacement(editor, start, end, tableTemplate, start + tableTemplate.length);
    }

    function insertHorizontalRule() {
        if (state.locked) return;
        const editor = getEditor();
        if (!editor) return;
        const start = editor.selectionStart;
        const end = editor.selectionEnd;
        const textBefore = editor.value.substring(0, start);
        const textAfter = editor.value.substring(end);

        let hr = '\n---\n';
        if (textBefore.length > 0 && textBefore[textBefore.length - 1] !== '\n') {
            hr = '\n' + hr;
        }
        if (textAfter.length > 0 && textAfter[0] !== '\n') {
            hr = hr + '\n';
        }

        applyReplacement(editor, start, end, hr, start + hr.length);
    }

    function getSheetEls() {
        return {
            sheet: document.getElementById('markdownToolsSheet'),
            backdrop: document.getElementById('markdownToolsBackdrop'),
            fab: document.getElementById('markdownToolsFab')
        };
    }

    function openSheet() {
        if (state.locked) return;
        const { sheet, backdrop, fab } = getSheetEls();
        if (!sheet || !backdrop) return;
        sheet.classList.add('is-open');
        backdrop.classList.add('is-open');
        sheet.setAttribute('aria-hidden', 'false');
        if (fab) {
            fab.setAttribute('aria-expanded', 'true');
            fab.classList.add('is-open');
        }
        document.body.classList.add('markdown-tools-sheet-open');
    }

    function closeSheet() {
        const { sheet, backdrop, fab } = getSheetEls();
        if (!sheet || !backdrop) return;
        sheet.classList.remove('is-open');
        backdrop.classList.remove('is-open');
        sheet.setAttribute('aria-hidden', 'true');
        if (fab) {
            fab.setAttribute('aria-expanded', 'false');
            fab.classList.remove('is-open');
        }
        document.body.classList.remove('markdown-tools-sheet-open');
        const editor = getEditor();
        if (editor) editor.focus();
    }

    function isSheetOpen() {
        const { sheet } = getSheetEls();
        return !!(sheet && sheet.classList.contains('is-open'));
    }

    function bindSheet() {
        const { sheet, backdrop, fab } = getSheetEls();
        if (!sheet) return;

        if (fab) {
            fab.addEventListener('click', function () {
                if (isSheetOpen()) {
                    closeSheet();
                } else {
                    openSheet();
                }
            });
        }

        if (backdrop) {
            backdrop.addEventListener('click', closeSheet);
        }

        const closeBtn = sheet.querySelector('[data-md-sheet-close]');
        if (closeBtn) {
            closeBtn.addEventListener('click', closeSheet);
        }

        sheet.querySelectorAll('[data-md-action]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const action = btn.getAttribute('data-md-action');
                if (!action) return;
                closeSheet();
                formatText(action);
            });
        });
    }

    function handleEscape() {
        if (isLinkPopoverOpen()) {
            closeLinkPopover();
            return true;
        }
        if (isSheetOpen()) {
            closeSheet();
            return true;
        }
        if (window.MarkdownTableEditor && window.MarkdownTableEditor.closeMenus()) {
            return true;
        }
        hideCaretChip();
        return false;
    }

    function init(options) {
        options = options || {};
        state.editorId = options.editorId || null;
        state.locked = !!options.locked;
        state.labels = Object.assign({}, DEFAULT_LABELS, options.labels || {});
        state.extras = Object.assign({ wikilink: false }, options.extras || {});
        state.i18n = options.i18n || window.MARKDOWN_EDITOR_I18N || {};

        window.formatText = formatText;
        window.insertTable = insertTable;
        window.insertHorizontalRule = insertHorizontalRule;
        window.MarkdownToolbar = api;

        const visualTables = options.visualTables !== false;
        if (visualTables && state.editorId && window.MarkdownTableEditor) {
            window.MarkdownTableEditor.mount(state.editorId, {
                locked: state.locked,
                i18n: state.i18n
            });
        }

        if (!state.locked) {
            bindSheet();
        } else {
            const { fab } = getSheetEls();
            if (fab) fab.style.display = 'none';
        }

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && handleEscape()) {
                e.preventDefault();
                e.stopPropagation();
            }
        }, true);

        document.addEventListener('selectionchange', function () {
            window.clearTimeout(caretChipTimer);
            caretChipTimer = window.setTimeout(updateCaretChip, 120);
        });
        document.addEventListener('click', function (e) {
            if (linkPopoverIgnoreClick) return;
            const pop = document.getElementById('markdownLinkPopover');
            if (!pop || pop.hidden) return;
            if (pop.contains(e.target)) return;
            if (e.target.closest && e.target.closest('[onclick*="link"], [data-md-action="link"], [data-md-caret-edit]')) {
                return;
            }
            closeLinkPopover();
        });
    }

    const api = {
        init: init,
        formatText: formatText,
        insertTable: insertTable,
        insertHorizontalRule: insertHorizontalRule,
        openSheet: openSheet,
        closeSheet: closeSheet,
        handleEscape: handleEscape,
        getEditor: getEditor,
        getContent: function () {
            if (state.editorId && window.MarkdownTableEditor) {
                return window.MarkdownTableEditor.getContent(state.editorId);
            }
            const editor = getSourceEditor();
            return editor ? editor.value : '';
        }
    };

    window.MarkdownToolbar = api;
})(window, document);
