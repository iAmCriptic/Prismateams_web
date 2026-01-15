from reportlab.lib.pagesizes import A4, A5, letter
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


def generate_music_wish_pdf(public_url, output=None):
    """
    Generiert eine A5-PDF für Musikwünsche mit QR-Code und Link.
    
    Args:
        public_url: Die öffentliche URL zur Wunschliste
        output: BytesIO Objekt oder Dateipfad (optional)
    
    Returns:
        BytesIO Objekt mit PDF-Daten (falls output=None)
    """
    if output is None:
        output = BytesIO()
    
    # A5-Seitengröße: 148 x 210 mm
    doc = SimpleDocTemplate(output, pagesize=A5, 
                           leftMargin=1.5*cm, rightMargin=1.5*cm,
                           topMargin=1.5*cm, bottomMargin=1.5*cm)
    story = []
    
    styles = getSampleStyleSheet()
    
    # Logo oben links
    logo_path = get_logo_path()
    if logo_path:
        try:
            logo = Image(logo_path, width=2.5*cm, height=2.5*cm, kind='proportional')
            # Logo linksbündig positionieren
            logo_table = Table([[logo]], colWidths=[2.5*cm], rowHeights=[2.5*cm])
            logo_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            story.append(logo_table)
            story.append(Spacer(1, 0.5*cm))
        except Exception as e:
            current_app.logger.warning(f"Konnte Logo nicht laden: {e}")
    
    # Überschrift "Musikwünsche?"
    title_style = ParagraphStyle(
        'MusicWishTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#0d6efd'),
        alignment=TA_CENTER,
        spaceAfter=0.8*cm,
        fontName='Helvetica-Bold'
    )
    story.append(Paragraph("Musikwünsche?", title_style))
    
    # Untertitel "Hier Scannen und Suchen"
    subtitle_style = ParagraphStyle(
        'MusicWishSubtitle',
        parent=styles['Normal'],
        fontSize=14,
        textColor=colors.black,
        alignment=TA_CENTER,
        spaceAfter=1.2*cm,
        fontName='Helvetica'
    )
    story.append(Paragraph("Hier Scannen und Suchen", subtitle_style))
    
    # QR-Code generieren
    qr_bytes = generate_qr_code_bytes(public_url, box_size=8, border=4)
    qr_image = Image(BytesIO(qr_bytes), width=6*cm, height=6*cm)
    
    # QR-Code zentriert
    qr_table = Table([[qr_image]], colWidths=[6*cm], rowHeights=[6*cm])
    qr_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(qr_table)
    story.append(Spacer(1, 0.8*cm))
    
    # Link in Klartext
    link_style = ParagraphStyle(
        'MusicWishLink',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#0d6efd'),
        alignment=TA_CENTER,
        spaceAfter=0,
        fontName='Helvetica',
        wordWrap='CJK'
    )
    # Link auf mehrere Zeilen aufteilen falls zu lang
    link_text = public_url
    story.append(Paragraph(link_text, link_style))
    
    doc.build(story)
    return output


