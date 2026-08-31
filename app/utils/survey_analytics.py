"""Analytics and export helpers for surveys."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from statistics import median

from app.models.survey import SurveyQuestion


NUMERIC_TYPES = {'number', 'slider', 'rating_stars'}

PIE_COLORS = (
    '#3b82f6', '#8b5cf6', '#ec4899', '#f97316',
    '#eab308', '#22c55e', '#14b8a6', '#6366f1',
)


def _pie_segments(distribution: list[dict]) -> list[dict]:
    if not distribution:
        return []
    total = sum(item.get('count', 0) for item in distribution) or 1
    segments = []
    cursor = 0.0
    for idx, item in enumerate(distribution):
        share = 100 * item.get('count', 0) / total
        if share <= 0:
            continue
        start = cursor
        end = cursor + share
        segments.append({
            **item,
            'color': PIE_COLORS[idx % len(PIE_COLORS)],
            'start_percent': round(start, 2),
            'end_percent': round(end, 2),
        })
        cursor = end
    if segments and cursor < 100:
        segments[-1]['end_percent'] = 100.0
    return segments


def _answer_values(answers, question_id: int):
    for ans in answers:
        if ans.question_id == question_id:
            if ans.value_json:
                try:
                    return json.loads(ans.value_json)
                except (TypeError, ValueError):
                    pass
            if ans.value_text is not None:
                return ans.value_text
            if ans.file_path:
                return ans.file_path
    return None


def _numeric_values(responses, question_id: int) -> list[float]:
    values = []
    for resp in responses:
        if resp.status != 'submitted':
            continue
        raw = _answer_values(resp.answers, question_id)
        if raw is None or raw == '':
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    return values


def analyze_question(question: SurveyQuestion, responses) -> dict:
    submitted = [r for r in responses if r.status == 'submitted']
    qtype = question.question_type
    result = {
        'question_id': question.id,
        'label': question.label,
        'type': qtype,
        'response_count': len(submitted),
        'answered_count': 0,
    }

    if qtype in ('single_choice', 'multiple_choice'):
        counter = Counter()
        for resp in submitted:
            raw = _answer_values(resp.answers, question.id)
            if raw is None or raw == '':
                continue
            result['answered_count'] += 1
            if isinstance(raw, list):
                for item in raw:
                    counter[str(item)] += 1
            else:
                counter[str(raw)] += 1
        total = sum(counter.values()) or 1
        options = question.get_config().get('options', [])
        option_labels = {str(o.get('id', o.get('label', ''))): o.get('label', '') for o in options}
        distribution = []
        for key, count in counter.most_common():
            label = option_labels.get(key, key)
            distribution.append({
                'value': key,
                'label': label,
                'count': count,
                'percent': round(100 * count / total, 1),
            })
        result['distribution'] = distribution
        result['chart_type'] = 'pie' if qtype == 'single_choice' else 'bar'
        if qtype == 'single_choice':
            segments = _pie_segments(distribution)
            result['pie_segments'] = segments
            result['pie_gradient'] = ', '.join(
                f"{seg['color']} {seg['start_percent']}% {seg['end_percent']}%"
                for seg in segments
            )
        return result

    if qtype in NUMERIC_TYPES:
        nums = _numeric_values(submitted, question.id)
        result['answered_count'] = len(nums)
        if nums:
            result['average'] = round(sum(nums) / len(nums), 2)
            result['median'] = median(nums)
            result['min'] = min(nums)
            result['max'] = max(nums)
        if qtype == 'rating_stars':
            result['chart_type'] = 'stars_avg'
            cfg = question.get_config()
            result['max_stars'] = int(cfg.get('max_stars') or 5)
        elif qtype == 'slider':
            result['chart_type'] = 'slider_avg'
        else:
            result['chart_type'] = 'numeric'
        return result

    if qtype == 'file_upload':
        files = []
        for resp in submitted:
            for ans in resp.answers:
                if ans.question_id == question.id and ans.file_path:
                    result['answered_count'] += 1
                    files.append({
                        'response_id': resp.id,
                        'file_path': ans.file_path,
                        'label': ans.value_text or ans.file_path.split('/')[-1],
                    })
        result['files'] = files
        return result

    texts = []
    for resp in submitted:
        raw = _answer_values(resp.answers, question.id)
        if raw is None or raw == '':
            continue
        result['answered_count'] += 1
        if isinstance(raw, list):
            texts.append('; '.join(str(x) for x in raw))
        else:
            texts.append(str(raw))
    result['text_answers'] = texts[:200]
    return result


def build_survey_summary(survey, responses) -> dict:
    submitted = [r for r in responses if r.status == 'submitted']
    total_started = len(responses)
    total_submitted = len(submitted)
    completion_rate = round(100 * total_submitted / total_started, 1) if total_started else 0
    last_submitted = None
    if submitted:
        last_submitted = max((r.submitted_at for r in submitted if r.submitted_at), default=None)

    questions = survey.all_questions()
    question_stats = [analyze_question(q, responses) for q in questions]

    return {
        'total_started': total_started,
        'total_submitted': total_submitted,
        'completion_rate': completion_rate,
        'last_submitted': last_submitted,
        'question_stats': question_stats,
    }


def export_responses_csv(survey, responses) -> str:
    """Return CSV string for all submitted responses."""
    questions = survey.all_questions()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)

    headers = ['ID', 'E-Mail', 'Eingereicht am', 'Status']
    headers.extend(q.label for q in questions)
    writer.writerow(headers)

    for resp in responses:
        if resp.status != 'submitted':
            continue
        row = [
            resp.id,
            resp.respondent_email or '',
            resp.submitted_at.isoformat() if resp.submitted_at else '',
            resp.status,
        ]
        for q in questions:
            raw = _answer_values(resp.answers, q.id)
            if isinstance(raw, list):
                row.append('; '.join(str(x) for x in raw))
            elif raw is not None:
                row.append(str(raw))
            else:
                row.append('')
        writer.writerow(row)

    return output.getvalue()
