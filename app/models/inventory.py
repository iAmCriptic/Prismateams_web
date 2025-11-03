from datetime import datetime, date
from app import db


class ProductFolder(db.Model):
    """Ordner für Produkte zur besseren Organisation."""
    __tablename__ = 'product_folders'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    description = db.Column(db.Text, nullable=True)
    color = db.Column(db.String(7), nullable=True)  # Hex-Farbe für visuelle Unterscheidung
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    creator = db.relationship('User', foreign_keys=[created_by])
    products = db.relationship('Product', back_populates='folder')
    
    def __repr__(self):
        return f'<ProductFolder {self.name}>'
    
    @property
    def product_count(self):
        """Anzahl der Produkte in diesem Ordner."""
        return len(self.products)


class Product(db.Model):
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(100), nullable=True)  # Eventtechnik-spezifisch
    serial_number = db.Column(db.String(100), nullable=True, index=True)
    condition = db.Column(db.String(50), nullable=True)  # z.B. "Neu", "Gut", "Beschädigt"
    location = db.Column(db.String(255), nullable=True)  # Lagerort
    length = db.Column(db.String(50), nullable=True)  # Länge (z.B. "5m", "120cm")
    purchase_date = db.Column(db.Date, nullable=True)  # Anschaffungsdatum
    status = db.Column(db.String(20), default='available', nullable=False, index=True)  # 'available', 'borrowed', 'missing'
    image_path = db.Column(db.String(500), nullable=True)  # Pfad zum Produktbild
    qr_code_data = db.Column(db.String(255), nullable=True)  # QR-Code-Wert (z.B. "PROD-{id}")
    folder_id = db.Column(db.Integer, db.ForeignKey('product_folders.id'), nullable=True, index=True)  # Ordner-Zuordnung
    
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    creator = db.relationship('User', foreign_keys=[created_by])
    folder = db.relationship('ProductFolder', back_populates='products')
    borrow_transactions = db.relationship('BorrowTransaction', back_populates='product', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Product {self.name}>'
    
    @property
    def is_available(self):
        """Prüft ob das Produkt verfügbar ist."""
        return self.status == 'available'
    
    @property
    def is_missing(self):
        """Prüft ob das Produkt als fehlend markiert ist."""
        return self.status == 'missing'
    
    @property
    def current_borrow(self):
        """Gibt die aktuelle aktive Ausleihe zurück, falls vorhanden."""
        return BorrowTransaction.query.filter_by(
            product_id=self.id,
            status='active'
        ).first()


class BorrowTransaction(db.Model):
    __tablename__ = 'borrow_transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    transaction_number = db.Column(db.String(50), unique=True, nullable=False, index=True)  # Ausleihvorgangsnummer
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    borrower_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Wer leiht aus
    borrowed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Wer registriert die Ausleihe
    borrow_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expected_return_date = db.Column(db.Date, nullable=False)
    actual_return_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='active', nullable=False, index=True)  # 'active', 'returned'
    qr_code_data = db.Column(db.String(255), nullable=True)  # QR-Code für den Ausleihvorgang (z.B. "BORROW-{transaction_number}")
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    product = db.relationship('Product', back_populates='borrow_transactions')
    borrower = db.relationship('User', foreign_keys=[borrower_id])
    borrowed_by = db.relationship('User', foreign_keys=[borrowed_by_id])
    
    def __repr__(self):
        return f'<BorrowTransaction {self.transaction_number}>'
    
    @property
    def is_overdue(self):
        """Prüft ob die Ausleihe überfällig ist."""
        if self.status == 'returned':
            return False
        return date.today() > self.expected_return_date
    
    def mark_as_returned(self):
        """Markiert die Ausleihe als zurückgegeben."""
        self.status = 'returned'
        self.actual_return_date = date.today()
        if self.product:
            self.product.status = 'available'

