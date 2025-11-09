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
    borrow_group_id = db.Column(db.String(50), nullable=True, index=True)  # Gruppierungs-ID für Mehrfachausleihen
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


class ProductSet(db.Model):
    """Produktset - mehrere Produkte zu einem Set zusammengefasst."""
    __tablename__ = 'product_sets'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    creator = db.relationship('User', foreign_keys=[created_by])
    items = db.relationship('ProductSetItem', back_populates='set', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<ProductSet {self.name}>'
    
    @property
    def product_count(self):
        """Anzahl der Produkte im Set."""
        return len(self.items)


class ProductSetItem(db.Model):
    """Einzelnes Produkt in einem Set."""
    __tablename__ = 'product_set_items'
    
    id = db.Column(db.Integer, primary_key=True)
    set_id = db.Column(db.Integer, db.ForeignKey('product_sets.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    
    # Relationships
    set = db.relationship('ProductSet', back_populates='items')
    product = db.relationship('Product')
    
    def __repr__(self):
        return f'<ProductSetItem {self.product_id} in Set {self.set_id}>'
    
    __table_args__ = (
        db.UniqueConstraint('set_id', 'product_id', name='uq_set_product'),
    )


class ProductDocument(db.Model):
    """Dokumente für Produkte (Handbücher, Datenblätter, etc.)."""
    __tablename__ = 'product_documents'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    manual_id = db.Column(db.Integer, db.ForeignKey('manuals.id'), nullable=True, index=True)  # Optional: Verknüpfung mit Manual-Modul
    file_path = db.Column(db.String(500), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(50), nullable=False)  # 'handbook', 'datasheet', 'invoice', 'warranty', 'other'
    file_size = db.Column(db.Integer, nullable=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    product = db.relationship('Product', backref='documents')
    manual = db.relationship('Manual', foreign_keys=[manual_id])
    uploader = db.relationship('User', foreign_keys=[uploaded_by])
    
    def __repr__(self):
        return f'<ProductDocument {self.file_name} for Product {self.product_id}>'


class SavedFilter(db.Model):
    """Gespeicherte Filter für Produktsuche."""
    __tablename__ = 'saved_filters'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    filter_data = db.Column(db.Text, nullable=False)  # JSON als String
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    user = db.relationship('User', foreign_keys=[user_id])
    
    def __repr__(self):
        return f'<SavedFilter {self.name} by User {self.user_id}>'


class ProductFavorite(db.Model):
    """Favoriten - Benutzer können Produkte als Favoriten markieren."""
    __tablename__ = 'product_favorites'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    user = db.relationship('User', foreign_keys=[user_id])
    product = db.relationship('Product')
    
    def __repr__(self):
        return f'<ProductFavorite User {self.user_id} -> Product {self.product_id}>'
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'product_id', name='uq_user_product_favorite'),
    )


class Inventory(db.Model):
    """Inventur-Session - Verwaltet eine Inventur-Session."""
    __tablename__ = 'inventories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='active', nullable=False, index=True)  # 'active', 'completed'
    started_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    starter = db.relationship('User', foreign_keys=[started_by])
    items = db.relationship('InventoryItem', back_populates='inventory', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Inventory {self.name} ({self.status})>'
    
    @property
    def checked_count(self):
        """Anzahl der inventierten Produkte."""
        return InventoryItem.query.filter_by(inventory_id=self.id, checked=True).count()
    
    @property
    def total_count(self):
        """Gesamtanzahl der Produkte in dieser Inventur."""
        return len(self.items)


class InventoryItem(db.Model):
    """Einzelne Produkt-Einträge in einer Inventur."""
    __tablename__ = 'inventory_items'
    
    id = db.Column(db.Integer, primary_key=True)
    inventory_id = db.Column(db.Integer, db.ForeignKey('inventories.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    checked = db.Column(db.Boolean, default=False, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    location_changed = db.Column(db.Boolean, default=False, nullable=False)
    new_location = db.Column(db.String(255), nullable=True)
    condition_changed = db.Column(db.Boolean, default=False, nullable=False)
    new_condition = db.Column(db.String(50), nullable=True)
    checked_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    checked_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    inventory = db.relationship('Inventory', back_populates='items')
    product = db.relationship('Product')
    checker = db.relationship('User', foreign_keys=[checked_by])
    
    # Unique constraint: Ein Produkt kann nur einmal pro Inventur vorkommen
    __table_args__ = (db.UniqueConstraint('inventory_id', 'product_id', name='uq_inventory_product'),)
    
    def __repr__(self):
        return f'<InventoryItem Inventory {self.inventory_id} -> Product {self.product_id} (checked: {self.checked})>'