from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, Flowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from flask import current_app
from io import BytesIO
from datetime import datetime
import os
from PIL import Image as PILImage
from app.utils.qr_code import generate_qr_code_bytes, generate_qr_code_inverted_bytes, generate_product_qr_code, generate_borrow_qr_code
from app.utils.lengths import format_length_from_meters, parse_length_to_meters
from app.utils.color_mapping import get_color_for_length, initialize_color_mappings


class DashedLine(Flowable):
    """Custom Flowable für gestrichelte Linien."""
    def __init__(self, width, height, color, dash_array=[3, 2], horizontal=True):
        Flowable.__init__(self)
        self.width = width
        self.height = height
        self.color = color
        self.dash_array = dash_array
        self.horizontal = horizontal
    
    def draw(self):
        """Zeichnet eine gestrichelte Linie."""
        self.canv.saveState()
        self.canv.setStrokeColor(self.color)
        self.canv.setDash(self.dash_array)
        self.canv.setLineWidth(0.5)
        
        if self.horizontal:
            # Horizontale Linie
            self.canv.line(0, self.height / 2, self.width, self.height / 2)
        else:
            # Vertikale Linie
            self.canv.line(self.width / 2, 0, self.width / 2, self.height)
        
        self.canv.restoreState()


def _format_length(value):
    """Gibt eine konsistente Meter-Darstellung zurück."""
    meters = parse_length_to_meters(value)
    if meters is None:
        return value or '-'
    formatted = format_length_from_meters(meters)
    return formatted or (value or '-')


def get_logo_path():
    """Holt den Pfad zum Portal-Logo aus SystemSettings oder Konfiguration."""
    # Try to get portal logo from SystemSettings first
    try:
        from app.models.settings import SystemSettings
        portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
        if portal_logo_setting and portal_logo_setting.value:
            # Portal logo is stored in uploads/system/
            project_root = os.path.dirname(current_app.root_path)
            logo_path = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'system', portal_logo_setting.value)
            if os.path.exists(logo_path):
                return logo_path
    except:
        pass
    
    # Fallback to config
    logo_path = current_app.config.get('APP_LOGO', 'static/img/logo.png')
    
    # Wenn der Pfad mit 'static/' beginnt, entferne es (Flask fügt es automatisch hinzu)
    if logo_path.startswith('static/'):
        logo_path = logo_path[7:]
    
    # Konvertiere zu absolutem Pfad
    static_folder = current_app.static_folder
    full_path = os.path.join(static_folder, logo_path)
    
    # Prüfe ob Logo existiert
    if os.path.exists(full_path):
        return full_path
    return None


