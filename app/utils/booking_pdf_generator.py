"""PDF-Generator für Buchungsanfragen — Portal-Standardlayout."""

from __future__ import annotations

import re
from datetime import datetime
from io import BytesIO

from flask import current_app
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, Spacer, Table, TableStyle

from app.utils.pdf_generator import (
    build_standard_header,
    build_standard_pdf,
    pdf_paragraph_styles,
    standard_table_style,
)


def _applicant_display_name(booking_request) -> str:
    if booking_request.applicant_name:
        return booking_request.applicant_name
    email = booking_request.email or ''
    if '@' in email:
        return email.split('@', 1)[0]
    return email


def _build_time_range(booking_request) -> str:
    if not booking_request.event_date:
        return ''
    date_str = booking_request.event_date.strftime('%d.%m.%Y')
    if booking_request.event_start_time and booking_request.event_end_time:
        return (
            f"{date_str} von {booking_request.event_start_time.strftime('%H:%M')} Uhr "
            f"bis {booking_request.event_end_time.strftime('%H:%M')} Uhr"
        )
    if booking_request.event_start_time:
        return f"{date_str} ab {booking_request.event_start_time.strftime('%H:%M')} Uhr"
    return date_str


def _role_approver_name(booking_request, role) -> str:
    for appr in booking_request.approvals:
        if appr.role_id != role.id:
            continue
        if appr.status in {'approved', 'rejected'} and appr.approver:
            return appr.approver.full_name
    return ''


def _status_text(booking_request, roles) -> tuple[str, bool]:
    is_rejected = False
    for role in roles:
        for appr in booking_request.approvals:
            if appr.role_id == role.id and appr.status == 'rejected':
                is_rejected = True
                break
        if is_rejected:
            break

    if is_rejected:
        return 'Abgelehnt', True
    if booking_request.status == 'accepted':
        return 'Angenommen', False
    return 'Ausstehend', False


def _apply_placeholders(text: str, booking_request) -> str:
    form = booking_request.form
    roles = sorted(form.roles, key=lambda r: r.role_order)
    applicant_name = _applicant_display_name(booking_request)
    applicant_email = booking_request.email or ''
    status_text, is_rejected = _status_text(booking_request, roles)
    time_range = _build_time_range(booking_request)
    event_name = booking_request.event_name or ''

    replacements = {
        '{applicant_name}': applicant_name,
        '{name}': applicant_name,
        '{applicant}': applicant_name,
        '{applicant_email}': applicant_email,
        '{email}': applicant_email,
        '{event_name}': event_name,
        '{time_range}': time_range,
        '{status}': status_text,
        '{approved}': 'Angenommen' if booking_request.status == 'accepted' else 'Nicht angenommen',
        '{rejected}': 'Abgelehnt' if is_rejected else 'Nicht abgelehnt',
    }

    for idx, role in enumerate(roles, start=1):
        role_text = _role_approver_name(booking_request, role)
        for key in (
            f'{{role_{idx}}}',
            f'{{Role_{idx}}}',
            f'{{ROLE_{idx}}}',
            f'{{role {idx}}}',
            f'{{Role {idx}}}',
            f'{{ROLE {idx}}}',
            f'{{role{idx}}}',
            f'{{Role{idx}}}',
            f'{{ROLE{idx}}}',
        ):
            replacements[key] = role_text

    result = text
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, str(value))

    for idx, role in enumerate(roles, start=1):
        role_text = _role_approver_name(booking_request, role)
        pattern = rf'\{{[Rr][Oo][Ll][Ee][_\s]*{idx}\}}'
        result = re.sub(pattern, role_text, result)

    return result


def _secondary_logo_flowable(path: str, size=2.0 * cm):
    if not path:
        return None
    try:
        return Image(path, width=size, height=size, kind='proportional')
    except Exception as exc:
        current_app.logger.warning(f'Konnte optionales 2. Logo nicht laden: {exc}')
        return None


def _field_values_table(booking_request, usable_width: float):
    rows = [['Feld', 'Wert']]
    for fv in booking_request.field_values:
        label = fv.field.field_label if fv.field else f'Feld #{fv.field_id}'
        value = fv.field_value or ''
        rows.append([str(label), str(value)])
    if len(rows) <= 1:
        return None
    col1 = usable_width * 0.35
    col2 = usable_width * 0.65
    table = Table(rows, colWidths=[col1, col2])
    table.setStyle(standard_table_style(header=True))
    return table


def generate_booking_request_pdf(booking_request, output=None):
    """
    Generiert ein PDF für eine Buchungsanfrage im Portal-Standardstil.

    Args:
        booking_request: BookingRequest Objekt
        output: BytesIO Objekt oder Dateipfad (optional)

    Returns:
        BytesIO Objekt mit PDF-Daten (falls output=None)
    """
    if output is None:
        output = BytesIO()

    usable_width = A4[0] - 4 * cm
    form = booking_request.form
    story = []

    header = build_standard_header(
        form.title,
        subtitle=booking_request.event_name or None,
        pagesize=A4,
        content_width=usable_width,
    )
    secondary = _secondary_logo_flowable(getattr(form, 'secondary_logo_path', None))
    if secondary:
        logo_col = 2.6 * cm
        header_with_second = Table(
            [[header, secondary]],
            colWidths=[usable_width - logo_col, logo_col],
        )
        header_with_second.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(header_with_second)
    else:
        story.append(header)

    story.append(Spacer(1, 0.45 * cm))

    ps = pdf_paragraph_styles()
    meta_style = ParagraphStyle(
        'BookingMeta',
        parent=ps['muted'],
        fontSize=10,
        spaceAfter=4,
    )
    story.append(Paragraph(
        f"Antragsteller: {_applicant_display_name(booking_request)} · {booking_request.email or '—'}",
        meta_style,
    ))
    time_range = _build_time_range(booking_request)
    if time_range:
        story.append(Paragraph(f"Zeitraum: {time_range}", meta_style))
    story.append(Spacer(1, 0.35 * cm))

    if form.pdf_application_text:
        pdf_text = _apply_placeholders(form.pdf_application_text, booking_request)
        pdf_text = pdf_text.replace('\n', '<br/>')
        text_style = ParagraphStyle(
            'BookingPdfText',
            parent=ps['body'],
            fontSize=11,
            alignment=TA_LEFT,
            spaceAfter=12,
            leading=16,
        )
        story.append(Paragraph(pdf_text, text_style))

    fields_table = _field_values_table(booking_request, usable_width)
    if fields_table:
        story.append(Spacer(1, 0.3 * cm))
        story.append(fields_table)

    if form.pdf_footer_text:
        story.append(Spacer(1, 0.45 * cm))
        footer_extra = _apply_placeholders(form.pdf_footer_text, booking_request).replace('\n', '<br/>')
        footer_style = ParagraphStyle(
            'BookingPdfFooterExtra',
            parent=ps['muted'],
            fontSize=9,
            leading=12,
        )
        story.append(Paragraph(footer_extra, footer_style))

    build_standard_pdf(story, pagesize=A4, output=output)

    if isinstance(output, BytesIO):
        output.seek(0)
        return output
    return output