def generate_borrow_receipt_pdf(borrow_transactions, output=None):
    """
    Generiert einen Ausleihschein-PDF für eine oder mehrere Ausleihen.
    
    Args:
        borrow_transactions: Einzelne BorrowTransaction oder Liste von BorrowTransaction-Objekten
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
        raise ValueError("Keine Ausleihvorgänge zum Generieren des PDFs vorhanden.")
    
    doc = SimpleDocTemplate(output, pagesize=A4, 
                           leftMargin=2*cm, rightMargin=2*cm,
                           topMargin=2*cm, bottomMargin=2*cm)
    story = []
    
    styles = getSampleStyleSheet()
    
    # Header: Logo und Titel
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
    
    # Get portal name from SystemSettings
    try:
        from app.models.settings import SystemSettings
        portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
        app_name = portal_name_setting.value if portal_name_setting and portal_name_setting.value else current_app.config.get('APP_NAME', 'Prismateams')
    except:
        app_name = current_app.config.get('APP_NAME', 'Prismateams')
    
    title_style = ParagraphStyle(
        'BorrowReceiptTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.black,
        alignment=TA_LEFT,
        fontName='Helvetica-Bold',
        leftIndent=0.5*cm
    )
    header_data[0].append(Paragraph("Ausleihschein", title_style))
    
    header_table = Table(header_data, colWidths=[3*cm, 15*cm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'LEFT'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.5*cm))
    
    # Ausleihdetails
    first_transaction = borrow_transactions[0]
    borrower = first_transaction.borrower
    
    normal_style = ParagraphStyle(
        'Normal',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.black,
        alignment=TA_LEFT,
        fontName='Helvetica'
    )
    
    details_data = [
        ['Ausleihdatum:', first_transaction.borrow_date.strftime('%d.%m.%Y %H:%M')],
        ['Vorgangsnummer:', first_transaction.transaction_number],
        ['Voraussichtliche Rückgabe:', first_transaction.expected_return_date.strftime('%d.%m.%Y')],
        ['Ausleiher:', f"{borrower.first_name} {borrower.last_name}"],
    ]
    
    if borrower.email:
        details_data.append(['E-Mail:', borrower.email])
    
    details_table = Table(details_data, colWidths=[6*cm, 10*cm])
    details_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(details_table)
    story.append(Spacer(1, 0.8*cm))
    
    # Produktliste
    items_header_style = ParagraphStyle(
        'ItemsHeader',
        parent=styles['Normal'],
        fontSize=14,
        textColor=colors.black,
        alignment=TA_LEFT,
        fontName='Helvetica-Bold',
        spaceAfter=0.3*cm
    )
    story.append(Paragraph("Ausgeliehene Artikel:", items_header_style))
    
    items_data = [['Nr.', 'Produktname', 'Produkt-ID', 'Länge']]
    
    for idx, transaction in enumerate(borrow_transactions, 1):
        product = transaction.product
        length_str = _format_length(product.length) if product.length else '-'
        items_data.append([
            str(idx),
            product.name or '-',
            str(product.id),
            length_str
        ])
    
    items_table = Table(items_data, colWidths=[1.5*cm, 8*cm, 3*cm, 3.5*cm], repeatRows=1)
    items_table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        
        # Body
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        
        # Grid
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        
        # Padding
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 1), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 0.8*cm))
    
    # Hinweis
    # Verwende Helvetica statt Helvetica-Italic, da Helvetica-Italic Unicode-Zeichen 
    # (z.B. "ü" in "Rückgabedatum") nicht korrekt darstellen kann.
    # Die Hervorhebung erfolgt bereits über Farbe und Einrückung.
    note_style = ParagraphStyle(
        'Note',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#666666'),
        alignment=TA_LEFT,
        fontName='Helvetica',
        leftIndent=0.5*cm,
        rightIndent=0.5*cm
    )
    story.append(Paragraph(
        f"Bitte beachten Sie das voraussichtliche Rückgabedatum: {first_transaction.expected_return_date.strftime('%d.%m.%Y')}",
        note_style
    ))
    
    # Footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=TA_CENTER,
    )
    footer_text = f"Erstellt am {datetime.now().strftime('%d.%m.%Y %H:%M')} - {app_name}"
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(footer_text, footer_style))
    
    doc.build(story)
    
    if isinstance(output, BytesIO):
        output.seek(0)
        return output
    
    return output


def generate_qr_code_sheet_pdf(products, output=None, label_type='cable'):
    """
    Generiert einen QR-Code-Druckbogen für Produkte.
    
    Args:
        products: Liste von Product-Objekten
        output: BytesIO Objekt oder Dateipfad (optional)
        label_type: 'cable' oder 'device' - bestimmt das Layout
    
    Returns:
        BytesIO Objekt mit PDF-Daten (falls output=None)
    """
    if output is None:
        output = BytesIO()
    
    if not products:
        raise ValueError("Keine Produkte zum Generieren des QR-Code-Druckbogens vorhanden.")
    
    # A4-Seitengröße
    doc = SimpleDocTemplate(output, pagesize=A4, 
                           leftMargin=1*cm, rightMargin=1*cm,
                           topMargin=1*cm, bottomMargin=1*cm)
    story = []
    
    styles = getSampleStyleSheet()
    
    # QR-Code-Größe basierend auf label_type
    if label_type == 'cable':
        qr_size = 2.5*cm
        items_per_row = 3
        items_per_col = 8
    else:  # device
        qr_size = 3*cm
        items_per_row = 2
        items_per_col = 6
    
    # Produkte in Blöcken anordnen
    items_per_page = items_per_row * items_per_col
    
    for page_start in range(0, len(products), items_per_page):
        page_products = products[page_start:page_start + items_per_page]
        
        # Erstelle Grid für QR-Codes
        qr_data = []
        for row in range(items_per_col):
            row_data = []
            for col in range(items_per_row):
                idx = row * items_per_row + col
                if idx < len(page_products):
                    product = page_products[idx]
                    qr_url = generate_product_qr_code(product.id)
                    qr_bytes = generate_qr_code_bytes(qr_url, box_size=6, border=2)
                    qr_image = Image(BytesIO(qr_bytes), width=qr_size, height=qr_size)
                    
                    # Produktname und ID unter dem QR-Code
                    product_name = product.name[:20] if product.name else f"ID: {product.id}"
                    name_style = ParagraphStyle(
                        'ProductName',
                        parent=styles['Normal'],
                        fontSize=8,
                        textColor=colors.black,
                        alignment=TA_CENTER,
                        fontName='Helvetica',
                        spaceAfter=0.1*cm
                    )
                    
                    id_style = ParagraphStyle(
                        'ProductID',
                        parent=styles['Normal'],
                        fontSize=7,
                        textColor=colors.grey,
                        alignment=TA_CENTER,
                        fontName='Helvetica'
                    )
                    
                    # Kombiniere QR-Code und Text
                    cell_content = [
                        qr_image,
                        Spacer(1, 0.1*cm),
                        Paragraph(product_name, name_style),
                        Paragraph(f"ID: {product.id}", id_style)
                    ]
                    row_data.append(cell_content)
                else:
                    row_data.append('')
            qr_data.append(row_data)
        
        # Tabelle mit QR-Codes erstellen
        col_widths = [A4[0] / items_per_row - 0.5*cm] * items_per_row
        row_heights = [qr_size + 1.5*cm] * items_per_col
        
        qr_table = Table(qr_data, colWidths=col_widths, rowHeights=row_heights)
        qr_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        story.append(qr_table)
        
        # Seitenumbruch für weitere Seiten
        if page_start + items_per_page < len(products):
            story.append(Spacer(1, 0.5*cm))
    
    doc.build(story)
    
    if isinstance(output, BytesIO):
        output.seek(0)
        return output
    
    return output