def generate_borrow_receipt_pdf(borrow_transactions, output=None):
    """
    Generiert einen Ausleihschein als PDF im Rechnungsformat.
    Unterstützt sowohl einzelne als auch mehrere Transaktionen.
    
    Args:
        borrow_transactions: BorrowTransaction Objekt oder Liste von BorrowTransaction Objekten
        output: BytesIO Objekt oder Dateipfad (optional)
    
    Returns:
        BytesIO Objekt mit PDF-Daten (falls output=None)
    """
    if output is None:
        output = BytesIO()
    
    # Normalisiere zu Liste
    if not isinstance(borrow_transactions, list):
        borrow_transactions = [borrow_transactions]
    
    if not borrow_transactions:
        raise ValueError("Mindestens eine Transaktion erforderlich")
    
    doc = SimpleDocTemplate(output, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm, 
                           leftMargin=2*cm, rightMargin=2*cm)
    story = []
    
    styles = getSampleStyleSheet()
    
    # Get portal name from SystemSettings
    try:
        from app.models.settings import SystemSettings
        portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
        app_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else current_app.config.get('APP_NAME', 'Prismateams')
    except:
        app_name = current_app.config.get('APP_NAME', 'Prismateams')
    
    # Header mit Logo links und QR-Code rechts
    logo_path = get_logo_path()
    first_transaction = borrow_transactions[0]
    borrower = first_transaction.borrower
    
    # Header-Tabelle: Logo links, QR-Code rechts
    header_data = []
    header_row = []
    
    # Logo links - nur Breite angeben, Höhe wird proportional berechnet
    if logo_path:
        try:
            # Lade Logo mit PIL um natürliche Dimensionen zu erhalten
            pil_img = PILImage.open(logo_path)
            img_width, img_height = pil_img.size
            aspect_ratio = img_height / img_width
            
            # Setze maximale Breite, Höhe wird proportional berechnet
            max_width = 4*cm
            calculated_height = max_width * aspect_ratio
            
            # Begrenze maximale Höhe falls Logo sehr hoch ist
            max_height = 3*cm
            if calculated_height > max_height:
                calculated_height = max_height
                max_width = calculated_height / aspect_ratio
            
            logo = Image(logo_path, width=max_width, height=calculated_height)
            header_row.append(logo)
        except Exception as e:
            current_app.logger.warning(f"Konnte Logo nicht laden: {e}")
            header_row.append('')
    else:
        header_row.append('')
    
    # QR-Code rechts (erster QR-Code)
    qr_image = None
    if first_transaction.qr_code_data:
        try:
            qr_data = first_transaction.qr_code_data
            qr_bytes = generate_qr_code_bytes(qr_data, box_size=6)
            qr_image = Image(BytesIO(qr_bytes), width=3*cm, height=3*cm)
            header_row.append(qr_image)
        except Exception as e:
            current_app.logger.error(f"Fehler beim Generieren des QR-Codes: {e}")
            header_row.append('')
    else:
        header_row.append('')
    
    header_data.append(header_row)
    # Spaltenbreiten: Logo links (genug Platz für verschiedene Logo-Formate), QR-Code rechts
    header_table = Table(header_data, colWidths=[12*cm, 5*cm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.8*cm))
    
    # Titel "Ausleihschein"
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#0d6efd'),
        alignment=TA_LEFT,
        spaceAfter=15,
        fontName='Helvetica-Bold'
    )
    story.append(Paragraph("Ausleihschein", title_style))
    story.append(Spacer(1, 0.5*cm))
    
    # Briefkopf-Informationen
    briefkopf_style = ParagraphStyle(
        'Briefkopf',
        parent=styles['Normal'],
        fontSize=10,
        alignment=TA_LEFT,
        spaceAfter=5
    )
    
    # Ausleihender Information
    borrower_info = f"<b>Ausleihender:</b><br/>{borrower.first_name} {borrower.last_name}"
    if borrower.email:
        borrower_info += f"<br/>{borrower.email}"
    story.append(Paragraph(borrower_info, briefkopf_style))
    story.append(Spacer(1, 0.3*cm))
    
    # Ausleihdatum und Vorgangsnummer
    info_data = [
        ['Ausleihdatum:', first_transaction.borrow_date.strftime('%d.%m.%Y %H:%M')],
        ['Vorgangsnummer:', first_transaction.transaction_number],
        ['Voraussichtliche Rückgabe:', first_transaction.expected_return_date.strftime('%d.%m.%Y')],
        ['Bearbeitender Nutzer:', f"{first_transaction.borrowed_by.first_name} {first_transaction.borrowed_by.last_name}" if first_transaction.borrowed_by else '-'],
    ]
    
    info_table = Table(info_data, colWidths=[5*cm, 12*cm])
    info_table.setStyle(TableStyle([
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.8*cm))
    
    # Artikel-Tabelle (wie Rechnung)
    table_data = [['#', 'Produktname', 'Produkt-ID', 'Länge', 'Seriennummer']]
    
    for idx, transaction in enumerate(borrow_transactions, 1):
        product = transaction.product
        row = [
            str(idx),
            product.name or '-',
            str(product.id),
            _format_length(product.length),
            product.serial_number or '-'
        ]
        table_data.append(row)
    
    # Tabelle erstellen
    col_widths = [1*cm, 7*cm, 2.5*cm, 2.5*cm, 4*cm]
    items_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        
        # Body
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        
        # Grid
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        
        # Padding
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
    ]))
    
    story.append(items_table)
    story.append(Spacer(1, 0.8*cm))
    
    # Zusammenfassung
    summary_style = ParagraphStyle(
        'Summary',
        parent=styles['Normal'],
        fontSize=10,
        spaceBefore=10
    )
    summary_text = f"<b>Gesamtanzahl ausgeliehener Artikel:</b> {len(borrow_transactions)}"
    story.append(Paragraph(summary_text, summary_style))
    story.append(Spacer(1, 1*cm))
    
    # Footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=TA_CENTER,
    )
    footer_text = f"Erstellt am {datetime.now().strftime('%d.%m.%Y %H:%M')} - {app_name}"
    story.append(Paragraph(footer_text, footer_style))
    story.append(Spacer(1, 0.3*cm))
    
    # Elektronischer Hinweis
    electronic_note_style = ParagraphStyle(
        'ElectronicNote',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.black,
        alignment=TA_CENTER,
        spaceBefore=5,
    )
    electronic_note = "Dieses Dokument wurde elektronisch erstellt und ist ohne eine Unterschrift gültig."
    story.append(Paragraph(electronic_note, electronic_note_style))
    
    # PDF bauen
    doc.build(story)
    
    if isinstance(output, BytesIO):
        output.seek(0)
        return output
    
    return output


