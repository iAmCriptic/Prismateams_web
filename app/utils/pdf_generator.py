from reportlab.lib.pagesizes import A4, A5, letter
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, Flowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas
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


class CableLabelFlowable(Flowable):
    """
    Kabel-Wickeletikett: [FARBSTREIFEN][QR weiß/schwarz][TEXT weiß/schwarz][FARBSTREIFEN]
    Kann um ein Kabel gewickelt werden – eine Seite QR, andere Seite Text.
    """
    def __init__(self, product, qr_bytes, stripe_color_hex, label_width, label_height):
        Flowable.__init__(self)
        self.product = product
        self.qr_bytes = qr_bytes
        try:
            self.stripe_color = colors.HexColor(stripe_color_hex)
        except Exception:
            self.stripe_color = colors.HexColor('#888888')
        self.width = label_width
        self.height = label_height

    def draw(self):
        c = self.canv
        lw = self.width
        lh = self.height
        sw = 1.2 * cm  # Streifenbreite

        # Linker Farbstreifen
        c.setFillColor(self.stripe_color)
        c.rect(0, 0, sw, lh, fill=1, stroke=0)

        # Rechter Farbstreifen
        c.setFillColor(self.stripe_color)
        c.rect(lw - sw, 0, sw, lh, fill=1, stroke=0)

        # Schwarzer Mittelteil
        c.setFillColor(colors.black)
        c.rect(sw, 0, lw - 2 * sw, lh, fill=1, stroke=0)

        # QR-Code (weiß auf schwarz) – quadratisch, füllt fast die volle Höhe
        qr_margin = 3
        qr_size = lh - 2 * qr_margin
        qr_x = sw + qr_margin
        qr_y = qr_margin
        c.drawImage(ImageReader(BytesIO(self.qr_bytes)), qr_x, qr_y, qr_size, qr_size)

        # Textbereich (weiß auf schwarz)
        c.setFillColor(colors.white)
        text_x = sw + qr_size + qr_margin * 2 + 4

        # Produktname (fett)
        name = self.product.name or f'ID {self.product.id}'
        if len(name) > 16:
            name = name[:15] + u'…'
        c.setFont('Helvetica-Bold', 8)
        c.drawString(text_x, lh * 0.70, name)

        # Produkt-ID
        c.setFont('Helvetica', 6.5)
        c.drawString(text_x, lh * 0.46, f'ID: {self.product.id}')

        # Länge mit farbigem Punkt
        if self.product.length:
            length_str = _format_length(self.product.length)
            dot_r = 3
            dot_x = text_x + dot_r
            dot_y = lh * 0.20 + dot_r
            c.setFillColor(self.stripe_color)
            c.circle(dot_x, dot_y, dot_r, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont('Helvetica-Bold', 8)
            c.drawString(text_x + dot_r * 2 + 4, lh * 0.17, length_str)

        # Gestrichelter Schnittrahmen
        c.setStrokeColor(colors.HexColor('#aaaaaa'))
        c.setDash([2, 2])
        c.setLineWidth(0.4)
        c.rect(0, 0, lw, lh, fill=0, stroke=1)
        c.setDash([])


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


def get_portal_name():
    """Portalname aus SystemSettings, sonst APP_NAME."""
    try:
        from app.models.settings import SystemSettings
        portal_name_setting = SystemSettings.query.filter_by(key='portal_name').first()
        if portal_name_setting and portal_name_setting.value and portal_name_setting.value.strip():
            return portal_name_setting.value.strip()
    except Exception:
        pass
    return current_app.config.get('APP_NAME', 'Prismateams')


def build_standard_header(title, subtitle=None, pagesize=A4, logo_size=2.0 * cm, content_width=None):
    """
    Einheitlicher PDF-Kopf: Portal-Logo links, Titel (und optional Untertitel) daneben.
    Grundlage für systemweite PDF-Dokumente (wie Veranstaltungen / Inventar).
    """
    styles = getSampleStyleSheet()
    usable_width = content_width if content_width is not None else (pagesize[0] - 4 * cm)

    title_style = ParagraphStyle(
        'PdfStandardTitle',
        parent=styles['Heading1'],
        fontSize=18,
        leading=22,
        textColor=colors.black,
        fontName='Helvetica-Bold',
        spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        'PdfStandardSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        leading=12,
        textColor=colors.HexColor('#6c757d'),
    )

    text_block = [Paragraph(title, title_style)]
    if subtitle:
        text_block.append(Paragraph(subtitle, subtitle_style))

    logo_cell = ''
    logo_path = get_logo_path()
    if logo_path:
        try:
            logo_cell = Image(logo_path, width=logo_size, height=logo_size, kind='proportional')
        except Exception:
            logo_cell = ''

    logo_col = logo_size + 0.6 * cm
    text_col = max(usable_width - logo_col, 8 * cm)
    header = Table([[logo_cell, text_block]], colWidths=[logo_col, text_col])
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    return header


def inventory_table_style(header=True):
    """Einheitlicher Tabellenstil für Inventar-PDFs (wie Veranstaltungen)."""
    style = [
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#adb5bd')),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('LEADING', (0, 0), (-1, -1), 12),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
    ]
    if header:
        style.extend([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ])
    return TableStyle(style)


def _qr_block(qr_payload, label='QR-Code', size=4.2 * cm):
    """Zentrierter QR mit Beschriftung für Inventar-Belege."""
    styles = getSampleStyleSheet()
    label_style = ParagraphStyle(
        'InvQrLabel',
        parent=styles['Normal'],
        fontSize=10,
        fontName='Helvetica-Bold',
        alignment=TA_CENTER,
        textColor=colors.HexColor('#212529'),
        spaceAfter=0.2 * cm,
    )
    caption_style = ParagraphStyle(
        'InvQrCaption',
        parent=styles['Normal'],
        fontSize=8,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#6c757d'),
    )
    qr_bytes = generate_qr_code_bytes(qr_payload, box_size=8, border=2)
    qr_image = Image(BytesIO(qr_bytes), width=size, height=size)
    inner = Table(
        [[Paragraph(label, label_style)], [qr_image], [Paragraph(str(qr_payload), caption_style)]],
        colWidths=[size + 0.8 * cm],
    )
    inner.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOX', (0, 0), (-1, -1), 0.7, colors.HexColor('#dee2e6')),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    return inner


class StandardFooterCanvas(pdf_canvas.Canvas):
    """Canvas mit Fußzeile und Seitenzahl im Format X/Y."""

    def __init__(self, *args, **kwargs):
        pdf_canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []
        self.pdf_created_at = datetime.now().strftime('%d.%m.%Y %H:%M')
        self.pdf_portal_name = 'Prismateams'
        self.pdf_left_margin = 2 * cm
        self.pdf_right_margin = 2 * cm

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        page_count = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(page_count)
            pdf_canvas.Canvas.showPage(self)
        pdf_canvas.Canvas.save(self)

    def _draw_footer(self, page_count):
        page_width, _ = self._pagesize
        left = self.pdf_left_margin
        right = page_width - self.pdf_right_margin
        y = 1.15 * cm
        line_y = y + 0.4 * cm

        self.saveState()
        self.setStrokeColor(colors.HexColor('#bbbbbb'))
        self.setLineWidth(0.6)
        self.line(left, line_y, right, line_y)

        self.setFillColor(colors.HexColor('#666666'))
        self.setFont('Helvetica', 8)
        self.drawString(left, y, f"Erstellt am {self.pdf_created_at}")
        self.drawCentredString(page_width / 2.0, y, f"© {self.pdf_portal_name}")
        self.drawRightString(right, y, f"{self._pageNumber}/{page_count}")
        self.restoreState()


def draw_standard_footer(canvas, doc):
    """
    Einheitlicher PDF-Fuß (Fallback ohne Gesamtseitenzahl).
    Bevorzugt StandardFooterCanvas über build_standard_pdf nutzen.
    """
    canvas.saveState()
    page_width, _ = doc.pagesize
    left = doc.leftMargin
    right = page_width - doc.rightMargin
    y = 1.15 * cm
    line_y = y + 0.4 * cm

    canvas.setStrokeColor(colors.HexColor('#bbbbbb'))
    canvas.setLineWidth(0.6)
    canvas.line(left, line_y, right, line_y)

    canvas.setFillColor(colors.HexColor('#666666'))
    canvas.setFont('Helvetica', 8)

    created_at = getattr(doc, 'pdf_created_at', None) or datetime.now().strftime('%d.%m.%Y %H:%M')
    portal_name = getattr(doc, 'pdf_portal_name', None) or 'Prismateams'
    page_count = getattr(doc, 'pdf_page_count', None)

    canvas.drawString(left, y, f"Erstellt am {created_at}")
    canvas.drawCentredString(page_width / 2.0, y, f"© {portal_name}")
    page_label = (
        f"{canvas.getPageNumber()}/{page_count}"
        if page_count
        else str(canvas.getPageNumber())
    )
    canvas.drawRightString(right, y, page_label)
    canvas.restoreState()


def build_standard_pdf(story, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                       topMargin=1.5 * cm, bottomMargin=2 * cm, output=None):
    """Baut PDF mit Standard-Footer und Seitenzahl X/Y auf jeder Seite."""
    if output is None:
        output = BytesIO()

    doc = SimpleDocTemplate(
        output,
        pagesize=pagesize,
        leftMargin=leftMargin,
        rightMargin=rightMargin,
        topMargin=topMargin,
        bottomMargin=bottomMargin,
    )
    created_at = datetime.now().strftime('%d.%m.%Y %H:%M')
    try:
        portal_name = get_portal_name()
    except Exception:
        portal_name = 'Prismateams'

    doc.pdf_created_at = created_at
    doc.pdf_portal_name = portal_name

    def _canvas_maker(filename, **kwargs):
        canvas_obj = StandardFooterCanvas(filename, **kwargs)
        canvas_obj.pdf_created_at = created_at
        canvas_obj.pdf_portal_name = portal_name
        canvas_obj.pdf_left_margin = leftMargin
        canvas_obj.pdf_right_margin = rightMargin
        return canvas_obj

    doc.build(story, canvasmaker=_canvas_maker)

    if isinstance(output, BytesIO):
        output.seek(0)
    return output


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
    if isinstance(output, BytesIO):
        output.seek(0)
    return output


def generate_borrow_receipt_pdf(borrow_transactions, output=None):
    """
    Generiert einen Ausleihschein-PDF für Checkout oder Legacy-BorrowTransactions.
    Einheitliches Layout: Logo, blauer Titel, Tabelle, QR, Standard-Footer.
    """
    from app.models.inventory import Checkout

    styles = getSampleStyleSheet()
    stand = datetime.now().strftime('%d.%m.%Y')
    section_style = ParagraphStyle(
        'InvSection',
        parent=styles['Normal'],
        fontSize=12,
        fontName='Helvetica-Bold',
        textColor=colors.HexColor('#212529'),
        spaceBefore=0.2 * cm,
        spaceAfter=0.25 * cm,
    )
    note_style = ParagraphStyle(
        'InvNote',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#6c757d'),
        leading=12,
    )

    # --- Checkout path ---
    if isinstance(borrow_transactions, Checkout):
        checkout = borrow_transactions
        story = [
            build_standard_header(
                "Ausleihschein / Packliste",
                subtitle=f"Stand: {stand}",
                pagesize=A4,
                logo_size=2.0 * cm,
            ),
            Spacer(1, 0.45 * cm),
        ]

        details_data = [
            ['Ausleihdatum', checkout.start_date.strftime('%d.%m.%Y %H:%M') if checkout.start_date else '—'],
            ['Vorgangsnummer', checkout.checkout_number],
            ['Projekt / Veranstaltung', checkout.event_name or '—'],
            ['Verantwortlicher', checkout.borrower_name or '—'],
            ['Kontakt-E-Mail', checkout.contact_email or '—'],
            ['Rückgabe bis', checkout.end_date.strftime('%d.%m.%Y %H:%M') if checkout.end_date else '—'],
            ['Status', checkout.status or '—'],
        ]
        details_table = Table(details_data, colWidths=[5.2 * cm, 6.3 * cm])
        details_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#495057')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))

        qr_payload = checkout.qr_code_data or generate_borrow_qr_code(checkout.checkout_number)
        top = Table([[details_table, _qr_block(qr_payload, 'Rückgabe-QR')]], colWidths=[11.8 * cm, 5.4 * cm])
        top.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(top)
        story.append(Spacer(1, 0.55 * cm))
        story.append(Paragraph("Ausgeliehene Artikel", section_style))

        items_data = [['Nr.', 'Produktname', 'ID', 'Länge', 'Zurück']]
        for idx, item in enumerate(checkout.items, 1):
            product = item.product
            length_str = _format_length(product.length) if product and product.length else '—'
            items_data.append([
                str(idx),
                Paragraph(product.name if product else '—', styles['Normal']),
                str(product.id) if product else '—',
                length_str,
                item.returned_at.strftime('%d.%m.%Y') if item.returned_at else 'unterwegs',
            ])
        items_table = Table(items_data, colWidths=[1.1 * cm, 7.2 * cm, 2.2 * cm, 2.5 * cm, 3.2 * cm], repeatRows=1)
        items_table.setStyle(inventory_table_style())
        story.append(items_table)
        story.append(Spacer(1, 0.4 * cm))
        end_txt = checkout.end_date.strftime('%d.%m.%Y %H:%M') if checkout.end_date else '—'
        story.append(Paragraph(
            f"Bitte beachten Sie das Rückgabedatum: <b>{end_txt}</b>. "
            f"Der QR-Code dient zur schnellen Rückgabe am Scanner.",
            note_style,
        ))
        return build_standard_pdf(story, pagesize=A4, output=output)

    # --- Legacy BorrowTransaction list ---
    if not isinstance(borrow_transactions, list):
        borrow_transactions = [borrow_transactions]
    if not borrow_transactions:
        raise ValueError("Keine Ausleihvorgänge zum Generieren des PDFs vorhanden.")

    first_transaction = borrow_transactions[0]
    borrower = first_transaction.borrower
    display_ref = first_transaction.borrow_group_id or first_transaction.transaction_number

    story = [
        build_standard_header("Ausleihschein", subtitle=f"Stand: {stand}", pagesize=A4, logo_size=2.0 * cm),
        Spacer(1, 0.45 * cm),
    ]

    details_data = [
        ['Ausleihdatum', first_transaction.borrow_date.strftime('%d.%m.%Y %H:%M')],
        ['Vorgangsnummer', display_ref],
        ['Voraussichtliche Rückgabe', first_transaction.expected_return_date.strftime('%d.%m.%Y')],
        ['Ausleiher', f"{borrower.first_name} {borrower.last_name}" if borrower else '—'],
    ]
    if borrower and borrower.email:
        details_data.append(['E-Mail', borrower.email])

    details_table = Table(details_data, colWidths=[5.2 * cm, 6.3 * cm])
    details_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#495057')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
    ]))

    qr_data = generate_borrow_qr_code(first_transaction.transaction_number)
    top = Table([[details_table, _qr_block(qr_data, 'Rückgabe-QR')]], colWidths=[11.8 * cm, 5.4 * cm])
    top.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(top)
    story.append(Spacer(1, 0.55 * cm))
    story.append(Paragraph("Ausgeliehene Artikel", section_style))

    items_data = [['Nr.', 'Produktname', 'Produkt-ID', 'Länge']]
    for idx, transaction in enumerate(borrow_transactions, 1):
        product = transaction.product
        length_str = _format_length(product.length) if product and product.length else '—'
        items_data.append([
            str(idx),
            Paragraph(product.name if product else '—', styles['Normal']),
            str(product.id) if product else '—',
            length_str,
        ])
    items_table = Table(items_data, colWidths=[1.5 * cm, 8.5 * cm, 3 * cm, 3.2 * cm], repeatRows=1)
    items_table.setStyle(inventory_table_style())
    story.append(items_table)
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(
        f"Bitte beachten Sie das voraussichtliche Rückgabedatum: "
        f"<b>{first_transaction.expected_return_date.strftime('%d.%m.%Y')}</b>.",
        note_style,
    ))
    return build_standard_pdf(story, pagesize=A4, output=output)


