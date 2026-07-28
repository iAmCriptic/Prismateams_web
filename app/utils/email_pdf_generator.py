"""PDF-Druckansicht für einzelne E-Mails — Portal-Standardlayout."""

from __future__ import annotations

import re
from html import unescape
from io import BytesIO

from bs4 import BeautifulSoup
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer, Table

from app.utils.common import format_datetime
from app.utils.i18n import translate
from app.utils.pdf_generator import (
    PDF_COLORS,
    build_standard_header,
    build_standard_pdf,
    meta_kv_table_style,
    pdf_paragraph_styles,
)


def _pdf_escape(text: str) -> str:
    if not text:
        return ''
    return (
        str(text)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )


def _decode_display(value) -> str:
    if value is None:
        return ''
    text = str(value).strip()
    if not text:
        return ''
    try:
        from email.header import decode_header
        parts = decode_header(text)
        out = ''
        for part, encoding in parts:
            if isinstance(part, bytes):
                for enc in (encoding, 'utf-8', 'latin-1', 'cp1252'):
                    if not enc:
                        continue
                    try:
                        out += part.decode(enc, errors='ignore')
                        break
                    except (UnicodeDecodeError, LookupError):
                        continue
                else:
                    out += part.decode('ascii', errors='replace')
            else:
                out += str(part)
        return out.strip() or text
    except Exception:
        return text


def _normalize_address_line(value) -> str:
    text = _decode_display(value)
    if not text:
        return '—'
    # JSON-Listen aus älteren Speichernormen glätten
    if text.startswith('[') and text.endswith(']'):
        try:
            import json
            parsed = json.loads(text)
            if isinstance(parsed, (list, tuple)):
                text = ', '.join(str(p).strip() for p in parsed if str(p).strip())
        except Exception:
            pass
    text = re.sub(r'\s*;\s*', ', ', text)
    text = re.sub(r'\s*,\s*', ', ', text)
    return text.strip() or '—'


def _html_to_plain_paragraphs(html: str) -> list[str]:
    soup = BeautifulSoup(html or '', 'html.parser')
    for tag in soup(['script', 'style', 'head', 'meta', 'link', 'title']):
        tag.decompose()
    for br in soup.find_all('br'):
        br.replace_with('\n')
    for block in soup.find_all(['p', 'div', 'tr', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'pre']):
        block.append('\n')
    raw = unescape(soup.get_text('\n'))
    lines = [re.sub(r'[ \t\f\v]+', ' ', line).strip() for line in raw.splitlines()]
    paragraphs: list[str] = []
    buf: list[str] = []
    for line in lines:
        if line:
            buf.append(line)
            continue
        if buf:
            paragraphs.append(' '.join(buf))
            buf = []
    if buf:
        paragraphs.append(' '.join(buf))
    return [p for p in paragraphs if p]


def _body_flowables(email_msg, body_style, muted_style) -> list:
    flowables = []
    raw_html = None
    if email_msg.body_html:
        try:
            if isinstance(email_msg.body_html, bytes):
                raw_html = email_msg.body_html.decode('utf-8', errors='replace')
            else:
                raw_html = str(email_msg.body_html)
        except Exception:
            raw_html = None

    paragraphs: list[str] = []
    if raw_html:
        paragraphs = _html_to_plain_paragraphs(raw_html)

    if not paragraphs and email_msg.body_text:
        text = str(email_msg.body_text)
        for chunk in re.split(r'\n\s*\n', text):
            cleaned = re.sub(r'[ \t]+', ' ', chunk).strip()
            cleaned = cleaned.replace('\n', ' ').strip()
            if cleaned:
                paragraphs.append(cleaned)

    if not paragraphs:
        flowables.append(Paragraph(
            _pdf_escape(translate('email.view.content.alert_no_content')),
            muted_style,
        ))
        return flowables

    for para in paragraphs:
        # Lange Absätze in ReportLab-sichere Brüche behalten
        safe = _pdf_escape(para).replace('\n', '<br/>')
        flowables.append(Paragraph(safe, body_style))
        flowables.append(Spacer(1, 0.18 * cm))
    return flowables


