(function () {
    'use strict';

    const TYPE_LABELS = {
        short_text: 'Kurztext',
        long_text: 'Langtext',
        number: 'Zahl',
        slider: 'Slider',
        single_choice: 'Single Choice',
        multiple_choice: 'Multiple Choice',
        rating_stars: '5 Sterne',
        file_upload: 'Dateiupload',
        date: 'Datum',
        time: 'Uhrzeit',
        url: 'Link',
        email: 'E-Mail',
    };

    const root = document.getElementById('surveyBuilder');
    if (!root) return;

    const dataEl = document.getElementById('surveyStructureData');
    let structure = JSON.parse(dataEl.textContent || '{}');
    let saveTimer = null;
    let tempIdCounter = -1;

    const els = {
        pages: document.getElementById('surveyPagesContainer'),
        title: document.getElementById('surveyTitleInput'),
        desc: document.getElementById('surveyDescInput'),
        addPage: document.getElementById('surveyAddPageBtn'),
        addMenu: document.getElementById('surveyAddQuestionMenu'),
        saveStatus: document.getElementById('surveySaveStatus'),
        layoutMode: document.getElementById('settingLayoutMode'),
        requireEmail: document.getElementById('settingRequireEmail'),
        onePerEmail: document.getElementById('settingOnePerEmail'),
        allowEdit: document.getElementById('settingAllowEdit'),
        progressBar: document.getElementById('settingProgressBar'),
        shuffle: document.getElementById('settingShuffle'),
        confirmMsg: document.getElementById('settingConfirmMsg'),
        anotherLink: document.getElementById('settingAnotherLink'),
        disableAutosave: document.getElementById('settingDisableAutosave'),
        publicFill: document.getElementById('settingPublicFill'),
        publicLink: document.getElementById('publicLinkInput'),
        publicLinkGroup: document.getElementById('publicLinkGroup'),
        copyLink: document.getElementById('copyPublicLinkBtn'),
        headerInput: document.getElementById('surveyHeaderInput'),
    };

    function tempId() {
        return tempIdCounter--;
    }

    function defaultConfig(type) {
        if (type === 'slider') return { min: 0, max: 100, step: 1 };
        if (type === 'rating_stars') return { max_stars: 5 };
        if (type === 'single_choice' || type === 'multiple_choice') {
            return { options: [{ id: '1', label: 'Option 1' }, { id: '2', label: 'Option 2' }] };
        }
        if (type === 'file_upload') return { allowed_extensions: ['pdf', 'png', 'jpg', 'jpeg'], max_size_mb: 10 };
        return {};
    }

    function syncSettingsFromStructure() {
        const s = structure.settings || {};
        if (els.layoutMode) els.layoutMode.value = structure.layout_mode || 'scroll';
        if (els.requireEmail) els.requireEmail.checked = !!s.require_email_verification;
        if (els.onePerEmail) els.onePerEmail.checked = !!s.one_response_per_email;
        if (els.allowEdit) els.allowEdit.checked = !!s.allow_edit_response;
        if (els.progressBar) els.progressBar.checked = s.show_progress_bar !== false;
        if (els.shuffle) els.shuffle.checked = !!s.shuffle_questions;
        if (els.confirmMsg) els.confirmMsg.value = s.confirmation_message || '';
        if (els.anotherLink) els.anotherLink.checked = s.show_submit_another_link !== false;
        if (els.disableAutosave) els.disableAutosave.checked = !!s.disable_autosave;
    }

    function syncStructureFromSettings() {
        structure.layout_mode = els.layoutMode ? els.layoutMode.value : 'scroll';
        structure.settings = {
            require_email_verification: els.requireEmail?.checked || false,
            one_response_per_email: els.onePerEmail?.checked || false,
            allow_edit_response: els.allowEdit?.checked || false,
            show_progress_bar: els.progressBar?.checked !== false,
            shuffle_questions: els.shuffle?.checked || false,
            confirmation_message: els.confirmMsg?.value || 'Ihre Antwort wurde gespeichert.',
            show_submit_another_link: els.anotherLink?.checked !== false,
            disable_autosave: els.disableAutosave?.checked || false,
        };
    }

    function renderAddMenu() {
        if (!els.addMenu) return;
        els.addMenu.innerHTML = '';
        (structure.question_types || Object.keys(TYPE_LABELS)).forEach((type) => {
            const li = document.createElement('li');
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'dropdown-item';
            btn.textContent = TYPE_LABELS[type] || type;
            btn.addEventListener('click', () => addQuestion(type));
            li.appendChild(btn);
            els.addMenu.appendChild(li);
        });
    }

    function renderPages() {
        if (!els.pages) return;
        els.pages.innerHTML = '';
        (structure.pages || []).forEach((page, pIdx) => {
            const pageEl = document.createElement('div');
            pageEl.className = 'surveys-page-card';
            pageEl.dataset.pageId = page.id;
            pageEl.draggable = true;

            const header = document.createElement('div');
            header.className = 'd-flex align-items-center gap-2 mb-2';
            header.innerHTML = `<span class="text-muted small">Seite ${pIdx + 1}</span>`;
            const titleInput = document.createElement('input');
            titleInput.type = 'text';
            titleInput.className = 'form-control form-control-sm';
            titleInput.value = page.title || '';
            titleInput.placeholder = 'Seitentitel';
            titleInput.addEventListener('input', () => { page.title = titleInput.value; scheduleSave(); });
            header.appendChild(titleInput);
            pageEl.appendChild(header);

            const qList = document.createElement('div');
            qList.className = 'surveys-questions-list';
            (page.questions || []).forEach((q, qIdx) => {
                qList.appendChild(renderQuestionCard(page, q, qIdx));
            });
            pageEl.appendChild(qList);
            els.pages.appendChild(pageEl);
        });
        bindDnD();
    }

    function renderQuestionCard(page, q, qIdx) {
        const card = document.createElement('div');
        card.className = 'surveys-question-card';
        card.draggable = true;
        card.dataset.questionId = q.id;
        card.dataset.pageId = page.id;

        const top = document.createElement('div');
        top.className = 'd-flex align-items-center justify-content-between gap-2 mb-2';
        top.innerHTML = `<span class="surveys-question-type-badge">${TYPE_LABELS[q.question_type] || q.question_type}</span>`;
        const delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.className = 'btn btn-sm btn-link text-danger p-0';
        delBtn.innerHTML = '<i class="bi bi-trash"></i>';
        delBtn.addEventListener('click', () => {
            page.questions = page.questions.filter((x) => x.id !== q.id);
            renderPages();
            scheduleSave();
        });
        top.appendChild(delBtn);
        card.appendChild(top);

        const label = document.createElement('input');
        label.type = 'text';
        label.className = 'form-control form-control-sm mb-2';
        label.value = q.label || '';
        label.placeholder = 'Fragentitel';
        label.addEventListener('input', () => { q.label = label.value; scheduleSave(); });
        card.appendChild(label);

        const reqWrap = document.createElement('div');
        reqWrap.className = 'form-check form-switch surveys-pill-switch';
        reqWrap.innerHTML = `<input class="form-check-input" type="checkbox" id="req_${q.id}"><label class="form-check-label" for="req_${q.id}">Pflichtfeld</label>`;
        const reqInput = reqWrap.querySelector('input');
        reqInput.checked = !!q.is_required;
        reqInput.addEventListener('change', () => { q.is_required = reqInput.checked; scheduleSave(); });
        card.appendChild(reqWrap);

        if (q.question_type === 'single_choice' || q.question_type === 'multiple_choice') {
            card.appendChild(renderOptionsEditor(q));
        }
        if (q.question_type === 'slider') {
            card.appendChild(renderSliderConfig(q));
        }

        return card;
    }

    function renderOptionsEditor(q) {
        const wrap = document.createElement('div');
        wrap.className = 'mt-2';
        if (!q.config) q.config = defaultConfig(q.question_type);
        if (!q.config.options) q.config.options = [];
        q.config.options.forEach((opt, idx) => {
            const row = document.createElement('div');
            row.className = 'input-group input-group-sm mb-1';
            const inp = document.createElement('input');
            inp.type = 'text';
            inp.className = 'form-control';
            inp.value = opt.label || '';
            inp.addEventListener('input', () => { opt.label = inp.value; opt.id = opt.id || String(idx + 1); scheduleSave(); });
            row.appendChild(inp);
            wrap.appendChild(row);
        });
        const addOpt = document.createElement('button');
        addOpt.type = 'button';
        addOpt.className = 'btn btn-sm btn-outline-secondary surveys-btn-pill mt-1';
        addOpt.textContent = '+ Option';
        addOpt.addEventListener('click', () => {
            q.config.options.push({ id: String(q.config.options.length + 1), label: `Option ${q.config.options.length + 1}` });
            renderPages();
            scheduleSave();
        });
        wrap.appendChild(addOpt);
        return wrap;
    }

    function renderSliderConfig(q) {
        if (!q.config) q.config = defaultConfig('slider');
        const wrap = document.createElement('div');
        wrap.className = 'row g-2 mt-2';
        ['min', 'max', 'step'].forEach((key) => {
            const col = document.createElement('div');
            col.className = 'col-4';
            col.innerHTML = `<label class="form-label small">${key}</label><input type="number" class="form-control form-control-sm" data-key="${key}" value="${q.config[key] ?? ''}">`;
            col.querySelector('input').addEventListener('input', (e) => {
                q.config[key] = e.target.value === '' ? null : Number(e.target.value);
                scheduleSave();
            });
            wrap.appendChild(col);
        });
        return wrap;
    }

    function addQuestion(type) {
        if (!structure.pages || !structure.pages.length) {
            structure.pages = [{ id: tempId(), title: 'Seite 1', page_order: 0, questions: [] }];
        }
        const page = structure.pages[structure.pages.length - 1];
        page.questions = page.questions || [];
        page.questions.push({
            id: tempId(),
            question_type: type,
            label: 'Neue Frage',
            description: '',
            is_required: false,
            question_order: page.questions.length,
            config: defaultConfig(type),
        });
        renderPages();
        scheduleSave();
    }

    function addPage() {
        structure.pages = structure.pages || [];
        structure.pages.push({
            id: tempId(),
            title: `Seite ${structure.pages.length + 1}`,
            description: '',
            page_order: structure.pages.length,
            questions: [],
        });
        renderPages();
        scheduleSave();
    }

    function bindDnD() {
        let dragged = null;
        document.querySelectorAll('.surveys-question-card').forEach((card) => {
            card.addEventListener('dragstart', (e) => {
                dragged = card;
                card.classList.add('is-dragging');
            });
            card.addEventListener('dragend', () => {
                card.classList.remove('is-dragging');
                dragged = null;
            });
            card.addEventListener('dragover', (e) => {
                e.preventDefault();
                card.classList.add('drag-over');
            });
            card.addEventListener('dragleave', () => card.classList.remove('drag-over'));
            card.addEventListener('drop', (e) => {
                e.preventDefault();
                card.classList.remove('drag-over');
                if (!dragged || dragged === card) return;
                reorderQuestions(dragged, card);
            });
        });
    }

    function reorderQuestions(fromCard, toCard) {
        const fromPageId = Number(fromCard.dataset.pageId);
        const toPageId = Number(toCard.dataset.pageId);
        const fromQId = Number(fromCard.dataset.questionId);
        const toQId = Number(toCard.dataset.questionId);
        const fromPage = structure.pages.find((p) => p.id === fromPageId);
        const toPage = structure.pages.find((p) => p.id === toPageId);
        if (!fromPage || !toPage) return;
        const fromIdx = fromPage.questions.findIndex((q) => q.id === fromQId);
        const [moved] = fromPage.questions.splice(fromIdx, 1);
        const toIdx = toPage.questions.findIndex((q) => q.id === toQId);
        toPage.questions.splice(toIdx, 0, moved);
        fromPage.questions.forEach((q, i) => { q.question_order = i; });
        toPage.questions.forEach((q, i) => { q.question_order = i; });
        renderPages();
        scheduleSave();
    }

    function scheduleSave() {
        if (els.saveStatus) els.saveStatus.textContent = 'Speichern…';
        clearTimeout(saveTimer);
        saveTimer = setTimeout(saveStructure, 800);
    }

    function saveStructure() {
        structure.title = els.title?.value || structure.title;
        structure.description = els.desc?.value || '';
        syncStructureFromSettings();
        fetch(root.dataset.structureUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(structure),
        })
            .then((r) => r.json())
            .then((data) => {
                if (data.ok && data.structure) {
                    structure = data.structure;
                    if (els.saveStatus) els.saveStatus.textContent = 'Gespeichert';
                    setTimeout(() => { if (els.saveStatus) els.saveStatus.textContent = ''; }, 2000);
                } else if (els.saveStatus) {
                    els.saveStatus.textContent = 'Fehler beim Speichern';
                }
            })
            .catch(() => {
                if (els.saveStatus) els.saveStatus.textContent = 'Fehler beim Speichern';
            });
    }

    function bindSettings() {
        [els.title, els.desc, els.layoutMode, els.requireEmail, els.onePerEmail, els.allowEdit,
            els.progressBar, els.shuffle, els.confirmMsg, els.anotherLink, els.disableAutosave].forEach((el) => {
            if (!el) return;
            el.addEventListener('input', scheduleSave);
            el.addEventListener('change', scheduleSave);
        });

        if (els.addPage) els.addPage.addEventListener('click', addPage);

        if (els.publicFill) {
            els.publicFill.addEventListener('change', () => togglePublicFill(els.publicFill.checked));
        }

        const shareModalFill = document.getElementById('shareModalPublicFill');
        if (shareModalFill) {
            shareModalFill.addEventListener('change', () => togglePublicFill(shareModalFill.checked));
        }

        const shareCopy = document.getElementById('shareModalCopyBtn');
        if (shareCopy) {
            shareCopy.addEventListener('click', () => {
                const inp = document.getElementById('shareModalLinkInput');
                if (inp) navigator.clipboard.writeText(inp.value);
            });
        }

        function setPublicFillUI(active) {
            if (els.publicFill) els.publicFill.checked = active;
            if (shareModalFill) shareModalFill.checked = active;
            if (els.publicLinkGroup) els.publicLinkGroup.style.display = active ? '' : 'none';
            if (els.publicLink) els.publicLink.value = active ? (els.publicLink.value || '') : '';
            const shareGroup = document.getElementById('shareModalLinkGroup');
            const shareInput = document.getElementById('shareModalLinkInput');
            if (shareGroup) shareGroup.style.display = active ? '' : 'none';
            if (shareInput) shareInput.value = active ? (shareInput.value || '') : '';
        }

        function togglePublicFill(desiredActive) {
            fetch(root.dataset.togglePublicUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: desiredActive }),
            })
                .then((r) => r.json())
                .then((data) => {
                    if (!data.ok) {
                        setPublicFillUI(!desiredActive);
                        return;
                    }
                    const active = !!data.is_publicly_fillable;
                    setPublicFillUI(active);
                    if (els.publicLink) els.publicLink.value = data.public_url || '';
                    const shareInput = document.getElementById('shareModalLinkInput');
                    if (shareInput) shareInput.value = data.public_url || '';
                })
                .catch(() => setPublicFillUI(!desiredActive));
        }

        if (els.copyLink) {
            els.copyLink.addEventListener('click', () => {
                if (els.publicLink) {
                    navigator.clipboard.writeText(els.publicLink.value);
                }
            });
        }

        if (els.headerInput) {
            els.headerInput.addEventListener('change', () => {
                const file = els.headerInput.files[0];
                if (!file) return;
                const fd = new FormData();
                fd.append('header_image', file);
                fetch(root.dataset.headerUrl, { method: 'POST', body: fd })
                    .then((r) => r.json())
                    .then((data) => {
                        if (data.ok) {
                            const preview = document.getElementById('surveyHeaderPreview');
                            if (preview) {
                                const img = document.createElement('img');
                                img.src = data.url + '?t=' + Date.now();
                                img.className = 'surveys-header-image';
                                img.id = 'surveyHeaderPreview';
                                preview.replaceWith(img);
                            }
                        }
                    });
            });
        }

        renderLogicRules();
        const addLogicBtn = document.getElementById('surveyAddLogicBtn');
        if (addLogicBtn) {
            addLogicBtn.addEventListener('click', () => {
                structure.logic_rules = structure.logic_rules || [];
                const questions = [];
                (structure.pages || []).forEach((p) => (p.questions || []).forEach((q) => questions.push(q)));
                if (!questions.length) return;
                structure.logic_rules.push({
                    id: tempId(),
                    source_question_id: questions[0].id,
                    operator: 'equals',
                    value: '',
                    action: 'goto_page',
                    target_page_id: structure.pages[0]?.id,
                    target_question_id: null,
                    rule_order: structure.logic_rules.length,
                });
                renderLogicRules();
                scheduleSave();
            });
        }
    }

    function allQuestions() {
        const list = [];
        (structure.pages || []).forEach((p) => (p.questions || []).forEach((q) => list.push({ ...q, page_id: p.id })));
        return list;
    }

    function renderLogicRules() {
        const container = document.getElementById('surveyLogicRules');
        if (!container) return;
        container.innerHTML = '';
        structure.logic_rules = structure.logic_rules || [];
        structure.logic_rules.forEach((rule, idx) => {
            const row = document.createElement('div');
            row.className = 'border rounded p-2 mb-2 small surveys-logic-rule';
            const questions = allQuestions();
            const qOpts = questions.map((q) => `<option value="${q.id}" ${q.id === rule.source_question_id ? 'selected' : ''}>${q.label || 'Frage'}</option>`).join('');
            const pageOpts = (structure.pages || []).map((p) => `<option value="${p.id}" ${p.id === rule.target_page_id ? 'selected' : ''}>${p.title || 'Seite'}</option>`).join('');
            row.innerHTML = `
                <div class="mb-1 fw-semibold">Regel ${idx + 1}</div>
                <select class="form-select form-select-sm mb-1 logic-src" data-inv-pill-select>${qOpts}</select>
                <select class="form-select form-select-sm mb-1 logic-op" data-inv-pill-select>
                    <option value="equals" ${rule.operator === 'equals' ? 'selected' : ''}>=</option>
                    <option value="not_equals" ${rule.operator === 'not_equals' ? 'selected' : ''}>≠</option>
                    <option value="contains" ${rule.operator === 'contains' ? 'selected' : ''}>enthält</option>
                    <option value="is_empty" ${rule.operator === 'is_empty' ? 'selected' : ''}>leer</option>
                    <option value="is_not_empty" ${rule.operator === 'is_not_empty' ? 'selected' : ''}>nicht leer</option>
                </select>
                <input type="text" class="form-control form-control-sm mb-1 logic-val" value="${rule.value || ''}" placeholder="Wert">
                <select class="form-select form-select-sm mb-1 logic-action" data-inv-pill-select>
                    <option value="goto_page" ${rule.action === 'goto_page' ? 'selected' : ''}>Gehe zu Seite</option>
                    <option value="skip_page" ${rule.action === 'skip_page' ? 'selected' : ''}>Seite überspringen</option>
                    <option value="hide_question" ${rule.action === 'hide_question' ? 'selected' : ''}>Frage ausblenden</option>
                    <option value="show_question" ${rule.action === 'show_question' ? 'selected' : ''}>Frage anzeigen</option>
                </select>
                <select class="form-select form-select-sm mb-1 logic-page" data-inv-pill-select>${pageOpts}</select>
                <button type="button" class="btn btn-sm btn-link text-danger p-0 logic-del">Entfernen</button>
            `;
            row.querySelector('.logic-src').addEventListener('change', (e) => { rule.source_question_id = Number(e.target.value); scheduleSave(); });
            row.querySelector('.logic-op').addEventListener('change', (e) => { rule.operator = e.target.value; scheduleSave(); });
            row.querySelector('.logic-val').addEventListener('input', (e) => { rule.value = e.target.value; scheduleSave(); });
            row.querySelector('.logic-action').addEventListener('change', (e) => { rule.action = e.target.value; scheduleSave(); });
            row.querySelector('.logic-page').addEventListener('change', (e) => { rule.target_page_id = Number(e.target.value); scheduleSave(); });
            row.querySelector('.logic-del').addEventListener('click', () => {
                structure.logic_rules.splice(idx, 1);
                renderLogicRules();
                scheduleSave();
            });
            container.appendChild(row);
        });
        if (window.InventoryPillSelect) {
            window.InventoryPillSelect.enhanceAll(container);
        }
    }

    if (!structure.pages || !structure.pages.length) {
        structure.pages = [{ id: tempId(), title: 'Seite 1', page_order: 0, questions: [] }];
    }

    syncSettingsFromStructure();
    renderAddMenu();
    renderPages();
    bindSettings();
    if (window.InventoryPillSelect) {
        const panel = document.getElementById('surveySettingsPanel');
        if (panel) window.InventoryPillSelect.enhanceAll(panel);
    }
})();
