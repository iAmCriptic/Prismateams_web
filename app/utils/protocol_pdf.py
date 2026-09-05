"""PDF generation for meeting protocols (Protokollführung)."""

from __future__ import annotations

import html as html_lib
import re
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import ListFlowable, ListItem, Paragraph, Spacer, Table, TableStyle

from app.utils.pdf_generator import (
    PDF_COLORS,
    build_standard_header,
    build_standard_pdf,
    pdf_paragraph_styles,
    standard_table_style,
)

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None


def _esc(text: str) -> str:
    return html_lib.escape(text or '', quote=True)


def _inline_markup(node) -> str:
    """Convert a BeautifulSoup node tree to ReportLab-safe inline markup."""
    if node is None:
        return ''
    if isinstance(node, str):
        return _esc(node)
    name = getattr(node, 'name', None)
    if name is None:
        return _esc(getattr(node, 'string', None) or '')

    inner = ''.join(_inline_markup(c) for c in getattr(node, 'children', []) or [])
    if name in ('b', 'strong'):
        return f'<b>{inner}</b>'
    if name in ('i', 'em'):
        return f'<i>{inner}</i>'
    if name == 'u':
        return f'<u>{inner}</u>'
    if name == 'br':
        return '<br/>'
    if name in ('span', 'a', 'font'):
        return inner
    return inner


def _html_to_flowables(html: str, body_style, bullet_style=None):
    """Convert limited Quill HTML into ReportLab flowables."""
    raw = (html or '').strip()
    if not raw or raw in ('<p><br></p>', '<p></p>'):
        return [Paragraph('—', body_style)]

    if BeautifulSoup is None:
        plain = re.sub(r'<[^>]+>', ' ', raw)
        plain = re.sub(r'\s+', ' ', plain).strip()
        return [Paragraph(_esc(plain) or '—', body_style)]

    soup = BeautifulSoup(raw, 'html.parser')
    flowables = []
    bullet_style = bullet_style or body_style

    def flush_paragraph(tag):
        markup = _inline_markup(tag).strip()
        if markup:
            flowables.append(Paragraph(markup, body_style))

    for child in list(soup.children):
        name = getattr(child, 'name', None)
        if name is None:
            text = str(child).strip()
            if text:
                flowables.append(Paragraph(_esc(text), body_style))
            continue
        if name in ('p', 'div', 'h1', 'h2', 'h3', 'h4'):
            flush_paragraph(child)
        elif name in ('ul', 'ol'):
            items = []
            for li in child.find_all('li', recursive=False):
                markup = _inline_markup(li).strip() or ' '
                items.append(ListItem(Paragraph(markup, bullet_style), leftIndent=12, bulletColor=PDF_COLORS['text']))
            if items:
                flowables.append(
                    ListFlowable(
                        items,
                        bulletType='1' if name == 'ol' else 'bullet',
                        start='1',
                        leftIndent=18,
                        bulletFontName='Helvetica',
                        bulletFontSize=10,
                    )
                )
        elif name == 'br':
            flowables.append(Spacer(1, 0.15 * cm))
        else:
            flush_paragraph(child)

    return flowables or [Paragraph('—', body_style)]


def generate_protocol_pdf(protocol, output=None):
    """Build a protocol PDF: logo right, title+date above accent line, standard footer."""
    if output is None:
        output = BytesIO()

    pagesize = A4
    usable = pagesize[0] - 4 * cm
    ps = pdf_paragraph_styles()

    date_str = protocol.meeting_date.strftime('%d.%m.%Y') if protocol.meeting_date else ''
    subtitle_parts = [date_str]
    if protocol.start_time:
        subtitle_parts.append(protocol.start_time.strftime('%H:%M'))
        if protocol.end_time:
            subtitle_parts[-1] += f' – {protocol.end_time.strftime("%H:%M")}'
    subtitle = ' · '.join(p for p in subtitle_parts if p)

    story = [
        build_standard_header(
            protocol.title or 'Protokoll',
            subtitle=subtitle or None,
            pagesize=pagesize,
            content_width=usable,
            logo_align='right',
        ),
        Spacer(1, 0.35 * cm),
    ]

    meta_style = ParagraphStyle(
        'ProtocolMetaLabel',
        parent=ps['body'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
    )
    meta_val = ParagraphStyle(
        'ProtocolMetaVal',
        parent=ps['body'],
        fontSize=9,
        leading=12,
    )

    def meta_row_plain(label, value):
        text = (value or '').strip() or '—'
        if text != '—':
            parts = [p.strip() for p in re.split(r'[\n,;]+', text) if p.strip()]
            text = ', '.join(parts) if parts else '—'
        return [
            Paragraph(_esc(label), meta_style),
            Paragraph(_esc(text), meta_val),
        ]

    meta_data = [
        meta_row_plain('Teilnehmer*innen', protocol.participants_text),
        meta_row_plain('Entschuldigt', protocol.excused_text),
        meta_row_plain('Unentschuldigt', protocol.absent_text),
    ]
    meta_table = Table(meta_data, colWidths=[3.6 * cm, usable - 3.6 * cm])
    meta_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 0.4 * cm))

    items = list(protocol.agenda_items or [])
    story.append(Paragraph('Tagesordnungspunkte', ps['section']))
    if items:
        for i, item in enumerate(items, start=1):
            story.append(Paragraph(f'{i}. {_esc(item.title or "TOP")}', ps['body']))
    else:
        story.append(Paragraph('—', ps['muted']))

    story.append(Spacer(1, 0.35 * cm))
    story.append(Paragraph('Inhalt', ps['section']))

    content_style = ParagraphStyle(
        'ProtocolContent',
        parent=ps['body'],
        fontSize=9,
        leading=12,
    )
    header_cell_style = ParagraphStyle(
        'ProtocolTableHead',
        parent=ps['body'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
    )

    table_data = [[
        Paragraph('TOP', header_cell_style),
        Paragraph('Inhalt', header_cell_style),
    ]]

    for i, item in enumerate(items, start=1):
        content_flows = _html_to_flowables(item.content_html or '', content_style)
        # Keep content in a nested flowable column
        content_cell = content_flows if len(content_flows) > 1 else content_flows[0]
        table_data.append([
            Paragraph(str(i), content_style),
            content_cell if not isinstance(content_cell, list) else content_flows,
        ])
        # ReportLab Table cells need a single flowable or string; wrap multi in KeepTogether-like list via nested Table
        if isinstance(table_data[-1][1], list):
            inner = Table([[f] for f in table_data[-1][1]], colWidths=[usable - 2.2 * cm])
            inner.setStyle(TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 1),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            table_data[-1][1] = inner

    if len(table_data) == 1:
        table_data.append([
            Paragraph('—', content_style),
            Paragraph('—', content_style),
        ])

    content_table = Table(table_data, colWidths=[1.6 * cm, usable - 1.6 * cm])
    content_table.setStyle(standard_table_style(header=True))
    content_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(content_table)

    return build_standard_pdf(story, pagesize=pagesize, output=output)
