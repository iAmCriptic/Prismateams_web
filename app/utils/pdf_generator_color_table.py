from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from flask import current_app
from datetime import datetime
from app.utils.pdf_generator import build_standard_header, build_standard_pdf
from app.utils.color_mapping import get_all_color_mappings, initialize_color_mappings
from app.utils.lengths import format_length_from_meters


def generate_color_code_table_pdf(output=None):
    """
    Generiert eine Tabelle mit allen Längen-Farb-Zuordnungen.
    Einheitliches Layout: Portal-Logo, blauer Titel, Standard-Footer.
    """
    try:
        initialize_color_mappings()
    except Exception as e:
        current_app.logger.warning(f"Fehler beim Initialisieren der Farbzuordnungen: {e}")
        from app import db
        db.session.rollback()

    styles = getSampleStyleSheet()
    stand = datetime.now().strftime('%d.%m.%Y')
    story = [
        build_standard_header(
            "Farbcodes für Längen",
            subtitle=f"Stand: {stand}",
            pagesize=A4,
            logo_size=2.0 * cm,
        ),
        Spacer(1, 0.4 * cm),
    ]

    mappings = get_all_color_mappings()

    if not mappings:
        no_data_style = ParagraphStyle(
            'NoData',
            parent=styles['Normal'],
            fontSize=12,
            textColor=colors.HexColor('#6c757d'),
            alignment=TA_CENTER,
        )
        story.append(Paragraph("Keine Farbzuordnungen vorhanden.", no_data_style))
    else:
        table_data = [['Länge', 'Farbe']]
        for length_meters, _color_hex in sorted(mappings.items()):
            length_str = format_length_from_meters(length_meters) or f"{length_meters} m"
            table_data.append([length_str, ''])

        color_table = Table(table_data, colWidths=[8 * cm, 9 * cm], repeatRows=1)
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#adb5bd')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        ]
        row_idx = 1
        for _length_meters, color_hex in sorted(mappings.items()):
            style_cmds.append(('BACKGROUND', (1, row_idx), (1, row_idx), colors.HexColor(color_hex)))
            row_idx += 1
        color_table.setStyle(TableStyle(style_cmds))
        story.append(color_table)

    return build_standard_pdf(story, pagesize=A4, output=output)
