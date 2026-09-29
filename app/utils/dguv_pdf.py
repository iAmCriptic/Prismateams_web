"""DGUV V3 Prüfprotokoll PDF (ReportLab) — compact single-page + FES stamp."""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from typing import Any, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from app.utils.pdf_generator import (
    PDF_COLORS,
    build_standard_header,
    pdf_paragraph_styles,
    standard_table_style,
)


def _fmt_bool(val: Optional[bool], yes: str = 'Bestanden', no: str = 'Nicht bestanden') -> str:
    if val is True:
        return yes
    if val is False:
        return no
    return '—'


def _fmt_num(val: Optional[float], unit: str = '') -> str:
    if val is None:
        return '—'
    text = f'{val:g}'
    return f'{text} {unit}'.strip() if unit else text


def _fmt_date(val) -> str:
    if val is None:
        return '—'
    if isinstance(val, datetime):
        return val.strftime('%d.%m.%Y %H:%M')
    if isinstance(val, date):
        return val.strftime('%d.%m.%Y')
    return str(val)


def _result_label(code: str) -> str:
    return {
        'passed': 'Bestanden',
        'deficient': 'Mangelhaft',
        'failed': 'Nicht bestanden / Außer Betrieb',
    }.get(code or '', code or '—')


def _compact_table_style():
    style = standard_table_style(header=True)
    # Tighten padding for single-page layout
    style.add('TOPPADDING', (0, 0), (-1, -1), 3)
    style.add('BOTTOMPADDING', (0, 0), (-1, -1), 3)
    style.add('FONTSIZE', (0, 0), (-1, -1), 8)
    style.add('LEADING', (0, 0), (-1, -1), 10)
    return style


def generate_dguv_exam_pdf(data: dict[str, Any]) -> bytes:
    """Build unsigned DGUV V3 protocol PDF (target: one A4 page)."""
    buffer = BytesIO()
    from reportlab.platypus import SimpleDocTemplate

    # Larger bottom margin reserves space for cryptographic signature appearance
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.1 * cm,
        bottomMargin=3.2 * cm,
    )
    ps = pdf_paragraph_styles()
    story = []
    usable = A4[0] - 3.2 * cm

    story.append(build_standard_header(
        'DGUV V3 Prüfprotokoll',
        subtitle='DIN VDE 0701-0702 / EN 50678 & EN 50699',
        pagesize=A4,
        content_width=usable,
        logo_size=1.5 * cm,
    ))
    story.append(Spacer(1, 0.2 * cm))

    story.append(Paragraph('1. Produkt- & Stammdaten', ps['section']))
    product_rows = [
        ['Feld', 'Wert'],
        ['Bezeichnung', data.get('product_name') or '—'],
        ['Inventar-Nr.', data.get('inventory_number') or '—'],
        ['Seriennummer', data.get('serial_number') or '—'],
        ['Eigentümer', data.get('owner_display') or '—'],
        ['Lagerort', data.get('location') or '—'],
        ['Länge', data.get('length') or '—'],
        ['Ordner', data.get('folder_name') or '—'],
    ]
    t1 = Table(product_rows, colWidths=[4.2 * cm, usable - 4.2 * cm])
    t1.setStyle(_compact_table_style())
    story.append(t1)
    story.append(Spacer(1, 0.18 * cm))

    story.append(Paragraph('2. Prüfer & Prüfgerät', ps['section']))
    device_rows = [
        ['Feld', 'Wert'],
        ['Prüfer', data.get('examiner_name') or '—'],
        ['E-Mail', data.get('examiner_email') or '—'],
        ['Prüfgerät', data.get('device_name') or '—'],
        ['Geräteseriennr.', data.get('device_serial') or '—'],
        ['Letzte Kalibrierung', _fmt_date(data.get('device_calibration_date'))],
        ['Prüfdatum', _fmt_date(data.get('exam_date'))],
        ['Intervall', f"{data.get('interval_months') or '—'} Monate"],
        ['Nächste Prüfung', _fmt_date(data.get('next_exam_date'))],
    ]
    t2 = Table(device_rows, colWidths=[4.2 * cm, usable - 4.2 * cm])
    t2.setStyle(_compact_table_style())
    story.append(t2)
    story.append(Spacer(1, 0.18 * cm))

    story.append(Paragraph('3. Messwerte & Beurteilungen', ps['section']))
    r_pe = data.get('r_pe_ohm')
    r_iso = data.get('r_iso_mohm')
    r_pe_limit = data.get('r_pe_limit', 0.3)
    r_iso_limit = data.get('r_iso_limit', 1.0)
    measure_rows = [
        ['Prüfung', 'Istwert', 'Grenzwert', 'Beurteilung'],
        ['Sichtprüfung', _fmt_bool(data.get('visual_ok')), '—', _fmt_bool(data.get('visual_ok'))],
        [
            'Schutzleiterwiderstand R_PE',
            _fmt_num(r_pe, 'Ω'),
            f'≤ {_fmt_num(r_pe_limit, "Ω")}',
            _fmt_bool(data.get('r_pe_pass')),
        ],
        [
            'Isolationswiderstand R_ISO',
            _fmt_num(r_iso, 'MΩ'),
            f'≥ {_fmt_num(r_iso_limit, "MΩ")}',
            _fmt_bool(data.get('r_iso_pass')),
        ],
        ['Schutzleiterstrom I_PE', _fmt_num(data.get('i_pe_ma'), 'mA'), '—', '—'],
        ['Berührungsstrom I_A', _fmt_num(data.get('i_touch_ma'), 'mA'), '—', '—'],
        ['Funktionsprüfung', _fmt_bool(data.get('function_ok')), '—', _fmt_bool(data.get('function_ok'))],
        [
            'Gesamtergebnis',
            _result_label(data.get('overall_result')),
            '—',
            _result_label(data.get('overall_result')),
        ],
    ]
    t3 = Table(measure_rows, colWidths=[5.0 * cm, 2.8 * cm, 3.2 * cm, usable - 11.0 * cm])
    t3.setStyle(_compact_table_style())
    story.append(t3)
    story.append(Spacer(1, 0.22 * cm))

    story.append(Paragraph('4. Digitale Signatur (FES/EES)', ps['section']))
    examiner = data.get('examiner_name') or '—'
    stamp_lines = [
        f'<b>Signed by "{examiner}"</b>',
        f"E-Mail: {data.get('examiner_email') or '—'}",
        f"Datum/Uhrzeit: {_fmt_date(data.get('signed_at') or data.get('exam_date'))}",
        f"Organisation (CA): {data.get('stamp_org') or '—'}",
        'Digital signiert (FES/EES, selbstsignierte Organisations-CA). Keine QES.',
    ]
    stamp_html = '<br/>'.join(stamp_lines)
    stamp_table = Table(
        [[Paragraph(stamp_html, ps.get('muted', ps['subtitle']))]],
        colWidths=[usable],
    )
    stamp_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1.0, PDF_COLORS['text']),
        ('BACKGROUND', (0, 0), (-1, -1), PDF_COLORS['header_bg']),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(stamp_table)
    # No extra spacer below stamp — bottomMargin reserves crypto signature area

    doc.build(story)
    return buffer.getvalue()
