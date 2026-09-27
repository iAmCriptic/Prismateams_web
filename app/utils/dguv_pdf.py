"""DGUV V3 Prüfprotokoll PDF (ReportLab) + visual FES stamp."""

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


def generate_dguv_exam_pdf(data: dict[str, Any]) -> bytes:
    """
    Build unsigned DGUV V3 protocol PDF bytes.

    Expected keys (subset): product_*, examiner_*, device_*, measurements,
    overall_result, exam_date, next_exam_date, interval_months, signed_stamp_*.
    """
    buffer = BytesIO()
    from reportlab.platypus import SimpleDocTemplate

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.5 * cm,
        bottomMargin=2 * cm,
    )
    ps = pdf_paragraph_styles()
    story = []
    usable = A4[0] - 4 * cm

    story.append(build_standard_header(
        'DGUV V3 Prüfprotokoll',
        subtitle='nach DIN VDE 0701-0702 / EN 50678 & EN 50699',
        pagesize=A4,
        content_width=usable,
    ))
    story.append(Spacer(1, 0.4 * cm))

    # Block 1 – Stammdaten
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
    t1 = Table(product_rows, colWidths=[5 * cm, usable - 5 * cm])
    t1.setStyle(standard_table_style(header=True))
    story.append(t1)
    story.append(Spacer(1, 0.35 * cm))

    # Block 2 – Prüfgerät
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
    t2 = Table(device_rows, colWidths=[5 * cm, usable - 5 * cm])
    t2.setStyle(standard_table_style(header=True))
    story.append(t2)
    story.append(Spacer(1, 0.35 * cm))

    # Block 3 – Messwerte
    story.append(Paragraph('3. Messwerte & Beurteilungen', ps['section']))
    r_pe = data.get('r_pe_ohm')
    r_iso = data.get('r_iso_mohm')
    r_pe_limit = data.get('r_pe_limit', 0.3)
    r_iso_limit = data.get('r_iso_limit', 1.0)
    measure_rows = [
        ['Prüfung', 'Istwert', 'Grenzwert', 'Beurteilung'],
        [
            'Sichtprüfung',
            _fmt_bool(data.get('visual_ok')),
            '—',
            _fmt_bool(data.get('visual_ok')),
        ],
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
        [
            'Schutzleiterstrom I_PE',
            _fmt_num(data.get('i_pe_ma'), 'mA'),
            '—',
            '—',
        ],
        [
            'Berührungsstrom I_A',
            _fmt_num(data.get('i_touch_ma'), 'mA'),
            '—',
            '—',
        ],
        [
            'Funktionsprüfung',
            _fmt_bool(data.get('function_ok')),
            '—',
            _fmt_bool(data.get('function_ok')),
        ],
        [
            'Gesamtergebnis',
            _result_label(data.get('overall_result')),
            '—',
            _result_label(data.get('overall_result')),
        ],
    ]
    t3 = Table(measure_rows, colWidths=[5.2 * cm, 3.2 * cm, 3.5 * cm, usable - 11.9 * cm])
    t3.setStyle(standard_table_style(header=True))
    story.append(t3)
    story.append(Spacer(1, 0.5 * cm))

    # Block 4 – Visueller FES-Stempel
    story.append(Paragraph('4. Digitale Signatur (FES/EES)', ps['section']))
    stamp_lines = [
        f"<b>{data.get('stamp_org') or 'Organisation'}</b>",
        f"Prüfer: {data.get('examiner_name') or '—'}",
        f"E-Mail: {data.get('examiner_email') or '—'}",
        f"Datum/Uhrzeit: {_fmt_date(data.get('signed_at') or data.get('exam_date'))}",
        'Digital signiert (FES/EES, organisationsbezogen, selbstsigniertes Zertifikat)',
        'Keine qualifizierte Signatur (QES).',
    ]
    stamp_html = '<br/>'.join(stamp_lines)
    stamp_table = Table(
        [[Paragraph(stamp_html, ps.get('body', ps['subtitle']))]],
        colWidths=[usable],
    )
    stamp_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1.2, PDF_COLORS['text']),
        ('BACKGROUND', (0, 0), (-1, -1), PDF_COLORS['header_bg']),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(stamp_table)
    story.append(Spacer(1, 1.2 * cm))
    story.append(Paragraph(
        'Unterhalb dieses Bereichs wird die kryptographische PDF-Signatur eingebettet.',
        ps['subtitle'],
    ))

    doc.build(story)
    return buffer.getvalue()
