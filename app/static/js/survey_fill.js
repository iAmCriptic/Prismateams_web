(function () {
    'use strict';

    document.querySelectorAll('.survey-star-rating').forEach((wrap) => {
        const stars = wrap.querySelectorAll('.survey-star');
        stars.forEach((star, idx) => {
            star.addEventListener('click', () => {
                const input = star.querySelector('input');
                if (input) input.checked = true;
                stars.forEach((s, i) => {
                    const icon = s.querySelector('i');
                    if (icon) {
                        icon.classList.toggle('bi-star-fill', i <= idx);
                        icon.classList.toggle('bi-star', i > idx);
                    }
                });
                applyLogic();
            });
        });
    });

    const logicEl = document.getElementById('surveyLogicData');
    const rules = logicEl ? JSON.parse(logicEl.textContent || '[]') : [];

    function getAnswers() {
        const answers = {};
        document.querySelectorAll('.survey-public-question').forEach((block) => {
            const qid = block.dataset.questionId;
            const type = block.dataset.questionType;
            if (type === 'multiple_choice') {
                answers[qid] = Array.from(block.querySelectorAll('input:checked')).map((i) => i.value);
            } else if (type === 'single_choice' || type === 'rating_stars') {
                const checked = block.querySelector('input:checked');
                answers[qid] = checked ? checked.value : '';
            } else {
                const input = block.querySelector('input, textarea, select');
                answers[qid] = input ? input.value : '';
            }
        });
        return answers;
    }

    function evaluate(operator, answer, expected) {
        const empty = answer === null || answer === undefined || answer === '' || (Array.isArray(answer) && !answer.length);
        if (operator === 'is_empty') return empty;
        if (operator === 'is_not_empty') return !empty;
        if (operator === 'equals') return String(answer) === String(expected);
        if (operator === 'not_equals') return String(answer) !== String(expected);
        if (operator === 'contains') return String(answer).includes(String(expected));
        return false;
    }

    function applyLogic() {
        if (!rules.length) return;
        const answers = getAnswers();
        const hiddenQuestions = new Set();
        const hiddenPages = new Set();

        rules.forEach((rule) => {
            const ans = answers[String(rule.source_question_id)];
            if (!evaluate(rule.operator, ans, rule.value)) return;
            if (rule.action === 'hide_question' && rule.target_question_id) {
                hiddenQuestions.add(String(rule.target_question_id));
            }
            if (rule.action === 'show_question' && rule.target_question_id) {
                hiddenQuestions.delete(String(rule.target_question_id));
            }
            if (rule.action === 'skip_page' && rule.target_page_id) {
                hiddenPages.add(String(rule.target_page_id));
            }
        });

        document.querySelectorAll('.survey-public-page').forEach((page) => {
            const pid = page.dataset.pageId;
            page.style.display = hiddenPages.has(pid) ? 'none' : '';
        });
        document.querySelectorAll('.survey-public-question').forEach((q) => {
            const qid = q.dataset.questionId;
            if (hiddenQuestions.has(qid)) {
                q.style.display = 'none';
                q.querySelectorAll('[required]').forEach((el) => el.removeAttribute('required'));
            } else {
                q.style.display = '';
            }
        });
    }

    document.getElementById('surveyFillForm')?.addEventListener('input', applyLogic);
    document.getElementById('surveyFillForm')?.addEventListener('change', applyLogic);
    applyLogic();
})();