def generate_qr_code_sheet_pdf(products, output=None, label_type='cable'):
    """
    Generiert einen QR-Code-Druckbogen für Produkte.
    Mit Standard-Kopf/Fuß; Etiketten darunter.
    """
    if not products:
        raise ValueError("Keine Produkte zum Generieren des QR-Code-Druckbogens vorhanden.")

    styles = getSampleStyleSheet()
    stand = datetime.now().strftime('%d.%m.%Y')
    title = "QR-Codes (Kabel)" if label_type == 'cable' else "QR-Codes (Geräte)"
    story = [
        build_standard_header(title, subtitle=f"Stand: {stand} · {len(products)} Artikel", pagesize=A4, logo_size=1.8 * cm),
        Spacer(1, 0.35 * cm),
    ]

    if label_type == 'cable':
        try:
            initialize_color_mappings()
        except Exception:
            pass

        LABEL_W = 8.6 * cm
        LABEL_H = 3.0 * cm
        LABELS_PER_ROW = 2
        GAP = 0.3 * cm

        rows = []
        row_data = []

        for product in products:
            stripe_hex = '#888888'
            if product.length:
                try:
                    color = get_color_for_length(product.length)
                    if color:
                        stripe_hex = color
                except Exception:
                    pass

            qr_url = generate_product_qr_code(product.id)
            qr_bytes = generate_qr_code_inverted_bytes(qr_url, box_size=6, border=2)
            label = CableLabelFlowable(product, qr_bytes, stripe_hex, LABEL_W, LABEL_H)
            row_data.append(label)

            if len(row_data) == LABELS_PER_ROW:
                rows.append(list(row_data))
                row_data = []

        if row_data:
            while len(row_data) < LABELS_PER_ROW:
                row_data.append('')
            rows.append(row_data)

        col_widths = [LABEL_W + GAP] * LABELS_PER_ROW
        row_heights = [LABEL_H + GAP] * len(rows)
        table = Table(rows, colWidths=col_widths, rowHeights=row_heights)
        table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(table)

    else:  # device
        from reportlab.platypus import PageBreak
        qr_size = 2.8 * cm
        items_per_row = 3
        items_per_col = 4
        items_per_page = items_per_row * items_per_col
        name_style = ParagraphStyle(
            'DeviceQrName', parent=styles['Normal'], fontSize=8,
            alignment=TA_CENTER, fontName='Helvetica-Bold', textColor=colors.HexColor('#212529'),
        )
        id_style = ParagraphStyle(
            'DeviceQrId', parent=styles['Normal'], fontSize=7,
            alignment=TA_CENTER, textColor=colors.HexColor('#6c757d'),
        )

        for page_start in range(0, len(products), items_per_page):
            if page_start > 0:
                story.append(PageBreak())
                story.append(build_standard_header(
                    title, subtitle=f"Stand: {stand} · Fortsetzung", pagesize=A4, logo_size=1.6 * cm
                ))
                story.append(Spacer(1, 0.3 * cm))

            page_products = products[page_start:page_start + items_per_page]
            qr_data = []
            for row in range(items_per_col):
                row_cells = []
                for col in range(items_per_row):
                    idx = row * items_per_row + col
                    if idx < len(page_products):
                        product = page_products[idx]
                        qr_url = generate_product_qr_code(product.id)
                        qr_bytes = generate_qr_code_bytes(qr_url, box_size=6, border=2)
                        qr_image = Image(BytesIO(qr_bytes), width=qr_size, height=qr_size)
                        product_name = (product.name or f"ID {product.id}")[:22]
                        cell = Table(
                            [[qr_image], [Paragraph(product_name, name_style)], [Paragraph(f"ID: {product.id}", id_style)]],
                            colWidths=[5.5 * cm],
                        )
                        cell.setStyle(TableStyle([
                            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                            ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#dee2e6')),
                            ('BACKGROUND', (0, 0), (-1, -1), colors.white),
                            ('TOPPADDING', (0, 0), (-1, -1), 6),
                            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                        ]))
                        row_cells.append(cell)
                    else:
                        row_cells.append('')
                qr_data.append(row_cells)

            qr_table = Table(qr_data, colWidths=[5.7 * cm] * items_per_row, rowHeights=[4.6 * cm] * items_per_col)
            qr_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(qr_table)

    return build_standard_pdf(
        story,
        pagesize=A4,
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=2.0 * cm,
        output=output,
    )


