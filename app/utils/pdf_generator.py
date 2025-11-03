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


def generate_borrow_receipt_pdf(borrow_transaction, output=None):
    """
    Generiert einen Ausleihschein als PDF.
    
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
            # Logo auf 3cm Breite skalieren
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
        textColor=colors.HexColor('#0d6efd'),
        alignment=TA_CENTER,
        spaceAfter=20
    )
    story.append(Paragraph("Ausleihschein", title_style))
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
        ['Ausleihvorgangsnummer:', borrow_transaction.transaction_number],
        ['Produkt:', product.name],
        ['Ausleihender:', f"{borrower.first_name} {borrower.last_name}"],
        ['Ausleihdatum:', borrow_transaction.borrow_date.strftime('%d.%m.%Y %H:%M')],
        ['Erwartetes Rückgabedatum:', borrow_transaction.expected_return_date.strftime('%d.%m.%Y')],
    ]
    
    if product.serial_number:
        data.insert(2, ['Seriennummer:', product.serial_number])
    
    if product.category:
        data.insert(2, ['Kategorie:', product.category])
    
    # Tabelle erstellen
    table = Table(data, colWidths=[6*cm, 12*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8f9fa')),
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
    
    # QR-Code für Ausleihvorgang generieren
    if borrow_transaction.qr_code_data:
        try:
            qr_data = borrow_transaction.qr_code_data
            qr_bytes = generate_qr_code_bytes(qr_data, box_size=8)
            
            # QR-Code als Image speichern
            qr_image = Image(BytesIO(qr_bytes), width=4*cm, height=4*cm)
            story.append(qr_image)
            story.append(Spacer(1, 0.2*cm))
            story.append(Paragraph(f"<b>QR-Code:</b> {qr_data}", styles['Normal']))
        except Exception as e:
            current_app.logger.error(f"Fehler beim Generieren des QR-Codes: {e}")
    
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
    Generiert einen QR-Code-Druckbogen für mehrere Produkte.
    Jeder QR-Code ist maximal 2x2 cm groß und wird direkt über dem Produktnamen angezeigt.
    
    Args:
        products: Liste von Product Objekten
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
            story.append(Spacer(1, 0.3*cm))
        except Exception as e:
            current_app.logger.warning(f"Konnte Logo nicht laden: {e}")
    
    # Titel
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#0d6efd'),
        alignment=TA_CENTER,
        spaceAfter=15
    )
    story.append(Paragraph("QR-Code-Druckbogen", title_style))
    story.append(Spacer(1, 0.5*cm))
    
    # QR-Codes für jedes Produkt generieren
    qr_size = 2*cm  # Maximal 2x2 cm
    
    for i, product in enumerate(products):
        # QR-Code generieren
        qr_data = generate_product_qr_code(product.id)
        
        try:
            qr_bytes = generate_qr_code_bytes(qr_data, box_size=6)
            qr_image = Image(BytesIO(qr_bytes), width=qr_size, height=qr_size)
            
            # Container für QR-Code und Text erstellen
            product_data = [
                [qr_image],
                [Paragraph(f"<b>{product.name}</b>", styles['Normal'])]
            ]
            
            if product.serial_number:
                product_data.append([Paragraph(f"SN: {product.serial_number}", styles['Normal'])])
            
            product_table = Table(product_data, colWidths=[qr_size])
            product_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
            ]))
            
            story.append(product_table)
            story.append(Spacer(1, 0.5*cm))
            
            # Jeden zweiten QR-Code in eine neue Zeile (optional: für bessere Platzausnutzung)
            # Hier einfach untereinander
            
        except Exception as e:
            current_app.logger.error(f"Fehler beim Generieren des QR-Codes für Produkt {product.id}: {e}")
            # Fallback: Nur Text
            story.append(Paragraph(f"<b>{product.name}</b> - {qr_data}", styles['Normal']))
            story.append(Spacer(1, 0.3*cm))
    
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

