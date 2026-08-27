/**
 * Shared Markdown editor toolbar: formatting + mobile overflow sheet.
 */
(function (window) {
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

    let state = {
        editorId: null,
        locked: false,
        labels: Object.assign({}, DEFAULT_LABELS),
        extras: { wikilink: false }
    };

    function getEditor() {
        if (!state.editorId) return null;
        return document.getElementById(state.editorId);
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
        editor.dispatchEvent(new Event('input'));
    }

    function formatText(type) {
        if (state.locked) return;
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
            case 'link':
                replacement = `[${selectedText || label('link_text')}](URL)`;
                newCursorPos = start + replacement.length - 4;
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
                    newCursorPos = start + 1;
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
            case 'table':
                insertTable();
                return;
            case 'hr':
                insertHorizontalRule();
                return;
            default:
                return;
        }

        applyReplacement(editor, start, end, replacement, newCursorPos);
    }

    function insertTable() {
        if (state.locked) return;
        const editor = getEditor();
        if (!editor) return;
        const start = editor.selectionStart;
        const end = editor.selectionEnd;
        const tableTemplate =
            '| Spalte 1 | Spalte 2 |\n|----------|----------|\n| Zeile 1  | Zeile 1  |\n| Zeile 2  | Zeile 2  |\n';
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

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && isSheetOpen()) {
                e.preventDefault();
                e.stopPropagation();
                closeSheet();
            }
        });
    }

    function init(options) {
        options = options || {};
        state.editorId = options.editorId || null;
        state.locked = !!options.locked;
        state.labels = Object.assign({}, DEFAULT_LABELS, options.labels || {});
        state.extras = Object.assign({ wikilink: false }, options.extras || {});

        // Global aliases for inline onclick handlers in templates
        window.formatText = formatText;
        window.insertTable = insertTable;
        window.insertHorizontalRule = insertHorizontalRule;
        window.MarkdownToolbar = api;

        if (!state.locked) {
            bindSheet();
        } else {
            const { fab } = getSheetEls();
            if (fab) fab.style.display = 'none';
        }
    }

    const api = {
        init: init,
        formatText: formatText,
        insertTable: insertTable,
        insertHorizontalRule: insertHorizontalRule,
        openSheet: openSheet,
        closeSheet: closeSheet
    };

    window.MarkdownToolbar = api;
})(window);
