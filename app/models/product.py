# app/models/product.py
"""
Product and Inventory Management Models
Comprehensive stock management with buffer stock alerts
and real-time inventory tracking
"""

from datetime import datetime, timedelta
from sqlalchemy import event, Index, CheckConstraint, and_, or_, func
from sqlalchemy.dialects.postgresql import JSONB
from decimal import Decimal
import uuid

from app.models.tenant import db


class Product(db.Model):
    """
    Product model representing inventory items
    Supports SKU tracking, pricing tiers, and stock levels
    """
    __tablename__ = 'products'
    
    # Primary Keys
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    
    # Tenant Association
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenants.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    
    # Basic Product Information
    name = db.Column(db.String(255), nullable=False, index=True)
    description = db.Column(db.Text)
    sku = db.Column(db.String(100), nullable=False, unique=True, index=True)
    barcode = db.Column(db.String(100), unique=True, sparse=True, index=True)
    qr_code = db.Column(db.String(500))
    
    # Categorization
    category = db.Column(db.String(100), nullable=False, index=True)
    subcategory = db.Column(db.String(100))
    brand = db.Column(db.String(100))
    supplier = db.Column(db.String(255))
    
    # Pricing Information
    cost_price = db.Column(
        db.Numeric(12, 2),
        nullable=False,
        comment='Cost price per unit'
    )
    selling_price = db.Column(
        db.Numeric(12, 2),
        nullable=False,
        comment='Standard selling price'
    )
    wholesale_price = db.Column(
        db.Numeric(12, 2),
        comment='Wholesale/bulk discount price'
    )
    retail_price = db.Column(
        db.Numeric(12, 2),
        comment='Retail marked price'
    )
    minimum_price = db.Column(
        db.Numeric(12, 2),
        comment='Minimum allowed selling price'
    )
    
    # Stock Levels
    current_stock = db.Column(
        db.Integer,
        default=0,
        nullable=False,
        index=True,
        comment='Current quantity in stock'
    )
    reserved_stock = db.Column(
        db.Integer,
        default=0,
        comment='Stock reserved for pending orders'
    )
    available_stock = db.Column(
        db.Integer,
        default=0,
        comment='Available for sale (current - reserved)'
    )
    
    # Stock Management Thresholds
    min_stock = db.Column(
        db.Integer,
        default=10,
        nullable=False,
        comment='Minimum stock level for reordering'
    )
    max_stock = db.Column(
        db.Integer,
        default=100,
        nullable=False,
        comment='Maximum stock level'
    )
    reorder_quantity = db.Column(
        db.Integer,
        default=50,
        comment='Quantity to order when stock is low'
    )
    
    # Two-Tier Buffer Stock Alert System
    critical_level = db.Column(
        db.Integer,
        nullable=False,
        comment='Critical stock level (15% of max)'
    )
    warning_level = db.Column(
        db.Integer,
        nullable=False,
        comment='Warning stock level (30% of max)'
    )
    
    # Physical Characteristics
    unit = db.Column(
        db.String(50),
        default='piece',
        nullable=False,
        comment='Unit of measurement (piece, kg, liter, box)'
    )
    weight = db.Column(db.Numeric(10, 3), comment='Weight in kg')
    dimensions = db.Column(db.String(100), comment='L x W x H in cm')
    color = db.Column(db.String(100))
    size = db.Column(db.String(100))
    
    # Media & Images
    image_url = db.Column(db.String(500), comment='Primary product image')
    thumbnail_url = db.Column(db.String(500))
    images = db.Column(
        JSONB if 'postgresql' in str(db.engine.url) else db.JSON,
        default=[],
        comment='Array of image URLs'
    )
    
    # Expiry & Shelf Life
    expiry_date = db.Column(db.DateTime)
    shelf_life_days = db.Column(db.Integer, comment='Days until expiry from manufacture')
    manufacture_date = db.Column(db.DateTime)
    batch_number = db.Column(db.String(100))
    
    # Status & Classification
    status = db.Column(
        db.String(50),
        default='active',
        nullable=False,
        index=True,
        comment='active, discontinued, archived'
    )
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    is_taxable = db.Column(db.Boolean, default=True, comment='Subject to tax')
    is_returnable = db.Column(db.Boolean, default=True, comment='Can be returned')
    
    # Tracking Flags
    track_serial_numbers = db.Column(db.Boolean, default=False)
    track_batch_numbers = db.Column(db.Boolean, default=False)
    track_expiry_dates = db.Column(db.Boolean, default=False)
    
    # Additional Settings
    allow_negative_stock = db.Column(db.Boolean, default=False)
    settings = db.Column(
        JSONB if 'postgresql' in str(db.engine.url) else db.JSON,
        default={},
        comment='Additional product settings'
    )
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = db.Column(db.DateTime)
    
    # Relationships
    stock_movements = db.relationship(
        'StockMovement',
        backref='product',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='StockMovement.product_id'
    )
    sale_items = db.relationship(
        'SaleItem',
        backref='product',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='SaleItem.product_id'
    )
    stock_alerts = db.relationship(
        'StockAlert',
        backref='product',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='StockAlert.product_id'
    )
    purchase_orders = db.relationship(
        'PurchaseOrder',
        backref='product',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='PurchaseOrder.product_id'
    )
    
    # Table constraints
    __table_args__ = (
        Index('idx_product_tenant_sku', 'tenant_id', 'sku'),
        Index('idx_product_tenant_category', 'tenant_id', 'category'),
        Index('idx_product_status', 'tenant_id', 'status'),
        Index('idx_product_stock_level', 'tenant_id', 'current_stock'),
        CheckConstraint('selling_price > 0', name='check_positive_price'),
        CheckConstraint('cost_price >= 0', name='check_non_negative_cost'),
    )
    
    def __repr__(self):
        return f'<Product {self.name} ({self.sku})>'
    
    def __str__(self):
        return self.name
    
    # =========================================================================
    # STOCK CALCULATION METHODS
    # =========================================================================
    
    def update_available_stock(self):
        """Update available stock based on reserved quantity"""
        self.available_stock = max(0, self.current_stock - self.reserved_stock)
        db.session.commit()
    
    def get_stock_percentage(self):
        """
        Calculate stock percentage relative to max stock
        
        Returns:
            float: Stock percentage (0-100)
        """
        if self.max_stock == 0:
            return 0
        return (self.current_stock / self.max_stock) * 100
    
    def get_turnover_rate(self, days=30):
        """
        Calculate stock turnover rate
        
        Args:
            days (int): Period in days to calculate turnover
            
        Returns:
            float: Turnover rate
        """
        from app.models.sale import SaleItem
        
        since_date = datetime.utcnow() - timedelta(days=days)
        sold_quantity = db.session.query(func.sum(SaleItem.quantity)).filter(
            SaleItem.product_id == self.id,
            SaleItem.created_at >= since_date
        ).scalar() or 0
        
        if self.max_stock == 0:
            return 0
        return sold_quantity / self.max_stock
    
    # =========================================================================
    # STOCK LEVEL CHECKING METHODS
    # =========================================================================
    
    def is_low_stock(self):
        """Check if stock is below warning level"""
        return self.current_stock <= self.warning_level
    
    def is_critical_stock(self):
        """Check if stock is below critical level"""
        return self.current_stock <= self.critical_level
    
    def needs_reorder(self):
        """Check if product needs reordering"""
        return self.current_stock <= self.min_stock
    
    def is_out_of_stock(self):
        """Check if product is completely out of stock"""
        return self.current_stock <= 0
    
    def is_overstocked(self):
        """Check if product exceeds maximum stock level"""
        return self.current_stock > self.max_stock
    
    def get_stock_status(self):
        """
        Get comprehensive stock status
        
        Returns:
            str: Status (optimal, low, critical, out_of_stock, overstocked)
        """
        if self.current_stock <= 0:
            return 'out_of_stock'
        elif self.current_stock <= self.critical_level:
            return 'critical'
        elif self.current_stock <= self.warning_level:
            return 'low'
        elif self.current_stock > self.max_stock:
            return 'overstocked'
        else:
            return 'optimal'
    
    # =========================================================================
    # AUTO-CALCULATION METHODS
    # =========================================================================
    
    def calculate_critical_level(self):
        """Auto-calculate critical level (15% of max stock)"""
        return int(self.max_stock * 0.15) if self.max_stock > 0 else 0
    
    def calculate_warning_level(self):
        """Auto-calculate warning level (30% of max stock)"""
        return int(self.max_stock * 0.30) if self.max_stock > 0 else 0
    
    def auto_set_buffer_levels(self):
        """Automatically set both critical and warning levels"""
        self.critical_level = self.calculate_critical_level()
        self.warning_level = self.calculate_warning_level()
        db.session.commit()
    
    # =========================================================================
    # PRICING METHODS
    # =========================================================================
    
    def calculate_profit_margin(self):
        """Calculate profit margin percentage"""
        if self.cost_price == 0:
            return 0
        profit = float(self.selling_price) - float(self.cost_price)
        return (profit / float(self.cost_price)) * 100
    
    def calculate_profit_per_unit(self):
        """Calculate profit per unit"""
        return float(self.selling_price) - float(self.cost_price)
    
    def get_effective_price(self, quantity=1, discount_percentage=0):
        """
        Calculate effective price with volume discounts
        
        Args:
            quantity (int): Quantity being purchased
            discount_percentage (float): Applied discount
            
        Returns:
            Decimal: Effective unit price
        """
        price = self.selling_price
        
        # Apply volume discount logic if needed
        if quantity >= 10 and self.wholesale_price:
            price = self.wholesale_price
        
        # Apply discount
        if discount_percentage > 0:
            price = price * (1 - discount_percentage / 100)
        
        return max(price, self.minimum_price) if self.minimum_price else price
    
    # =========================================================================
    # STOCK ADJUSTMENT METHODS
    # =========================================================================
    
    def adjust_stock(self, quantity, movement_type='adjustment', notes='', user_id=None):
        """
        Adjust stock level and create movement record
        
        Args:
            quantity (int): Quantity to adjust (positive or negative)
            movement_type (str): Type of movement
            notes (str): Notes for adjustment
            user_id (int): User making adjustment
            
        Returns:
            StockMovement: Created movement record
        """
        self.current_stock += quantity
        
        if not self.allow_negative_stock and self.current_stock < 0:
            raise ValueError(f'Insufficient stock for {self.name}')
        
        self.update_available_stock()
        
        # Create stock movement record
        movement = StockMovement(
            tenant_id=self.tenant_id,
            product_id=self.id,
            movement_type=movement_type,
            quantity=quantity,
            notes=notes,
            created_by=user_id
        )
        db.session.add(movement)
        db.session.commit()
        
        return movement
    
    # =========================================================================
    # DISPLAY METHODS
    # =========================================================================
    
    def get_status_color(self):
        """Get color code for stock status"""
        status = self.get_stock_status()
        colors = {
            'optimal': 'success',
            'low': 'warning',
            'critical': 'danger',
            'out_of_stock': 'dark',
            'overstocked': 'info'
        }
        return colors.get(status, 'secondary')
    
    def get_status_badge(self):
        """Get badge text for status"""
        return self.get_stock_status().replace('_', ' ').title()


