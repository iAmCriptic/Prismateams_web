"""Conditional logic evaluation for surveys."""

from __future__ import annotations

import json
from typing import Any


def _normalize_answer(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def _answer_for_question(answers: dict, question_id: int) -> Any:
    key = str(question_id)
    if key in answers:
        return answers[key]
    if question_id in answers:
        return answers[question_id]
    return None


def _coerce_numeric(value: Any):
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_condition(operator: str, answer: Any, expected: Any) -> bool:
    answer = _normalize_answer(answer)
    if operator == 'is_empty':
        if answer is None:
            return True
        if isinstance(answer, (list, dict)) and not answer:
            return True
        return False
    if operator == 'is_not_empty':
        return not evaluate_condition('is_empty', answer, expected)

    if operator == 'equals':
        if isinstance(answer, list):
            return expected in answer
        return str(answer) == str(expected)
    if operator == 'not_equals':
        return not evaluate_condition('equals', answer, expected)
    if operator == 'contains':
        if answer is None:
            return False
        if isinstance(answer, list):
            return any(str(expected) in str(item) for item in answer)
        return str(expected) in str(answer)
    if operator == 'one_of':
        options = expected if isinstance(expected, list) else [expected]
        if isinstance(answer, list):
            return any(str(item) in [str(o) for o in options] for item in answer)
        return str(answer) in [str(o) for o in options]
    if operator == 'greater_than':
        a_num = _coerce_numeric(answer)
        e_num = _coerce_numeric(expected)
        return a_num is not None and e_num is not None and a_num > e_num
    if operator == 'less_than':
        a_num = _coerce_numeric(answer)
        e_num = _coerce_numeric(expected)
        return a_num is not None and e_num is not None and a_num < e_num
    return False


def evaluate_rules(survey, answers: dict | None = None) -> dict:
    """
    Evaluate logic rules for a survey.

    Returns dict with:
      - hidden_page_ids: set
      - hidden_question_ids: set
      - goto_page_map: {source_page_id: target_page_id}
      - skip_page_ids: set
    """
    answers = answers or {}
    hidden_pages: set[int] = set()
    hidden_questions: set[int] = set()
    goto_page_map: dict[int, int] = {}
    skip_pages: set[int] = set()

    rules = sorted(survey.logic_rules or [], key=lambda r: r.rule_order)
    for rule in rules:
        answer = _answer_for_question(answers, rule.source_question_id)
        expected = rule.get_value()
        if not evaluate_condition(rule.operator, answer, expected):
            continue

        if rule.action == 'goto_page' and rule.target_page_id:
            source_page_id = None
            if rule.source_question and rule.source_question.page_id:
                source_page_id = rule.source_question.page_id
            if source_page_id:
                goto_page_map[source_page_id] = rule.target_page_id
        elif rule.action == 'skip_page' and rule.target_page_id:
            skip_pages.add(rule.target_page_id)
        elif rule.action == 'hide_question' and rule.target_question_id:
            hidden_questions.add(rule.target_question_id)
        elif rule.action == 'show_question' and rule.target_question_id:
            hidden_questions.discard(rule.target_question_id)

    return {
        'hidden_page_ids': hidden_pages | skip_pages,
        'hidden_question_ids': hidden_questions,
        'goto_page_map': goto_page_map,
        'skip_page_ids': skip_pages,
    }


def get_visible_pages(survey, answers: dict | None = None) -> list:
    """Return ordered visible pages based on logic rules."""
    answers = answers or {}
    logic = evaluate_rules(survey, answers)
    hidden = logic['hidden_page_ids']
    pages = [p for p in survey.pages if p.id not in hidden]
    return pages


def get_visible_questions(page, answers: dict | None = None, survey=None) -> list:
    """Return ordered visible questions on a page."""
    if survey is None and page.survey:
        survey = page.survey
    logic = evaluate_rules(survey, answers or {}) if survey else {'hidden_question_ids': set()}
    hidden = logic['hidden_question_ids']
    return [q for q in page.questions if q.id not in hidden]


def get_next_page_id(survey, current_page_id: int, answers: dict | None = None) -> int | None:
    """Determine next page after current_page_id respecting goto rules."""
    logic = evaluate_rules(survey, answers or {})
    goto = logic['goto_page_map']
    if current_page_id in goto:
        return goto[current_page_id]

    visible = get_visible_pages(survey, answers)
    page_ids = [p.id for p in visible]
    if current_page_id not in page_ids:
        return page_ids[0] if page_ids else None
    idx = page_ids.index(current_page_id)
    if idx + 1 < len(page_ids):
        return page_ids[idx + 1]
    return None


def build_logic_payload(survey) -> list[dict]:
    """Serialize logic rules for client-side evaluation."""
    payload = []
    for rule in survey.logic_rules or []:
        payload.append({
            'id': rule.id,
            'source_question_id': rule.source_question_id,
            'operator': rule.operator,
            'value': rule.get_value(),
            'action': rule.action,
            'target_page_id': rule.target_page_id,
            'target_question_id': rule.target_question_id,
            'rule_order': rule.rule_order,
        })
    return payload


def answers_from_request(form_data, files, questions) -> dict:
    """Parse answers from multipart/form request."""
    answers: dict[str, Any] = {}
    for question in questions:
        qid = str(question.id)
        qtype = question.question_type
        if qtype == 'multiple_choice':
            answers[qid] = form_data.getlist(f'q_{question.id}')
        elif qtype == 'file_upload':
            f = files.get(f'q_{question.id}')
            if f and f.filename:
                answers[qid] = f.filename
        else:
            val = form_data.get(f'q_{question.id}')
            if val is not None:
                answers[qid] = val
    return answers


def validate_required_answers(survey, answers: dict) -> list[str]:
    """Return list of validation error messages for missing required fields."""
    errors = []
    for page in get_visible_pages(survey, answers):
        for question in get_visible_questions(page, answers, survey):
            if not question.is_required:
                continue
            val = _answer_for_question(answers, question.id)
            if val is None or val == '' or (isinstance(val, list) and not val):
                errors.append(question.label or f'Frage {question.id}')
    return errors