def generate_inventory_list_pdf(products, output=None):
    """Inventurliste als PDF im Standard-Layout."""
    styles = getSampleStyleSheet()
    products = products or []
    stand = datetime.now().strftime('%d.%m.%Y')
    story = [
        build_standard_header(
            "Inventurliste",
            subtitle=f"Stand: {stand} · {len(products)} Produkte",
            pagesize=A4,
            logo_size=2.0 * cm,
        ),
        Spacer(1, 0.4 * cm),
    ]

    if not products:
        story.append(Paragraph("Keine Produkte vorhanden.", styles['Normal']))
        return build_standard_pdf(story, pagesize=A4, output=output)

    table_data = [["#", "Name", "ID", "Kategorie", "Standort", "Status"]]
    for idx, product in enumerate(products, 1):
        table_data.append([
            str(idx),
            Paragraph(getattr(product, "name", None) or "—", styles['Normal']),
            str(getattr(product, "id", "—")),
            getattr(product, "category", None) or "—",
            Paragraph(getattr(product, "location", None) or "—", styles['Normal']),
            getattr(product, "status", None) or "—",
        ])

    table = Table(table_data, colWidths=[1 * cm, 5.5 * cm, 1.8 * cm, 3.2 * cm, 3.5 * cm, 2.2 * cm], repeatRows=1)
    table.setStyle(inventory_table_style())
    story.append(table)
    return build_standard_pdf(story, pagesize=A4, output=output)