class StockMovement(db.Model):
    """
    Track all stock movements for audit and analytics
    Records every change to inventory
    """
    __tablename__ = 'stock_movements'
    
    # Primary Key
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    
    # Association
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenants.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    product_id = db.Column(
        db.Integer,
        db.ForeignKey('products.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    
    # Movement Details
    movement_type = db.Column(
        db.String(50),
        nullable=False,
        index=True,
        comment='in, out, adjustment, return, damage, loss, transfer'
    )
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), comment='Price at time of movement')
    
    # Reference Information
    reference_id = db.Column(db.Integer, comment='Related sale/PO/adjustment ID')
    reference_type = db.Column(
        db.String(50),
        comment='sale, purchase_order, adjustment, transfer'
    )
    reference_number = db.Column(db.String(100), comment='Sale number, PO number, etc.')
    
    # Location Tracking
    warehouse_from = db.Column(db.String(100))
    warehouse_to = db.Column(db.String(100))
    
    # Additional Information
    notes = db.Column(db.Text)
    batch_number = db.Column(db.String(100))
    serial_number = db.Column(db.String(100))
    lot_number = db.Column(db.String(100))
    
    # User Tracking
    created_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL')
    )
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Table constraints
    __table_args__ = (
        Index('idx_movement_tenant_product_type', 'tenant_id', 'product_id', 'movement_type'),
        Index('idx_movement_reference', 'reference_type', 'reference_id'),
        Index('idx_movement_created', 'created_at'),
    )
    
    def __repr__(self):
        return f'<StockMovement {self.movement_type} ({self.quantity})>'
    
    def get_movement_label(self):
        """Get human-readable movement label"""
        labels = {
            'in': 'Stock In',
            'out': 'Stock Out (Sale)',
            'adjustment': 'Adjustment',
            'return': 'Return',
            'damage': 'Damaged',
            'loss': 'Loss',
            'transfer': 'Transfer'
        }
        return labels.get(self.movement_type, self.movement_type.title())


