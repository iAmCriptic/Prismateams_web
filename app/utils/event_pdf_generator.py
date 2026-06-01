from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.utils.pdf_generator import get_logo_path


def _build_pdf(story):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    doc.build(story)
    buffer.seek(0)
    return buffer


def generate_single_event_pdf(event_obj):
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('SingleTitle', parent=styles['Heading2'], fontSize=18, textColor=colors.HexColor('#0d6efd'))
    subtitle_style = ParagraphStyle('SingleSubtitle', parent=styles['Normal'], fontSize=12)
    body_style = ParagraphStyle('SingleBody', parent=styles['Normal'], fontSize=11, leading=14)

    logo_path = get_logo_path()
    logo_cell = ''
    if logo_path:
        try:
            logo_cell = Image(logo_path, width=2.2 * cm, height=2.2 * cm, kind='proportional')
        except Exception:
            logo_cell = ''

    stand_date = event_obj.created_at.strftime('%d.%m.%Y') if event_obj.created_at else datetime.now().strftime('%d.%m.%Y')
    header_text = [
        Paragraph(f"Veranstaltung: {event_obj.name}", title_style),
        Paragraph(f"Stand: {stand_date}", subtitle_style),
    ]
    header = Table([[logo_cell, header_text]], colWidths=[2.8 * cm, 14.8 * cm])
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))

    story = [header, Spacer(1, 0.35 * cm)]
    story.append(Paragraph(f"<b>Beschreibung:</b> {event_obj.description or '-'}", body_style))
    story.append(Paragraph(f"<b>Ort:</b> {event_obj.default_location or '-'}", body_style))
    story.append(Spacer(1, 0.25 * cm))

    table_data = [['Termin', 'Start', 'Ende', 'Ort']]
    for appointment in event_obj.appointments:
        table_data.append([
            appointment.label,
            appointment.start_time.strftime('%d.%m.%Y %H:%M'),
            appointment.end_time.strftime('%d.%m.%Y %H:%M'),
            appointment.location or event_obj.default_location or '-',
        ])
    table = Table(table_data, colWidths=[4.5 * cm, 4 * cm, 4 * cm, 5.1 * cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 10.5),
        ('LEADING', (0, 0), (-1, -1), 13),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.35 * cm))

    people = _collect_people(event_obj)
    story.append(Paragraph(f"<b>Helfer:</b> {', '.join(people)}", body_style))
    story.append(Spacer(1, 0.2 * cm))

    story.append(Paragraph("Ansprechpartner", styles['Heading3']))
    if event_obj.contacts:
        for contact in event_obj.contacts:
            detail_parts = [contact.name]
            if contact.role:
                detail_parts.append(f"({contact.role})")
            if contact.phone:
                detail_parts.append(contact.phone)
            if contact.email:
                detail_parts.append(contact.email)
            story.append(Paragraph(f"- {' '.join(detail_parts)}", body_style))
    else:
        story.append(Paragraph("- Keine", body_style))

    story.append(Spacer(1, 0.25 * cm))
    story.append(Paragraph("Zeitplan pro Termin", styles['Heading3']))
    if event_obj.appointments:
        for appointment in event_obj.appointments:
            story.append(Paragraph(
                f"<b>{appointment.label}</b> ({appointment.start_time.strftime('%d.%m.%Y %H:%M')})",
                body_style,
            ))
            appointment_timeline = [item for item in event_obj.timeline_items if item.appointment_id == appointment.id]
            if appointment_timeline:
                for item in appointment_timeline:
                    story.append(Paragraph(f"- {item.title}", body_style))
            else:
                story.append(Paragraph("- Kein Zeitplan für diesen Termin", body_style))
            story.append(Spacer(1, 0.1 * cm))
    else:
        story.append(Paragraph("- Kein Zeitplan", body_style))

    return _build_pdf(story)


def _future_appointments_for_event(event_obj, now):
    return [a for a in event_obj.appointments if a.end_time >= now]


def _collect_people(event_obj):
    names = []
    for assignment in event_obj.assignments:
        if assignment.user:
            names.append(assignment.user.full_name)
        elif assignment.display_name:
            names.append(assignment.display_name)
    return names or ['-']


def _collect_materials_for_event(event_obj):
    materials = []
    seen = set()
    for appointment in event_obj.appointments:
        for need in appointment.inventory_needs:
            name = need.product.name if need.product else f'Produkt {need.product_id}'
            key = (name, need.quantity)
            if key in seen:
                continue
            seen.add(key)
            materials.append(f"{name} x{need.quantity}")
    return materials or ['-']