def generate_inventory_tool_pdf(inventory, items, output=None):
    """Inventur-Export als PDF im Standard-Layout."""
    styles = getSampleStyleSheet()
    items = items or []
    stand = datetime.now().strftime('%d.%m.%Y')
    title = f"Inventur: {getattr(inventory, 'name', 'Unbenannt')}"
    story = [
        build_standard_header(title, subtitle=f"Stand: {stand}", pagesize=A4, logo_size=2.0 * cm),
        Spacer(1, 0.35 * cm),
    ]

    started = getattr(inventory, "started_at", None)
    completed = getattr(inventory, "completed_at", None)
    meta_rows = [
        ["Status", getattr(inventory, "status", None) or "—"],
        ["Gestartet", started.strftime("%d.%m.%Y %H:%M") if started else "—"],
        ["Abgeschlossen", completed.strftime("%d.%m.%Y %H:%M") if completed else "—"],
        ["Positionen", str(len(items))],
    ]
    meta = Table(meta_rows, colWidths=[4 * cm, 12 * cm])
    meta.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor('#495057')),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.extend([meta, Spacer(1, 0.4 * cm)])

    table_data = [["Produkt", "Geprüft", "Neuer Standort", "Neuer Zustand", "Geprüft von"]]
    for item in items:
        product = getattr(item, "product", None)
        checker = getattr(item, "checker", None)
        checker_name = "—"
        if checker:
            checker_name = getattr(checker, "full_name", None) or getattr(checker, "username", "—")
        checked = getattr(item, "checked", None)
        if checked is None:
            checked = getattr(item, "is_counted", False)
        table_data.append([
            Paragraph(getattr(product, "name", None) or "—", styles['Normal']),
            "Ja" if checked else "Nein",
            Paragraph(
                getattr(item, "new_location", None)
                or (getattr(product, "location", None) if product else None)
                or "—",
                styles['Normal'],
            ),
            getattr(item, "new_condition", None)
            or (getattr(product, "condition", None) if product else None)
            or "—",
            checker_name,
        ])

    table = Table(table_data, colWidths=[4.5 * cm, 1.8 * cm, 3.8 * cm, 3 * cm, 3.1 * cm], repeatRows=1)
    table.setStyle(inventory_table_style())
    story.append(table)
    return build_standard_pdf(story, pagesize=A4, output=output)