class StockAlert(db.Model):
    """
    Real-time stock level alerts for inventory management
    Two-tier alert system: warning and critical
    """
    __tablename__ = 'stock_alerts'
    
    # Primary Key
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    
    # Association
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenants.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    product_id = db.Column(
        db.Integer,
        db.ForeignKey('products.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    
    # Alert Information
    alert_type = db.Column(
        db.String(50),
        nullable=False,
        index=True,
        comment='reorder_notification, low_stock_urgent, critical_stock, expiry_warning'
    )
    severity = db.Column(
        db.String(20),
        default='medium',
        comment='low, medium, high, critical'
    )
    message = db.Column(db.Text, nullable=False)
    
    # Stock Details
    current_stock = db.Column(db.Integer)
    threshold_level = db.Column(db.Integer)
    
    # Action Required
    action_required = db.Column(db.String(255), comment='Suggested action')
    is_acknowledged = db.Column(db.Boolean, default=False, nullable=False, index=True)
    acknowledged_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL')
    )
    acknowledged_at = db.Column(db.DateTime)
    acknowledgement_notes = db.Column(db.Text)
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    resolved_at = db.Column(db.DateTime)
    
    # Table constraints
    __table_args__ = (
        Index('idx_alert_tenant_type', 'tenant_id', 'alert_type'),
        Index('idx_alert_unacknowledged', 'tenant_id', 'is_acknowledged'),
        Index('idx_alert_severity', 'severity'),
    )
    
    def __repr__(self):
        return f'<StockAlert {self.alert_type}>'
    
    def acknowledge(self, user_id, notes=''):
        """
        Acknowledge the alert
        
        Args:
            user_id (int): User acknowledging alert
            notes (str): Acknowledgement notes
        """
        self.is_acknowledged = True
        self.acknowledged_by = user_id
        self.acknowledged_at = datetime.utcnow()
        self.acknowledgement_notes = notes
        db.session.commit()
    
    def resolve(self):
        """Mark alert as resolved"""
        self.resolved_at = datetime.utcnow()
        db.session.commit()
    
    def get_severity_color(self):
        """Get color for severity level"""
        colors = {
            'low': 'info',
            'medium': 'warning',
            'high': 'danger',
            'critical': 'dark'
        }
        return colors.get(self.severity, 'secondary')


class PurchaseOrder(db.Model):
    """
    Purchase orders for stock replenishment
    Manages supplier orders and inventory replenishment
    """
    __tablename__ = 'purchase_orders'
    
    # Primary Key
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    
    # Association
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenants.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    product_id = db.Column(
        db.Integer,
        db.ForeignKey('products.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    
    # PO Information
    po_number = db.Column(db.String(100), nullable=False, unique=True, index=True)
    po_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Supplier Details
    supplier_name = db.Column(db.String(255), nullable=False)
    supplier_email = db.Column(db.String(255))
    supplier_phone = db.Column(db.String(20))
    supplier_address = db.Column(db.Text)
    
    # Order Details
    quantity = db.Column(db.Integer, nullable=False)
    unit_cost = db.Column(db.Numeric(12, 2), nullable=False)
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    tax_amount = db.Column(db.Numeric(12, 2), default=0)
    shipping_cost = db.Column(db.Numeric(12, 2), default=0)
    grand_total = db.Column(db.Numeric(12, 2), nullable=False)
    
    # Status
    status = db.Column(
        db.String(50),
        default='pending',
        nullable=False,
        index=True,
        comment='pending, confirmed, dispatched, received, cancelled, returned'
    )
    
    # Delivery
    expected_delivery = db.Column(db.DateTime)
    expected_delivery_days = db.Column(db.Integer, comment='Estimated days for delivery')
    received_date = db.Column(db.DateTime)
    received_quantity = db.Column(db.Integer)
    
    # Quality Check
    quality_check_passed = db.Column(db.Boolean)
    quality_notes = db.Column(db.Text)
    
    # Additional Information
    payment_terms = db.Column(db.String(100), comment='e.g., Net 30')
    notes = db.Column(db.Text)
    tracking_number = db.Column(db.String(100))
    invoice_number = db.Column(db.String(100))
    
    # Audit
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Table constraints
    __table_args__ = (
        Index('idx_po_tenant_number', 'tenant_id', 'po_number'),
        Index('idx_po_status', 'status'),
        Index('idx_po_date', 'po_date'),
    )
    
    def __repr__(self):
        return f'<PurchaseOrder {self.po_number}>'
    
    # =========================================================================
    # STATUS METHODS
    # =========================================================================
    
    def confirm(self):
        """Confirm the purchase order"""
        self.status = 'confirmed'
        self.expected_delivery = datetime.utcnow() + timedelta(
            days=self.expected_delivery_days or 7
        )
        db.session.commit()
    
    def mark_received(self, received_quantity=None, quality_passed=True):
        """Mark PO as received"""
        self.status = 'received'
        self.received_date = datetime.utcnow()
        self.received_quantity = received_quantity or self.quantity
        self.quality_check_passed = quality_passed
        db.session.commit()
    
    def cancel(self):
        """Cancel the purchase order"""
        self.status = 'cancelled'
        db.session.commit()
    
    # =========================================================================
    # CALCULATION METHODS
    # =========================================================================
    
    def calculate_grand_total(self):
        """Calculate grand total with tax and shipping"""
        self.total_amount = Decimal(self.quantity) * self.unit_cost
        self.grand_total = self.total_amount + (self.tax_amount or 0) + (self.shipping_cost or 0)
        db.session.commit()