def generate_inventory_tool_pdf(inventory, items, output=None):
    """
    Generiert eine Inventurliste als PDF mit Checkboxen und Anmerkungsfeldern.
    
    Args:
        inventory: Inventory Objekt
        items: Liste von InventoryItem Objekten
        output: BytesIO Objekt oder Dateipfad (optional)
    
    Returns:
        BytesIO Objekt mit PDF-Daten (falls output=None)
    """
    if output is None:
        output = BytesIO()
    
    doc = SimpleDocTemplate(output, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
    story = []
    
    styles = getSampleStyleSheet()
    
    # Logo hinzufügen
    logo_path = get_logo_path()
    if logo_path:
        try:
            logo = Image(logo_path, width=3*cm, height=3*cm, kind='proportional')
            story.append(logo)
            story.append(Spacer(1, 0.3*cm))
        except Exception as e:
            current_app.logger.warning(f"Konnte Logo nicht laden: {e}")
    
    # Titel
    title_style = ParagraphStyle(
        'InventoryTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#0d6efd'),
        alignment=TA_CENTER,
        spaceAfter=10
    )
    story.append(Paragraph(f"Inventur: {inventory.name}", title_style))
    
    # Datum und Status
    date_style = ParagraphStyle(
        'Date',
        parent=styles['Normal'],
        fontSize=10,
        alignment=TA_CENTER,
        spaceAfter=5
    )
    story.append(Paragraph(f"Gestartet: {inventory.started_at.strftime('%d.%m.%Y %H:%M')}", date_style))
    if inventory.completed_at:
        story.append(Paragraph(f"Abgeschlossen: {inventory.completed_at.strftime('%d.%m.%Y %H:%M')}", date_style))
    story.append(Paragraph(f"Status: {'Abgeschlossen' if inventory.status == 'completed' else 'Aktiv'}", date_style))
    story.append(Spacer(1, 0.5*cm))
    
    # Tabellendaten vorbereiten
    # Spalten: #, Produktname, Kategorie, Lagerort, Zustand, Inventiert (Checkbox), Anmerkungen
    table_data = [['#', 'Produktname', 'Kategorie', 'Lagerort', 'Zustand', 'Inventiert', 'Anmerkungen']]
    
    for item in items:
        product = item.product
        # Checkbox als leeres Kästchen darstellen (□)
        checkbox = '☐' if not item.checked else '☑'
        
        table_data.append([
            str(product.id),
            product.name or '-',
            product.category or '-',
            product.location or '-',
            product.condition or '-',
            checkbox,
            item.notes or ''  # Anmerkungen können leer sein
        ])
    
    # Tabelle erstellen
    # Spaltenbreiten anpassen (A4 Breite: 21cm, abzüglich Ränder)
    available_width = 17*cm
    col_widths = [
        0.8*cm,  # #
        4*cm,    # Produktname
        2*cm,    # Kategorie
        2*cm,    # Lagerort
        1.5*cm,  # Zustand
        1.2*cm,  # Inventiert (Checkbox)
        5.5*cm   # Anmerkungen
    ]
    
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (5, 1), (5, -1), 'CENTER'),  # Checkbox zentrieren
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        
        # Body
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('FONTSIZE', (5, 1), (5, -1), 12),  # Größere Checkbox-Zeichen
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        
        # Anmerkungsfeld - mehr Platz für Text
        ('TOPPADDING', (6, 1), (6, -1), 4),
        ('BOTTOMPADDING', (6, 1), (6, -1), 4),
    ]))
    
    story.append(table)
    
    # Footer mit Seitenzahl
    story.append(Spacer(1, 0.5*cm))
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        alignment=TA_CENTER,
        textColor=colors.grey
    )
    story.append(Paragraph(f"Seite 1", footer_style))
    
    doc.build(story)
    return output