def generate_email_print_pdf(email_msg, output=None):
    """
    Druck-PDF einer E-Mail: Logo + Betreff, Metadaten, Trennlinie, Inhalt, Portal-Footer.
    """
    if output is None:
        output = BytesIO()

    ps = pdf_paragraph_styles()
    subject = _decode_display(email_msg.subject) or translate('email.compose.quoted.empty_subject')
    sender = _normalize_address_line(email_msg.sender)
    recipients = _normalize_address_line(email_msg.recipients)
    cc = _normalize_address_line(email_msg.cc) if email_msg.cc else ''
    sent_at = email_msg.received_at or email_msg.sent_at
    date_str = format_datetime(sent_at, '%d.%m.%Y %H:%M') if sent_at else '—'

    body_style = ParagraphStyle(
        'EmailPrintBody',
        parent=ps['body'],
        fontSize=10,
        leading=14,
        spaceAfter=0,
    )
    label_style = ParagraphStyle(
        'EmailPrintLabel',
        parent=ps['muted'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=PDF_COLORS['text_secondary'],
    )
    value_style = ParagraphStyle(
        'EmailPrintValue',
        parent=ps['body'],
        fontSize=10,
        leading=13,
    )

    usable = A4[0] - 4 * cm
    story = [
        build_standard_header(
            _pdf_escape(subject),
            subtitle=None,
            pagesize=A4,
            logo_size=2.0 * cm,
            content_width=usable,
            show_accent=False,
        ),
        Spacer(1, 0.45 * cm),
    ]

    meta_rows = [
        [
            Paragraph(_pdf_escape(translate('email.view.header.from')), label_style),
            Paragraph(_pdf_escape(sender), value_style),
        ],
        [
            Paragraph(_pdf_escape(translate('email.view.header.to')), label_style),
            Paragraph(_pdf_escape(recipients), value_style),
        ],
    ]
    if email_msg.cc and cc and cc != '—':
        meta_rows.append([
            Paragraph(_pdf_escape(translate('email.view.header.cc')), label_style),
            Paragraph(_pdf_escape(cc), value_style),
        ])
    meta_rows.append([
        Paragraph(_pdf_escape(translate('email.view.header.date')), label_style),
        Paragraph(_pdf_escape(date_str), value_style),
    ])

    meta = Table(meta_rows, colWidths=[2.6 * cm, usable - 2.6 * cm])
    meta.setStyle(meta_kv_table_style())
    story.append(meta)
    story.append(Spacer(1, 0.35 * cm))

    # Trennlinie unter den Metadaten (wie gewünscht)
    from app.utils.pdf_generator import AccentLine
    story.append(AccentLine(usable))
    story.append(Spacer(1, 0.45 * cm))

    story.extend(_body_flowables(email_msg, body_style, ps['muted']))

    non_inline = [
        a for a in (email_msg.attachments or [])
        if not getattr(a, 'is_inline', False)
    ]
    if non_inline:
        story.append(Spacer(1, 0.35 * cm))
        story.append(Paragraph(
            _pdf_escape(translate('email.view.attachments.title', count=len(non_inline))),
            ps['section'],
        ))
        for attachment in non_inline:
            name = _decode_display(attachment.filename) or '—'
            story.append(Paragraph(f"• {_pdf_escape(name)}", ps['muted']))

    return build_standard_pdf(story, pagesize=A4, output=output)


def safe_email_pdf_filename(email_msg) -> str:
    subject = _decode_display(getattr(email_msg, 'subject', None)) or 'email'
    cleaned = re.sub(r'[\\/:*?"<>|]+', '', subject).strip()
    cleaned = re.sub(r'\s+', '_', cleaned)[:80] or 'email'
    return f"E-Mail_{cleaned}_{email_msg.id}.pdf"
