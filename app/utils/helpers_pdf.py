"""PDF-Generator für Bereichs-Schichtpläne & Team-Listen (einheitliches Portal-PDF-Design)."""

from __future__ import annotations

import io
from html import escape

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph, Spacer, Table

from app.utils.pdf_generator import (
    build_standard_header,
    build_standard_pdf,
    pdf_paragraph_styles,
    standard_table_style,
)


def generate_area_team_pdf(event, area, detail):
    """Erstellt ein A4-Querformat-PDF im einheitlichen Portal-Design (Logo, Akzentlinie, Footer)."""
    pagesize = landscape(A4)
    left_margin = 1.5 * cm
    right_margin = 1.5 * cm
    content_width = pagesize[0] - left_margin - right_margin

    kpis = detail['kpis']
    ps = pdf_paragraph_styles()
    cell_style = ps.get('cell') or ps['body']

    subtitle = (
        f'{escape(event.name)}  |  '
        f'Schichten besetzt: {kpis["filled_slots"]} / {kpis["total_slots"]}  |  '
        f'Stunden gesamt: {kpis["total_hours"]} Std.  |  '
        f'Essen: {kpis["food_total"]} (Fr {kpis["food_by_day"]["Fr"]} / Sa {kpis["food_by_day"]["Sa"]} / So {kpis["food_by_day"]["So"]})  |  '
        f'Getränke: {kpis["drinks_total"]}'
    )

    story = [
        build_standard_header(
            title=f'Bereich: {escape(area.name)}',
            subtitle=subtitle,
            pagesize=pagesize,
            content_width=content_width,
            logo_size=1.8 * cm,
        )
    ]

    # 1. Schichtplan-Tabelle
    story.append(Paragraph('Schichtplan', ps['section']))
    shift_data = [['Tag', 'Datum', 'Zeitraum', 'Std.', 'Rolle / Sub-Bereich', 'Helfer / Posten', 'Essen', 'Getränke']]
    for row in detail['shift_rows']:
        s = row['shift']
        date_str = s.date.strftime('%d.%m.%Y') if s.date else '—'
        time_str = f'{s.start_time or "—"}' + (f' – {s.end_time}' if s.end_time else '')
        role_str = (s.role_label or '—') + (' (HEAD)' if s.is_head_role else '')
        if s.helper:
            helper_str = s.helper.full_name
        elif (s.group_count or 1) > 1:
            helper_str = f'{s.group_count}x {s.role_label or "Sammelposten"}'
        else:
            helper_str = 'Offen'

        shift_data.append([
            Paragraph(escape(s.day_label or ''), cell_style),
            Paragraph(escape(date_str), cell_style),
            Paragraph(escape(time_str), cell_style),
            Paragraph(escape(str(s.hours)), cell_style),
            Paragraph(escape(role_str), cell_style),
            Paragraph(escape(helper_str), cell_style),
            Paragraph(escape(str(row['food'])), cell_style),
            Paragraph(escape(str(row['drinks'])), cell_style),
        ])

    if len(shift_data) == 1:
        shift_data.append([Paragraph('Keine Schichten vorhanden.', cell_style), '', '', '', '', '', '', ''])

    shift_table = Table(
        shift_data,
        colWidths=[24 * mm, 24 * mm, 30 * mm, 16 * mm, 48 * mm, 76 * mm, 18 * mm, 22 * mm],
        repeatRows=1,
    )
    shift_table.setStyle(standard_table_style(header=True))
    story.append(shift_table)
    story.append(Spacer(1, 6 * mm))

    # 2. Team-Liste
    story.append(Paragraph('Team-Liste (Kontakt & Unverträglichkeiten)', ps['section']))
    team_data = [['Name', 'E-Mail', 'Telefon', 'Unverträglichkeiten', 'Rollen', 'Std.', 'Marken (E / G)']]
    for item in detail['team_list']:
        h = item['helper']
        team_data.append([
            Paragraph(escape(h.full_name), cell_style),
            Paragraph(escape(h.email or ''), cell_style),
            Paragraph(escape(h.phone or '—'), cell_style),
            Paragraph(escape(h.allergies or '—'), cell_style),
            Paragraph(escape(', '.join(item['roles']) or '—'), cell_style),
            Paragraph(escape(str(item['hours'])), cell_style),
            Paragraph(escape(f'{item["food"]} / {item["drinks"]}'), cell_style),
        ])

    if len(team_data) == 1:
        team_data.append([Paragraph('Keine Helfer eingeteilt.', cell_style), '', '', '', '', '', ''])

    team_table = Table(
        team_data,
        colWidths=[44 * mm, 55 * mm, 31 * mm, 52 * mm, 42 * mm, 16 * mm, 27 * mm],
        repeatRows=1,
    )
    team_table.setStyle(standard_table_style(header=True))
    story.append(team_table)

    output = io.BytesIO()
    build_standard_pdf(
        story,
        pagesize=pagesize,
        leftMargin=left_margin,
        rightMargin=right_margin,
        topMargin=1.4 * cm,
        bottomMargin=1.8 * cm,
        output=output,
    )
    output.seek(0)
    return output.getvalue()