def generate_qr_code_sheet_pdf(products, output=None, label_type='cable'):
    """
    Generiert einen QR-Code-Druckbogen für mehrere Produkte als Labels.
    
    Args:
        products: Liste von Product Objekten
        output: BytesIO Objekt oder Dateipfad (optional)
        label_type: 'cable' oder 'device' (Standard: 'cable')
    
    Returns:
        BytesIO Objekt mit PDF-Daten (falls output=None)
    """
    if output is None:
        output = BytesIO()
    
    # Initialisiere Farbzuordnungen falls nötig
    # Wichtig: Auch bei Fehler fortfahren, damit Geräte-PDFs ohne Länge funktionieren
    try:
        initialize_color_mappings()
    except Exception as e:
        current_app.logger.warning(f"Fehler beim Initialisieren der Farbzuordnungen: {e}")
        # Session zurücksetzen, damit weitere Operationen funktionieren
        from app import db
        db.session.rollback()
    
    # A4-Seite: 21cm × 29.7cm
    # Ränder: 1.5cm links/rechts, 2cm oben/unten
    # Speichere Label-Parameter für Custom Template
    label_params = {
        'label_width': None,
        'label_height': None,
        'cols_per_row': None,
        'num_rows': None,
        'line_color': None,
        'label_type': label_type
    }
    
    doc = SimpleDocTemplate(output, pagesize=A4, 
                           leftMargin=1.5*cm, rightMargin=1.5*cm,
                           topMargin=2*cm, bottomMargin=2*cm)
    story = []
    
    styles = getSampleStyleSheet()
    
    # Header: Logo links, "Labels" Text rechts daneben
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
    
    # "Labels" Text daneben
    label_type_text = "Kabel-Labels" if label_type == 'cable' else "Geräte-Labels"
    labels_style = ParagraphStyle(
        'LabelsTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.black,
        alignment=TA_LEFT,
        fontName='Helvetica-Bold',
        leftIndent=0.5*cm
    )
    header_data[0].append(Paragraph(label_type_text, labels_style))
    
    header_table = Table(header_data, colWidths=[3*cm, 15*cm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'LEFT'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.5*cm))
    
    # Label-Dimensionen
    label_width = 1.9*cm  # Breite des Labels
    # Höhe abhängig vom Label-Typ: Kabel = 3.8cm, Geräte = 3.0cm (kompakter)
    label_height = 3.8*cm if label_type == 'cable' else 3.0*cm
    qr_size = 1.9*cm  # QR-Code Größe
    
    # Berechne Anzahl Spalten pro Zeile
    available_width = 21*cm - 3*cm  # A4-Breite minus linke/rechte Ränder
    cols_per_row = int(available_width / label_width)
    
    # Erstelle Labels für alle Produkte
    label_rows = []
    current_row = []
    
    for product in products:
        # QR-Code generieren
        qr_data = generate_product_qr_code(product.id)
        
        try:
            if label_type == 'cable':
                # Kabel-Label: Invertierter QR-Code
                qr_bytes = generate_qr_code_inverted_bytes(qr_data, box_size=6)
                qr_image = Image(BytesIO(qr_bytes), width=qr_size, height=qr_size)
                
                # Produktname (einzeilig, kürzen falls zu lang)
                product_name = product.name
                if len(product_name) > 20:
                    product_name = product_name[:17] + "..."
                
                # Hole Farbe für Länge
                color_hex = get_color_for_length(product.length) if product.length else None
                color_obj = colors.HexColor(color_hex) if color_hex else colors.black
                
                # Obere Hälfte: Farbstreifen (wenn Länge vorhanden) + Text
                # Wenn keine Länge: Komplett schwarz, kein Farbstreifen
                has_length = color_hex and product.length
                color_stripe_height = 0.4*cm if has_length else 0  # Höhe des Farbstreifens
                text_area_height = label_height - color_stripe_height - qr_size
                
                # Erstelle oberen Bereich mit Farbstreifen und Text
                top_elements = []
                if has_length:
                    # Farbstreifen oben (nur wenn Länge vorhanden)
                    color_stripe = Table([[Paragraph("", ParagraphStyle('Empty', parent=styles['Normal']))]], 
                                        colWidths=[label_width], rowHeights=[color_stripe_height])
                    color_stripe.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, -1), color_obj),
                        ('LEFTPADDING', (0, 0), (-1, -1), 0),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                        ('TOPPADDING', (0, 0), (-1, -1), 0),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                    ]))
                    top_elements.append(color_stripe)
                
                # Text-Bereich (weiß auf schwarz)
                text_elements = []
                name_style = ParagraphStyle(
                    'LabelName',
                    parent=styles['Normal'],
                    fontSize=8,
                    textColor=colors.white,
                    alignment=TA_CENTER,
                    fontName='Helvetica-Bold',
                    leading=10
                )
                text_elements.append(Paragraph(product_name, name_style))
                
                if product.length:
                    length_style = ParagraphStyle(
                        'LabelLength',
                        parent=styles['Normal'],
                        fontSize=7,
                        textColor=colors.white,
                        alignment=TA_CENTER,
                        leading=9
                    )
                    text_elements.append(Paragraph(_format_length(product.length), length_style))
                
                text_table = Table([[text_elements]], colWidths=[label_width], rowHeights=[text_area_height])
                text_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), colors.black),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                    ('TOPPADDING', (0, 0), (-1, -1), 0),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ]))
                top_elements.append(text_table)
                
                # Untere Hälfte: QR-Code auf schwarzem Hintergrund
                qr_table = Table([[qr_image]], colWidths=[label_width], rowHeights=[qr_size])
                qr_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), colors.black),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                    ('TOPPADDING', (0, 0), (-1, -1), 0),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ]))
                
                # Kombiniere alle Teile
                label_content = []
                for elem in top_elements:
                    label_content.append([elem])
                label_content.append([qr_table])
                
                row_heights = []
                if has_length:
                    row_heights.append(color_stripe_height)
                row_heights.append(text_area_height)
                row_heights.append(qr_size)
                
            else:
                # Geräte-Label: Normaler QR-Code
                qr_bytes = generate_qr_code_bytes(qr_data, box_size=6)
                qr_image = Image(BytesIO(qr_bytes), width=qr_size, height=qr_size)
                
                # Produktname (einzeilig, kürzen falls zu lang)
                product_name = product.name
                if len(product_name) > 20:
                    product_name = product_name[:17] + "..."
                
                # Obere Hälfte: QR-Code (angepasst für kompaktere Geräte-Labels)
                qr_area_height = 1.8*cm if label_type == 'device' else 2.0*cm
                qr_table = Table([[qr_image]], colWidths=[label_width], rowHeights=[qr_area_height])
                qr_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), colors.white),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                    ('TOPPADDING', (0, 0), (-1, -1), 0),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ]))
                
                # Untere Hälfte: Produktname
                name_area_height = label_height - qr_area_height
                name_style = ParagraphStyle(
                    'LabelName',
                    parent=styles['Normal'],
                    fontSize=8,
                    textColor=colors.black,
                    alignment=TA_CENTER,
                    fontName='Helvetica-Bold',
                    leading=10
                )
                name_table = Table([[Paragraph(product_name, name_style)]], colWidths=[label_width], rowHeights=[name_area_height])
                name_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), colors.white),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                    ('TOPPADDING', (0, 0), (-1, -1), 0),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ]))
                
                label_content = [
                    [qr_table],
                    [name_table]
                ]
                row_heights = [qr_area_height, name_area_height]
            
            # Label-Tabelle erstellen
            label_table = Table(label_content, colWidths=[label_width], rowHeights=row_heights)
            label_style = [
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]
            # Für Kabel-Labels: Komplett schwarzer Hintergrund (kein weißer Rand)
            if label_type == 'cable':
                label_style.append(('BACKGROUND', (0, 0), (-1, -1), colors.black))
            label_table.setStyle(TableStyle(label_style))
            
            # Label zur aktuellen Zeile hinzufügen
            current_row.append(label_table)
            
            # Wenn Zeile voll ist, zur Liste hinzufügen und neue Zeile starten
            if len(current_row) >= cols_per_row:
                label_rows.append(current_row)
                current_row = []
                
        except Exception as e:
            current_app.logger.error(f"Fehler beim Generieren des QR-Codes für Produkt {product.id}: {e}")
            # Fallback: Leeres Label mit Text
            fallback_style = ParagraphStyle(
                'LabelFallback',
                parent=styles['Normal'],
                fontSize=7,
                textColor=colors.red,
                alignment=TA_CENTER
            )
            fallback_content = [[Paragraph(f"Fehler: {product.name}", fallback_style)]]
            fallback_table = Table(fallback_content, colWidths=[label_width])
            current_row.append(fallback_table)
            
            if len(current_row) >= cols_per_row:
                label_rows.append(current_row)
                current_row = []
    
    # Restliche Labels in der letzten Zeile hinzufügen
    if current_row:
        # Fülle die letzte Zeile mit leeren Zellen auf, damit das Raster korrekt aussieht
        while len(current_row) < cols_per_row:
            current_row.append('')
        label_rows.append(current_row)
    
    # Raster-Tabelle mit allen Labels erstellen
    if label_rows:
        # Bestimme Linienfarbe basierend auf Label-Typ
        line_color = colors.white if label_type == 'cable' else colors.black
        
        # Speichere Parameter für Custom Template
        label_params['label_width'] = label_width
        label_params['label_height'] = label_height
        label_params['cols_per_row'] = cols_per_row
        label_params['num_rows'] = len(label_rows)
        label_params['line_color'] = line_color
        
        # Erstelle einfache Tabelle ohne GRID
        grid_table = Table(label_rows, colWidths=[label_width] * cols_per_row)
        grid_style = [
            # Ausrichtung
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            # Höhe der Zeilen
            ('HEIGHT', (0, 0), (-1, -1), label_height),
            # Kein Padding
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]
        grid_table.setStyle(TableStyle(grid_style))
        
        # Erstelle Custom Flowable, das die Tabelle und gestrichelte Linien rendert
        class TableWithDashedLines(Flowable):
            def __init__(self, table, label_width, label_height, cols_per_row, num_rows, line_color):
                Flowable.__init__(self)
                self.table = table
                self.label_width = label_width
                self.label_height = label_height
                self.cols_per_row = cols_per_row
                self.num_rows = num_rows
                self.line_color = line_color
                self.width = label_width * cols_per_row
                self.height = label_height * num_rows
            
            def wrap(self, availWidth, availHeight):
                """Wrappt die Tabelle und gibt die Größe zurück."""
                # Wrappe die Tabelle zuerst, damit sie später gezeichnet werden kann
                self.table.wrap(availWidth, availHeight)
                return (self.width, self.height)
            
            def draw(self):
                """Rendert die Tabelle und zeichnet dann die gestrichelten Linien."""
                # Rendere die Tabelle (sie wurde bereits in wrap() gewrappt)
                self.table.drawOn(self.canv, 0, 0)
                
                # Zeichne gestrichelte vertikale Linien
                self.canv.saveState()
                self.canv.setStrokeColor(self.line_color)
                self.canv.setDash([3, 2])  # 3pt Strich, 2pt Lücke
                self.canv.setLineWidth(0.5)
                
                for col in range(1, self.cols_per_row):
                    x = col * self.label_width
                    self.canv.line(x, 0, x, self.height)
                
                # Zeichne gestrichelte horizontale Linien
                for row in range(1, self.num_rows):
                    y = row * self.label_height
                    self.canv.line(0, y, self.width, y)
                
                self.canv.restoreState()
        
        # Verwende Custom Flowable für Tabelle mit gestrichelten Linien
        table_with_lines = TableWithDashedLines(
            grid_table, label_width, label_height, cols_per_row, len(label_rows), line_color
        )
        story.append(table_with_lines)
    
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
    
    from app.utils.color_mapping import get_all_color_mappings
    from app.utils.lengths import format_length_from_meters
    
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


