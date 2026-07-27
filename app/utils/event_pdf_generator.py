from datetime import datetime

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from app.utils.pdf_generator import (
    PDF_COLORS,
    RoundedBox,
    build_standard_header,
    build_standard_pdf,
    pdf_paragraph_styles,
    standard_table_style,
)


def generate_single_event_pdf(event_obj):
    styles = getSampleStyleSheet()
    ps = pdf_paragraph_styles()
    body_style = ParagraphStyle(
        'SingleBody',
        parent=ps['body'],
        fontSize=10,
        leading=14,
    )

    stand_date = event_obj.created_at.strftime('%d.%m.%Y') if event_obj.created_at else datetime.now().strftime('%d.%m.%Y')
    story = [
        build_standard_header(
            f"Veranstaltung: {event_obj.name}",
            subtitle=f"Stand: {stand_date}",
            pagesize=A4,
        ),
        Spacer(1, 0.35 * cm),
    ]
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
    table.setStyle(standard_table_style())
    story.append(table)
    story.append(Spacer(1, 0.35 * cm))

    people = _collect_people(event_obj)
    story.append(Paragraph(f"<b>Helfer:</b> {', '.join(people)}", body_style))
    story.append(Spacer(1, 0.2 * cm))

    story.append(Paragraph("Ansprechpartner", ps['section']))
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
    story.append(Paragraph("Zeitplan pro Termin", ps['section']))
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

    return build_standard_pdf(story, pagesize=A4)


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
        fontSize=13,
        textColor=PDF_COLORS['text'],
        fontName='Helvetica-Bold',
        spaceAfter=5,
    )
    body_style = ParagraphStyle(
        'CardBody',
        parent=styles['Normal'],
        fontSize=9.5,
        leading=12.5,
        textColor=PDF_COLORS['text'],
    )

    people = _collect_people(event_obj)
    materials = _collect_materials_for_event(event_obj)
    contacts = _collect_contacts(event_obj)

    term_lines = []
    for appointment in future_appointments:
        term_lines.append(
            f"{appointment.start_time.strftime('%d.%m. %H:%M')} - "
            f"{appointment.end_time.strftime('%H:%M')} | {appointment.label}"
        )

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

    inner = Table([[lines]], colWidths=[6.3 * cm])
    inner.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    return RoundedBox(
        inner,
        width=6.7 * cm,
        padding=8,
        radius=10,
        fill_color=PDF_COLORS['white'],
        stroke_color=PDF_COLORS['line'],
    )


def generate_event_overview_pdf(events, now=None, title='Veranstaltungsübersicht'):
    """Karten-Übersicht aktiver Events mit zukünftigen Terminen (Querformat)."""
    now = now or datetime.utcnow()
    styles = getSampleStyleSheet()
    page = landscape(A4)
    story = [
        build_standard_header(
            title,
            subtitle=f"Stand: {datetime.now().strftime('%d.%m.%Y')}",
            pagesize=page,
            logo_size=1.6 * cm,
            content_width=page[0] - 1.1 * cm,
        ),
        Spacer(1, 0.35 * cm),
    ]

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

    return build_standard_pdf(
        story,
        pagesize=page,
        leftMargin=0.55 * cm,
        rightMargin=0.55 * cm,
        topMargin=0.7 * cm,
        bottomMargin=1.8 * cm,
    )


def generate_appointments_overview_pdf(appointments, title='Standardübersicht'):
    """Tabellen-PDF für Terminlisten (Standard / Meine / Archiv)."""
    styles = getSampleStyleSheet()
    story = [
        build_standard_header(title, subtitle=f"Stand: {datetime.now().strftime('%d.%m.%Y')}", pagesize=A4),
        Spacer(1, 0.35 * cm),
    ]

    table_data = [['Termin', 'Veranstaltung', 'Start', 'Ende', 'Ort']]
    for appointment in appointments:
        event_name = appointment.event.name if appointment.event else '-'
        location = appointment.location or (appointment.event.default_location if appointment.event else None) or '-'
        table_data.append([
            Paragraph(appointment.label, styles['Normal']),
            Paragraph(event_name, styles['Normal']),
            appointment.start_time.strftime('%d.%m.%Y %H:%M'),
            appointment.end_time.strftime('%d.%m.%Y %H:%M'),
            Paragraph(location, styles['Normal']),
        ])

    if len(table_data) == 1:
        story.append(Paragraph("Keine Termine vorhanden.", styles['Normal']))
    else:
        table = Table(table_data, colWidths=[3.4 * cm, 4.2 * cm, 3.2 * cm, 3.2 * cm, 3.2 * cm])
        table.setStyle(standard_table_style())
        story.append(table)

    return build_standard_pdf(story, pagesize=A4)


def generate_people_overview_pdf(rows, title='Personenübersicht'):
    """Tabellen-PDF für die Personenübersicht."""
    styles = getSampleStyleSheet()
    story = [
        build_standard_header(title, subtitle=f"Stand: {datetime.now().strftime('%d.%m.%Y')}", pagesize=A4),
        Spacer(1, 0.35 * cm),
    ]

    table_data = [['Person', 'Anzahl Veranstaltungen']]
    for row in rows:
        table_data.append([row['user'].full_name, str(row['event_count'])])

    if len(table_data) == 1:
        story.append(Paragraph("Noch keine Zuordnungen vorhanden.", styles['Normal']))
    else:
        table = Table(table_data, colWidths=[10 * cm, 7 * cm])
        table.setStyle(standard_table_style())
        story.append(table)

    return build_standard_pdf(story, pagesize=A4)
