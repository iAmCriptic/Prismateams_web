from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from flask import current_app
from io import BytesIO
from datetime import datetime
import os
from PIL import Image as PILImage
from app.utils.qr_code import generate_qr_code_bytes, generate_product_qr_code, generate_borrow_qr_code


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
            product.length or '-',
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
    
    # PDF bauen
    doc.build(story)
    
    if isinstance(output, BytesIO):
        output.seek(0)
        return output
    
    return output


def generate_qr_code_sheet_pdf(products, output=None):
    """
    Generiert einen QR-Code-Druckbogen für mehrere Produkte als Labels.
    Jedes Label ist 4cm hoch × 2cm breit und enthält Produktname, Länge (optional) und QR-Code.
    
    Args:
        products: Liste von Product Objekten
        output: BytesIO Objekt oder Dateipfad (optional)
    
    Returns:
        BytesIO Objekt mit PDF-Daten (falls output=None)
    """
    if output is None:
        output = BytesIO()
    
    # A4-Seite: 21cm × 29.7cm
    # Ränder: 1.5cm links/rechts, 2cm oben/unten
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
    labels_style = ParagraphStyle(
        'LabelsTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.black,
        alignment=TA_LEFT,
        fontName='Helvetica-Bold',
        leftIndent=0.5*cm
    )
    header_data[0].append(Paragraph("Labels", labels_style))
    
    header_table = Table(header_data, colWidths=[3*cm, 15*cm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'LEFT'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.5*cm))
    
    # Label-Dimensionen - Exakt halbiert für Umklappen
    label_width = 1.9*cm  # Breite des Labels
    label_height = 3.8*cm  # Gesamthöhe (1.9cm + 1.9cm)
    text_height = 1.9*cm  # Obere Hälfte für Text (exakt 1.9cm)
    qr_height = 1.9*cm  # Untere Hälfte für QR-Code (exakt 1.9cm)
    qr_size = 1.9*cm  # QR-Code Größe (nutzt die volle untere Hälfte)
    
    # Berechne Anzahl Spalten pro Zeile (A4-Breite - Ränder = 18cm, bei 1.9cm pro Label)
    available_width = 21*cm - 3*cm  # A4-Breite minus linke/rechte Ränder
    cols_per_row = int(available_width / label_width)
    
    # Erstelle Labels für alle Produkte
    label_rows = []
    current_row = []
    
    for product in products:
        # QR-Code generieren
        qr_data = generate_product_qr_code(product.id)
        
        try:
            qr_bytes = generate_qr_code_bytes(qr_data, box_size=6)
            qr_image = Image(BytesIO(qr_bytes), width=qr_size, height=qr_size)
            
            # Produktname (einzeilig, kürzen falls zu lang)
            product_name = product.name
            if len(product_name) > 20:
                product_name = product_name[:17] + "..."
            
            # Erstelle Text-Inhalt für obere Hälfte
            text_elements = []
            
            # Produktname
            name_style = ParagraphStyle(
                'LabelName',
                parent=styles['Normal'],
                fontSize=8,
                textColor=colors.black,
                alignment=TA_CENTER,
                fontName='Helvetica-Bold',
                leading=10
            )
            text_elements.append(Paragraph(product_name, name_style))
            
            # Länge (wenn vorhanden)
            if product.length:
                length_style = ParagraphStyle(
                    'LabelLength',
                    parent=styles['Normal'],
                    fontSize=7,
                    textColor=colors.black,
                    alignment=TA_CENTER,
                    leading=9
                )
                text_elements.append(Paragraph(product.length, length_style))
            
            # Erstelle Label-Tabelle mit zwei Zeilen - jede exakt 1.9cm hoch
            # Zeile 1: Text-Bereich (exakt 1.9cm)
            # Zeile 2: QR-Code-Bereich (exakt 1.9cm)
            label_content = [
                [text_elements],  # Obere Hälfte: Text (1.9cm x 1.9cm)
                [qr_image]  # Untere Hälfte: QR-Code (1.9cm x 1.9cm)
            ]
            
            # Label-Tabelle erstellen mit gestrichelter Linie genau in der Mitte
            label_table = Table(label_content, colWidths=[label_width], rowHeights=[text_height, qr_height])
            label_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                # KEINE Padding-Werte, damit die Höhen exakt bleiben
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                # Gestrichelte Linie zwischen Text und QR-Code (genau in der Mitte bei 1.9cm)
                ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.black, 1, (2, 2)),  # Gestrichelt: 2pt Strich, 2pt Lücke
            ]))
            
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
        grid_table = Table(label_rows, colWidths=[label_width] * cols_per_row)
        grid_table.setStyle(TableStyle([
            # Rahmen um alle Labels
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            # Ausrichtung
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            # Höhe der Zeilen
            ('HEIGHT', (0, 0), (-1, -1), label_height),
        ]))
        story.append(grid_table)
    
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
            product.length or '-',
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