def _build_overview_header(styles):
    title_style = ParagraphStyle(
        'EventOverviewTitle',
        parent=styles['Heading2'],
        fontSize=24,
        textColor=colors.HexColor('#0d6efd'),
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        'EventOverviewSubtitle',
        parent=styles['Normal'],
        fontSize=14,
        textColor=colors.HexColor('#555555'),
    )
    stand = datetime.now().strftime('%d.%m.%Y')
    title_block = [
        Paragraph('Veranstaltungsübersicht', title_style),
        Paragraph(f'Stand: {stand}', subtitle_style),
    ]

    logo_cell = ''
    logo_path = get_logo_path()
    if logo_path:
        try:
            logo_cell = Image(logo_path, width=1.7 * cm, height=1.7 * cm, kind='proportional')
        except Exception:
            logo_cell = ''

    header_table = Table([[logo_cell, title_block, '']], colWidths=[2.8 * cm, 12 * cm, 12.5 * cm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (1, 0), 'LEFT'),
        ('ALIGN', (2, 0), (2, 0), 'LEFT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    return header_table


def _collect_contacts(event_obj):
    contacts = []
    for contact in event_obj.contacts:
        entry = contact.name
        if contact.role:
            entry += f" ({contact.role})"
        contacts.append(entry)
    return contacts or ['-']


def _event_card(event_obj, future_appointments, styles):
    card_title = ParagraphStyle(
        'CardTitle',
        parent=styles['Heading4'],
        fontSize=15,
        textColor=colors.HexColor('#0d6efd'),
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        'CardBody',
        parent=styles['Normal'],
        fontSize=11.5,
        leading=14,
        textColor=colors.black,
    )

    people = _collect_people(event_obj)
    materials = _collect_materials_for_event(event_obj)
    people_text = ', '.join(people)
    material_text = ', '.join(materials)

    term_lines = []
    for appointment in future_appointments:
        term_lines.append(
            f"{appointment.start_time.strftime('%d.%m. %H:%M')} - "
            f"{appointment.end_time.strftime('%H:%M')} | {appointment.label}"
        )
    terms_text = '<br/>'.join(term_lines) if term_lines else '-'

    contacts = _collect_contacts(event_obj)
    contacts_text = ', '.join(contacts)

    lines = [Paragraph(f"{event_obj.name}", card_title)]
    sections = [
        ('Ort', [event_obj.default_location or '-']),
        ('Termine', term_lines or ['-']),
        ('Personen', people or ['-']),
        ('Ansprechpartner', contacts or ['-']),
        ('Material', materials or ['-']),
    ]

    for heading, entries in sections:
        section_text = f"<b>{heading}:</b><br/>" + "<br/>".join(entries) + "<br/><br/>"
        lines.append(Paragraph(section_text, body_style))

    table = Table([[lines]], colWidths=[6.7 * cm])
    table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.7, colors.HexColor('#b7b7b7')),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    return table


def generate_event_overview_pdf(events, now=None):
    now = now or datetime.utcnow()
    styles = getSampleStyleSheet()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=0.55 * cm,
        rightMargin=0.55 * cm,
        topMargin=0.55 * cm,
        bottomMargin=0.55 * cm,
    )
    story = [_build_overview_header(styles), Spacer(1, 0.45 * cm)]

    event_items = []
    for event_obj in events:
        future_appointments = _future_appointments_for_event(event_obj, now)
        if not future_appointments:
            continue
        first_start = min(appointment.start_time for appointment in future_appointments)
        event_items.append((first_start, _event_card(event_obj, future_appointments, styles)))

    event_items.sort(key=lambda item: item[0])
    cards = [item[1] for item in event_items]

    if not cards:
        story.append(Paragraph("Keine zukünftigen Veranstaltungstermine vorhanden.", styles['Normal']))
    else:
        columns = 4
        rows = []
        for index in range(0, len(cards), columns):
            row_cards = cards[index:index + columns]
            while len(row_cards) < columns:
                row_cards.append('')
            rows.append(row_cards)

        grid = Table(rows, colWidths=[6.95 * cm] * columns, rowHeights=[7.2 * cm] * len(rows))
        grid.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(grid)
    doc.build(story)
    buffer.seek(0)
    return buffer