def generate_inventory_list_pdf(products, output=None):
    """
    Generiert eine Inventurliste als PDF.
    
    Args:
        products: Liste von Product Objekten
        output: BytesIO Objekt oder Dateipfad (optional)
    
    Returns:
        BytesIO Objekt mit PDF-Daten (falls output=None)
    """
    if output is None:
        output = BytesIO()
    
    doc = SimpleDocTemplate(output, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
    story = []
    
    styles = getSampleStyleSheet()
    
    # Logo hinzufügen
    logo_path = get_logo_path()
    if logo_path:
        try:
            logo = Image(logo_path, width=3*cm, height=3*cm, kind='proportional')
            story.append(logo)
            story.append(Spacer(1, 0.3*cm))
        except Exception as e:
            current_app.logger.warning(f"Konnte Logo nicht laden: {e}")
    
    # Titel
    title_style = ParagraphStyle(
        'InventoryTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#0d6efd'),
        alignment=TA_CENTER,
        spaceAfter=10
    )
    story.append(Paragraph("Inventurliste", title_style))
    
    # Datum
    date_style = ParagraphStyle(
        'Date',
        parent=styles['Normal'],
        fontSize=10,
        alignment=TA_CENTER,
        spaceAfter=15
    )
    story.append(Paragraph(f"Stand: {datetime.now().strftime('%d.%m.%Y %H:%M')}", date_style))
    story.append(Spacer(1, 0.5*cm))
    
    # Tabellendaten vorbereiten
    table_data = [['#', 'Produktname', 'Kategorie', 'Seriennummer', 'Lagerort', 'Länge', 'Status', 'Zustand']]
    
    for product in products:
        status_text = 'Verfügbar' if product.status == 'available' else ('Ausgeliehen' if product.status == 'borrowed' else 'Fehlend')
        table_data.append([
            str(product.id),
            product.name or '-',
            product.category or '-',
            product.serial_number or '-',
            product.location or '-',
            _format_length(product.length),
            status_text,
            product.condition or '-'
        ])
    
    # Tabelle erstellen
    # Spaltenbreiten anpassen (A4 Breite: 21cm, abzüglich Ränder)
    available_width = 17*cm
    col_widths = [
        0.8*cm,  # #
        5*cm,    # Produktname
        2.5*cm,  # Kategorie
        2.5*cm,  # Seriennummer
        2*cm,    # Lagerort
        1.5*cm,  # Länge
        2*cm,    # Status
        2*cm     # Zustand
    ]
    
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        
        # Body
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        
        # Padding
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
    ]))
    
    story.append(table)
    story.append(Spacer(1, 0.5*cm))
    
    # Zusammenfassung
    available_count = sum(1 for p in products if p.status == 'available')
    borrowed_count = sum(1 for p in products if p.status == 'borrowed')
    missing_count = sum(1 for p in products if p.status == 'missing')
    total_count = len(products)
    
    summary_style = ParagraphStyle(
        'Summary',
        parent=styles['Normal'],
        fontSize=9,
        spaceBefore=10
    )
    
    summary_text = f"<b>Zusammenfassung:</b> Gesamt: {total_count} | Verfügbar: {available_count} | Ausgeliehen: {borrowed_count} | Fehlend: {missing_count}"
    story.append(Paragraph(summary_text, summary_style))
    
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