def generate_return_confirmation_pdf(borrow_transaction, output=None):
    """Kompakte Rückgabe-Bestätigung im Standard-Layout (optional mit QR)."""
    styles = getSampleStyleSheet()
    stand = datetime.now().strftime('%d.%m.%Y')
    story = [
        build_standard_header("Rückgabeschein", subtitle=f"Stand: {stand}", pagesize=A4, logo_size=2.0 * cm),
        Spacer(1, 0.4 * cm),
    ]

    # CheckoutItem / Checkout compat
    from app.models.inventory import Checkout, CheckoutItem
    if isinstance(borrow_transaction, Checkout):
        checkout = borrow_transaction
        return_date = datetime.utcnow()
        rows = [
            ["Vorgangsnummer", checkout.checkout_number],
            ["Projekt", checkout.event_name or "—"],
            ["Verantwortlicher", checkout.borrower_name or "—"],
            ["Status", checkout.status or "—"],
            ["Bestätigt am", return_date.strftime("%d.%m.%Y %H:%M")],
        ]
        qr_payload = checkout.qr_code_data or generate_borrow_qr_code(checkout.checkout_number)
    elif isinstance(borrow_transaction, CheckoutItem):
        item = borrow_transaction
        checkout = item.checkout
        product = item.product
        return_date = item.returned_at or datetime.utcnow()
        rows = [
            ["Vorgangsnummer", checkout.checkout_number if checkout else "—"],
            ["Produkt", getattr(product, "name", None) or "—"],
            ["Verantwortlicher", checkout.borrower_name if checkout else "—"],
            ["Rückgabedatum", return_date.strftime("%d.%m.%Y %H:%M")],
        ]
        qr_payload = (checkout.qr_code_data if checkout else None) or (
            generate_product_qr_code(product.id) if product else None
        )
    else:
        borrower = getattr(borrow_transaction, "borrower", None)
        product = getattr(borrow_transaction, "product", None)
        borrower_name = getattr(borrower, "full_name", "—") if borrower else "—"
        product_name = getattr(product, "name", "—") if product else "—"
        return_date = getattr(borrow_transaction, "actual_return_date", None) or datetime.utcnow()
        txn = getattr(borrow_transaction, "transaction_number", "—")
        rows = [
            ["Vorgangsnummer", txn],
            ["Ausleiher", borrower_name],
            ["Produkt", product_name],
            ["Rückgabedatum", return_date.strftime("%d.%m.%Y %H:%M")],
        ]
        qr_payload = generate_borrow_qr_code(txn) if txn and txn != "—" else None

    details = Table(rows, colWidths=[5 * cm, 6.5 * cm])
    details.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor('#495057')),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    if qr_payload:
        layout = Table([[details, _qr_block(qr_payload, 'Beleg-QR', size=3.6 * cm)]], colWidths=[11.8 * cm, 5.4 * cm])
        layout.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(layout)
    else:
        story.append(details)

    return build_standard_pdf(story, pagesize=A4, output=output)
