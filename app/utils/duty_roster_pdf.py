"""PDF export for monthly duty rosters — always one landscape A4 page."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import Image, KeepInFrame, Paragraph, Spacer, Table, TableStyle

from app.utils.duty_roster import (
    entry_map_for_roster,
    planned_hours_by_column_week,
    visible_columns,
    week_boundary_rows,
)
from app.utils.pdf_generator import (
    PDF_COLORS,
    AccentLine,
    build_standard_pdf,
    get_logo_path,
)


def _escape(text: str) -> str:
    return (
        (text or '')
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )


def _compact_header_flowables(title: str, subtitle: str, content_width: float, logo_size: float):
    """Schmaler Kopf als flache Flowables (kein KeepTogether — kaputt in KeepInFrame)."""
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DutyPdfTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=14,
        textColor=PDF_COLORS['text'],
        spaceAfter=1,
    )
    sub_style = ParagraphStyle(
        'DutyPdfSub',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        textColor=PDF_COLORS['text_muted'],
    )

    text_block = [Paragraph(_escape(title), title_style), Paragraph(_escape(subtitle), sub_style)]
    logo_cell = ''
    logo_path = get_logo_path()
    if logo_path:
        try:
            logo_cell = Image(logo_path, width=logo_size, height=logo_size, kind='proportional')
        except Exception:
            logo_cell = ''

    if logo_cell != '':
        logo_col = logo_size + 0.4 * cm
        text_col = max(content_width - logo_col, 6 * cm)
        header = Table([[logo_cell, text_block]], colWidths=[logo_col, text_col])
    else:
        header = Table([[text_block]], colWidths=[content_width])

    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    return [header, Spacer(1, 1.2 * mm), AccentLine(content_width, height=1.2), Spacer(1, 1.5 * mm)]


def _measure_flowables_height(flowables, width: float) -> float:
    total = 0.0
    for f in flowables:
        _w, h = f.wrap(width, 10000)
        total += h
    return total


def generate_duty_roster_pdf(roster, output=None):
    """Landscape A4, eine Seite: Tabelle füllt die verfügbare Höhe, Schrift so groß wie möglich."""
    pagesize = landscape(A4)
    page_w, page_h = pagesize

    left_m = right_m = 0.5 * cm
    top_m = 0.45 * cm
    # Standard-Footer: Text ~1.15cm, Linie ~1.55cm → genug Abstand darunter
    bottom_m = 1.75 * cm

    usable_w = page_w - left_m - right_m
    usable_h = page_h - top_m - bottom_m

    cols = visible_columns(roster)
    n_person = max(len(cols), 1)

    team_name = roster.team.name if roster.team else ''
    title = f'Dienstplan – {roster.display_title}'
    stand = datetime.now().strftime('%d.%m.%Y')
    subtitle = f'{team_name} · Stand: {stand}' if team_name else f'Stand: {stand}'

    entries = entry_map_for_roster(roster)
    rows = week_boundary_rows(roster.days, roster=roster)
    hours_by_week = planned_hours_by_column_week(roster)

    header_parts = _compact_header_flowables(title, subtitle, usable_w, logo_size=1.0 * cm)
    header_h = _measure_flowables_height(header_parts, usable_w)
    # 2pt Puffer gegen Rundungs-Overflow (sonst schrumpft KeepInFrame unnötig)
    table_budget = max(usable_h - header_h - 2, 80)

    n_table_rows = 1 + len(rows)
    # Zeilenhöhe so wählen, dass die Tabelle die volle Resthöhe ausfüllt
    row_h = table_budget / n_table_rows
    # KW-Zeilen etwas flacher, Tageszeilen etwas höher — gleichmäßig reicht
    pad = max(1.0, min(2.5, row_h * 0.12))
    # Schrift aus Zeilenhöhe: möglichst groß, aber einzeilig
    font_size = max(5.0, min(10.0, row_h - 2 * pad - 1.5))
    if n_person >= 10:
        font_size = min(font_size, 7.0)
    elif n_person >= 7:
        font_size = min(font_size, 8.0)
    leading = min(font_size + 1.2, row_h - 2 * pad)

    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle(
        'DutyCell',
        parent=styles['Normal'],
        fontSize=font_size,
        leading=leading,
        alignment=TA_CENTER,
        textColor=PDF_COLORS['text'],
    )
    left_style = ParagraphStyle(
        'DutyLeft',
        parent=cell_style,
        alignment=TA_LEFT,
    )
    header_style = ParagraphStyle(
        'DutyHeader',
        parent=cell_style,
        fontName='Helvetica-Bold',
        fontSize=font_size + 0.5,
        leading=leading,
    )
    kw_style = ParagraphStyle(
        'DutyKW',
        parent=styles['Normal'],
        fontSize=font_size + 0.5,
        leading=leading,
        fontName='Helvetica-Bold',
        alignment=TA_LEFT,
        textColor=PDF_COLORS['text'],
    )

    header = [
        Paragraph('Wochentag', header_style),
        Paragraph('Datum', header_style),
        Paragraph('WAS IST LOS?', header_style),
    ]
    for col in cols:
        header.append(Paragraph(_escape(col.display_name), header_style))

    table_data = [header]
    style_cmds = [
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 0), (-1, 0), PDF_COLORS['header_bg']),
        ('GRID', (0, 0), (-1, -1), 0.35, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), pad),
        ('RIGHTPADDING', (0, 0), (-1, -1), pad),
        ('TOPPADDING', (0, 0), (-1, -1), pad),
        ('BOTTOMPADDING', (0, 0), (-1, -1), pad),
    ]

    row_idx = 1
    for row in rows:
        if row['kind'] == 'kw':
            week = row['week']
            label = Paragraph(f'KW {week}', kw_style)
            cells = [label, '', '']
            for col in cols:
                h = hours_by_week.get(col.id, {}).get(week, 0.0)
                cells.append(Paragraph(f'{h}h', cell_style))
            table_data.append(cells)
            bg = colors.HexColor(row['color'])
            style_cmds.append(('SPAN', (0, row_idx), (2, row_idx)))
            style_cmds.append(('BACKGROUND', (0, row_idx), (-1, row_idx), bg))
            style_cmds.append(('ALIGN', (3, row_idx), (-1, row_idx), 'CENTER'))
            row_idx += 1
            continue

        day = row['day']
        bg = colors.HexColor(row['color'])
        cells = [
            Paragraph(_escape(day.weekday_label), cell_style),
            Paragraph(day.date.strftime('%d.%m.%Y'), cell_style),
            Paragraph(_escape(day.whats_happening or ''), left_style),
        ]
        for col in cols:
            e = entries.get((day.id, col.id))
            text = e.display_text() if e else ''
            cells.append(Paragraph(_escape(text), cell_style))
        table_data.append(cells)
        style_cmds.append(('BACKGROUND', (0, row_idx), (-1, row_idx), bg))
        if row.get('out_of_month'):
            style_cmds.append(('TEXTCOLOR', (0, row_idx), (-1, row_idx), colors.HexColor('#555555')))
        row_idx += 1

    # Spaltenbreiten: Wochentag breit genug für „Donnerstag“ / „Wochentag“
    weekday_w = 2.35 * cm
    date_w = 1.9 * cm
    whats_w = max(2.0 * cm, min(3.8 * cm, usable_w * 0.16))
    person_w = max(1.0 * cm, (usable_w - weekday_w - date_w - whats_w) / n_person)
    if weekday_w + date_w + whats_w + person_w * n_person > usable_w + 0.01:
        whats_w = max(1.4 * cm, usable_w - weekday_w - date_w - person_w * n_person)
    col_widths = [weekday_w, date_w, whats_w] + [person_w] * n_person

    # Feste Zeilenhöhen → Tabelle füllt die Resthöhe exakt
    row_heights = [row_h] * n_table_rows
    table = Table(table_data, colWidths=col_widths, rowHeights=row_heights, repeatRows=0)
    table.setStyle(TableStyle(style_cmds))

    content = list(header_parts) + [table]

    # Safety-Net: nur schrumpfen, falls Messung/Rundung doch überläuft
    frame = KeepInFrame(
        maxWidth=usable_w,
        maxHeight=usable_h,
        content=content,
        mode='shrink',
        hAlign='LEFT',
        vAlign='TOP',
    )

    buf = build_standard_pdf(
        [frame],
        pagesize=pagesize,
        leftMargin=left_m,
        rightMargin=right_m,
        topMargin=top_m,
        bottomMargin=bottom_m,
        output=output,
    )
    if isinstance(buf, BytesIO):
        buf.seek(0)
    return buf