def generate_inventory_tool_pdf(inventory, items, output=None):
    """
    Generiert eine Inventurliste als PDF mit Checkboxen und Anmerkungsfeldern.
    
    Args:
        inventory: Inventory Objekt
        items: Liste von InventoryItem Objekten
        output: BytesIO Objekt oder Dateipfad (optional)
    
    Returns:
        BytesIO Objekt mit PDF-Daten (falls output=None)
    """
    if output is None:
        output = BytesIO()
    
    doc = SimpleDocTemplate(output, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
    story = []
    
    styles = getSampleStyleSheet()
    
    # Logo hinzufügen
    logo_path = get_logo_path()
    if logo_path:
        try:
            logo = Image(logo_path, width=3*cm, height=3*cm, kind='proportional')
            story.append(logo)
            story.append(Spacer(1, 0.3*cm))
        except Exception as e:
            current_app.logger.warning(f"Konnte Logo nicht laden: {e}")
    
    # Titel
    title_style = ParagraphStyle(
        'InventoryTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#0d6efd'),
        alignment=TA_CENTER,
        spaceAfter=10
    )
    story.append(Paragraph(f"Inventur: {inventory.name}", title_style))
    
    # Datum und Status
    date_style = ParagraphStyle(
        'Date',
        parent=styles['Normal'],
        fontSize=10,
        alignment=TA_CENTER,
        spaceAfter=5
    )
    story.append(Paragraph(f"Gestartet: {inventory.started_at.strftime('%d.%m.%Y %H:%M')}", date_style))
    if inventory.completed_at:
        story.append(Paragraph(f"Abgeschlossen: {inventory.completed_at.strftime('%d.%m.%Y %H:%M')}", date_style))
    story.append(Paragraph(f"Status: {'Abgeschlossen' if inventory.status == 'completed' else 'Aktiv'}", date_style))
    story.append(Spacer(1, 0.5*cm))
    
    # Tabellendaten vorbereiten
    # Spalten: #, Produktname, Kategorie, Lagerort, Zustand, Inventiert (Checkbox), Anmerkungen
    table_data = [['#', 'Produktname', 'Kategorie', 'Lagerort', 'Zustand', 'Inventiert', 'Anmerkungen']]
    
    for item in items:
        product = item.product
        # Checkbox als leeres Kästchen darstellen (□)
        checkbox = '☐' if not item.checked else '☑'
        
        table_data.append([
            str(product.id),
            product.name or '-',
            product.category or '-',
            product.location or '-',
            product.condition or '-',
            checkbox,
            item.notes or ''  # Anmerkungen können leer sein
        ])
    
    # Tabelle erstellen
    # Spaltenbreiten anpassen (A4 Breite: 21cm, abzüglich Ränder)
    available_width = 17*cm
    col_widths = [
        0.8*cm,  # #
        4*cm,    # Produktname
        2*cm,    # Kategorie
        2*cm,    # Lagerort
        1.5*cm,  # Zustand
        1.2*cm,  # Inventiert (Checkbox)
        5.5*cm   # Anmerkungen
    ]
    
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (5, 1), (5, -1), 'CENTER'),  # Checkbox zentrieren
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        
        # Body
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('FONTSIZE', (5, 1), (5, -1), 12),  # Größere Checkbox-Zeichen
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        
        # Anmerkungsfeld - mehr Platz für Text
        ('TOPPADDING', (6, 1), (6, -1), 4),
        ('BOTTOMPADDING', (6, 1), (6, -1), 4),
    ]))
    
    story.append(table)
    
    # Footer mit Seitenzahl
    story.append(Spacer(1, 0.5*cm))
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        alignment=TA_CENTER,
        textColor=colors.grey
    )
    story.append(Paragraph(f"Seite 1", footer_style))
    
    doc.build(story)
    return output


