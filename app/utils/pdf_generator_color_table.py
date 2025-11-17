from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from flask import current_app
from io import BytesIO
from datetime import datetime
from app.utils.pdf_generator import get_logo_path
from app.utils.color_mapping import get_all_color_mappings, initialize_color_mappings
from app.utils.lengths import format_length_from_meters


def generate_color_code_table_pdf(output=None):
    """
    Generiert eine Tabelle mit allen Längen-Farb-Zuordnungen.
    
    Args:
        output: BytesIO Objekt oder Dateipfad (optional)
    
    Returns:
        BytesIO Objekt mit PDF-Daten (falls output=None)
    """
    if output is None:
        output = BytesIO()
    
    # Initialisiere Farbzuordnungen falls nötig
    try:
        initialize_color_mappings()
    except Exception as e:
        current_app.logger.warning(f"Fehler beim Initialisieren der Farbzuordnungen: {e}")
        # Session zurücksetzen, damit weitere Operationen funktionieren
        from app import db
        db.session.rollback()
    
    doc = SimpleDocTemplate(output, pagesize=A4, 
                           leftMargin=2*cm, rightMargin=2*cm,
                           topMargin=2*cm, bottomMargin=2*cm)
    story = []
    
    styles = getSampleStyleSheet()
    
    # Header: Logo links, "Farbcodes" Text rechts daneben
    logo_path = get_logo_path()
    header_data = []
    
    if logo_path:
        try:
            logo = Image(logo_path, width=2.5*cm, height=2.5*cm, kind='proportional')
            header_data.append([logo])
        except Exception as e:
            current_app.logger.warning(f"Konnte Logo nicht laden: {e}")
            header_data.append([''])
    else:
        header_data.append([''])
    
    # "Farbcodes" Text daneben
    title_style = ParagraphStyle(
        'ColorCodesTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.black,
        alignment=TA_LEFT,
        fontName='Helvetica-Bold',
        leftIndent=0.5*cm
    )
    header_data[0].append(Paragraph("Farbcodes für Längen", title_style))
    
    header_table = Table(header_data, colWidths=[3*cm, 15*cm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'LEFT'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.5*cm))
    
    # Hole alle Farbzuordnungen
    mappings = get_all_color_mappings()
    
    if not mappings:
        # Keine Zuordnungen vorhanden
        no_data_style = ParagraphStyle(
            'NoData',
            parent=styles['Normal'],
            fontSize=12,
            textColor=colors.grey,
            alignment=TA_CENTER
        )
        story.append(Paragraph("Keine Farbzuordnungen vorhanden.", no_data_style))
    else:
        # Erstelle Tabelle mit Längen und Farben
        table_data = [['Länge', 'Farbe']]
        
        for length_meters, color_hex in sorted(mappings.items()):
            length_str = format_length_from_meters(length_meters) or f"{length_meters} m"
            table_data.append([length_str, ''])
        
        # Tabelle erstellen
        col_widths = [8*cm, 9*cm]
        color_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        
        # Tabellen-Styles
        table_style = [
            # Header
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 0), (-1, 0), 10),
            
            # Body
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 11),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            
            # Grid
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            
            # Padding
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ]
        
        # Füge Hintergrundfarben für jede Zeile hinzu
        row_idx = 1
        for length_meters, color_hex in sorted(mappings.items()):
            color_obj = colors.HexColor(color_hex)
            table_style.append(('BACKGROUND', (1, row_idx), (1, row_idx), color_obj))
            row_idx += 1
        
        color_table.setStyle(TableStyle(table_style))
        story.append(color_table)
    
    # Footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=TA_CENTER,
    )
    # Get portal name from SystemSettings
    try:
        from app.models.settings import SystemSettings
        portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
        app_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else current_app.config.get('APP_NAME', 'Prismateams')
    except:
        app_name = current_app.config.get('APP_NAME', 'Prismateams')
    footer_text = f"Erstellt am {datetime.now().strftime('%d.%m.%Y %H:%M')} - {app_name}"
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(footer_text, footer_style))
    
    # PDF bauen
    doc.build(story)
    
    if isinstance(output, BytesIO):
        output.seek(0)
        return output
    
    return output