def generate_return_confirmation_pdf(borrow_transaction, output=None):
    """
    Generiert eine Rückgabe-Bestätigung als PDF.
    
    Args:
        borrow_transaction: BorrowTransaction Objekt
        output: BytesIO Objekt oder Dateipfad (optional)
    
    Returns:
        BytesIO Objekt mit PDF-Daten (falls output=None)
    """
    if output is None:
        output = BytesIO()
    
    doc = SimpleDocTemplate(output, pagesize=A4)
    story = []
    
    styles = getSampleStyleSheet()
    
    # Logo hinzufügen
    logo_path = get_logo_path()
    if logo_path:
        try:
            logo = Image(logo_path, width=3*cm, height=3*cm, kind='proportional')
            story.append(logo)
            story.append(Spacer(1, 0.5*cm))
        except Exception as e:
            current_app.logger.warning(f"Konnte Logo nicht laden: {e}")
    
    # Titel
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#198754'),
        alignment=TA_CENTER,
        spaceAfter=20
    )
    story.append(Paragraph("Rückgabe-Bestätigung", title_style))
    story.append(Spacer(1, 0.5*cm))
    
    # Daten für Tabelle vorbereiten
    # Get portal name from SystemSettings
    try:
        from app.models.settings import SystemSettings
        portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
        app_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else current_app.config.get('APP_NAME', 'Prismateams')
    except:
        app_name = current_app.config.get('APP_NAME', 'Prismateams')
    product = borrow_transaction.product
    borrower = borrow_transaction.borrower
    
    # Tabellendaten
    data = [
        ['Produkt:', product.name],
        ['Ausleihender:', f"{borrower.first_name} {borrower.last_name}"],
        ['Ausleihvorgangsnummer:', borrow_transaction.transaction_number],
        ['Rückgabedatum:', borrow_transaction.actual_return_date.strftime('%d.%m.%Y') if borrow_transaction.actual_return_date else datetime.now().strftime('%d.%m.%Y')],
        ['Bearbeitender Nutzer:', f"{borrow_transaction.borrowed_by.first_name} {borrow_transaction.borrowed_by.last_name}" if borrow_transaction.borrowed_by else '-'],
    ]
    
    if product.serial_number:
        data.insert(1, ['Seriennummer:', product.serial_number])
    
    if product.category:
        data.insert(1, ['Kategorie:', product.category])
    
    # Tabelle erstellen
    table = Table(data, colWidths=[6*cm, 12*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#E8F5E9')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
    ]))
    
    story.append(table)
    story.append(Spacer(1, 1*cm))
    
    # Erfolgs-Hinweis
    success_text = Paragraph(
        "<b>✓ Rückgabe erfolgreich registriert</b><br/>Vielen Dank für die pünktliche Rückgabe!",
        ParagraphStyle(
            'Success',
            parent=styles['Normal'],
            fontSize=11,
            textColor=colors.HexColor('#198754'),
            spaceBefore=10
        )
    )
    story.append(success_text)
    
    story.append(Spacer(1, 1*cm))
    
    # Footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=TA_CENTER,
    )
    footer_text = f"Erstellt am {datetime.now().strftime('%d.%m.%Y %H:%M')} - {app_name}"
    story.append(Paragraph(footer_text, footer_style))
    
    # PDF bauen
    doc.build(story)
    
    if isinstance(output, BytesIO):
        output.seek(0)
        return output
    
    return output


def generate_inventory_tool_pdf(inventory, items, output=None):
    """
    Generiert eine Inventurliste als PDF mit Checkboxen und Anmerkungsfeldern.
    
    Args:
        inventory: Inventory Objekt
        items: Liste von InventoryItem Objekten
        output: BytesIO Objekt oder Dateipfad (optional)
    
    Returns:
        BytesIO Objekt mit PDF-Daten (falls output=None)
    """
    if output is None:
        output = BytesIO()
    
    doc = SimpleDocTemplate(output, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
    story = []
    
    styles = getSampleStyleSheet()
    
    # Logo hinzufügen
    logo_path = get_logo_path()
    if logo_path:
        try:
            logo = Image(logo_path, width=3*cm, height=3*cm, kind='proportional')
            story.append(logo)
            story.append(Spacer(1, 0.3*cm))
        except Exception as e:
            current_app.logger.warning(f"Konnte Logo nicht laden: {e}")
    
    # Titel
    title_style = ParagraphStyle(
        'InventoryTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#0d6efd'),
        alignment=TA_CENTER,
        spaceAfter=10
    )
    story.append(Paragraph(f"Inventur: {inventory.name}", title_style))
    
    # Datum und Status
    date_style = ParagraphStyle(
        'Date',
        parent=styles['Normal'],
        fontSize=10,
        alignment=TA_CENTER,
        spaceAfter=5
    )
    story.append(Paragraph(f"Gestartet: {inventory.started_at.strftime('%d.%m.%Y %H:%M')}", date_style))
    if inventory.completed_at:
        story.append(Paragraph(f"Abgeschlossen: {inventory.completed_at.strftime('%d.%m.%Y %H:%M')}", date_style))
    story.append(Paragraph(f"Status: {'Abgeschlossen' if inventory.status == 'completed' else 'Aktiv'}", date_style))
    story.append(Spacer(1, 0.5*cm))
    
    # Tabellendaten vorbereiten
    # Spalten: #, Produktname, Kategorie, Lagerort, Zustand, Inventiert (Checkbox), Anmerkungen
    table_data = [['#', 'Produktname', 'Kategorie', 'Lagerort', 'Zustand', 'Inventiert', 'Anmerkungen']]
    
    for item in items:
        product = item.product
        # Checkbox als leeres Kästchen darstellen (□)
        checkbox = '☐' if not item.checked else '☑'
        
        table_data.append([
            str(product.id),
            product.name or '-',
            product.category or '-',
            product.location or '-',
            product.condition or '-',
            checkbox,
            item.notes or ''  # Anmerkungen können leer sein
        ])
    
    # Tabelle erstellen
    # Spaltenbreiten anpassen (A4 Breite: 21cm, abzüglich Ränder)
    available_width = 17*cm
    col_widths = [
        0.8*cm,  # #
        4*cm,    # Produktname
        2*cm,    # Kategorie
        2*cm,    # Lagerort
        1.5*cm,  # Zustand
        1.2*cm,  # Inventiert (Checkbox)
        5.5*cm   # Anmerkungen
    ]
    
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (5, 1), (5, -1), 'CENTER'),  # Checkbox zentrieren
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        
        # Body
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('FONTSIZE', (5, 1), (5, -1), 12),  # Größere Checkbox-Zeichen
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        
        # Anmerkungsfeld - mehr Platz für Text
        ('TOPPADDING', (6, 1), (6, -1), 4),
        ('BOTTOMPADDING', (6, 1), (6, -1), 4),
    ]))
    
    story.append(table)
    
    # Footer mit Seitenzahl
    story.append(Spacer(1, 0.5*cm))
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        alignment=TA_CENTER,
        textColor=colors.grey
    )
    story.append(Paragraph(f"Seite 1", footer_style))
    
    doc.build(story)
    return output

