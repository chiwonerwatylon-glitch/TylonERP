# app/models/sale.py
"""
Sales and Revenue Tracking Models
Comprehensive sales management with invoicing,
expenses, and financial tracking
"""

from datetime import datetime, timedelta
from sqlalchemy import event, Index, CheckConstraint, and_, or_, func
from sqlalchemy.dialects.postgresql import JSONB
from decimal import Decimal
import uuid

from app.models.tenant import db


class Sale(db.Model):
    """
    Sale model representing transactions
    Supports cash, credit, and mixed payment sales
    """
    __tablename__ = 'sales'
    
    # Primary Key
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    
    # Tenant Association
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenants.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    
    # Reference Information
    receipt_number = db.Column(db.String(100), unique=True, nullable=False, index=True)
    sale_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Customer Information
    client_id = db.Column(
        db.Integer,
        db.ForeignKey('clients.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
        comment='NULL for cash sales to unknown customers'
    )
    customer_name = db.Column(
        db.String(255),
        nullable=True,
        comment='For walk-in customers if no client_id'
    )
    customer_phone = db.Column(db.String(20))
    
    # Sale Details
    sale_type = db.Column(
        db.String(50),
        nullable=False,
        default='cash',
        comment='cash, credit, mixed'
    )
    
    # Amount Tracking
    subtotal = db.Column(
        db.Numeric(12, 2),
        nullable=False,
        default=0,
        comment='Total before discount and tax'
    )
    discount_amount = db.Column(
        db.Numeric(12, 2),
        default=0,
        comment='Fixed discount amount'
    )
    discount_percentage = db.Column(
        db.Numeric(5, 2),
        default=0,
        comment='Discount percentage applied'
    )
    tax_amount = db.Column(db.Numeric(12, 2), default=0)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    total_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    
    # Payment Tracking (for mixed sales)
    cash_paid = db.Column(db.Numeric(12, 2), default=0)
    credit_amount = db.Column(db.Numeric(12, 2), default=0)
    change_given = db.Column(db.Numeric(12, 2), default=0)
    
    # Status
    status = db.Column(
        db.String(50),
        default='completed',
        nullable=False,
        index=True,
        comment='pending, completed, cancelled, returned'
    )
    is_invoiced = db.Column(db.Boolean, default=False, index=True)
    is_returned = db.Column(db.Boolean, default=False)
    return_amount = db.Column(db.Numeric(12, 2), default=0)
    
    # Notes & Reference
    notes = db.Column(db.Text)
    reference_code = db.Column(db.String(100), comment='PO number, ticket number, etc.')
    
    # User Information
    created_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True
    )
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = db.Column(db.DateTime)
    
    # Relationships
    sale_items = db.relationship(
        'SaleItem',
        backref='sale',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='SaleItem.sale_id'
    )
    invoice = db.relationship(
        'Invoice',
        backref='sale',
        uselist=False,
        cascade='all, delete-orphan',
        foreign_keys='Invoice.sale_id'
    )
    debts = db.relationship(
        'Debt',
        backref='sale',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='Debt.sale_id'
    )
    
    # Table constraints
    __table_args__ = (
        Index('idx_sale_tenant_date', 'tenant_id', 'sale_date'),
        Index('idx_sale_receipt', 'receipt_number'),
        Index('idx_sale_client', 'client_id'),
        Index('idx_sale_status', 'status'),
        Index('idx_sale_invoiced', 'is_invoiced'),
        CheckConstraint('total_amount >= 0', name='check_positive_total'),
    )
    
    def __repr__(self):
        return f'<Sale {self.receipt_number}>'
    
    # =========================================================================
    # CALCULATION METHODS
    # =========================================================================
    
    def calculate_totals(self):
        """
        Calculate and update all sale totals
        Should be called whenever items or discounts change
        """
        items = self.sale_items.all()
        
        # Calculate subtotal
        self.subtotal = Decimal('0.00')
        for item in items:
            self.subtotal += item.line_total
        
        # Apply discount
        discount = (self.subtotal * self.discount_percentage / 100) if self.discount_percentage > 0 else Decimal(str(self.discount_amount or 0))
        
        # Calculate tax
        taxable_amount = self.subtotal - discount
        self.tax_amount = taxable_amount * (self.tax_rate / 100) if self.tax_rate > 0 else Decimal('0.00')
        
        # Calculate total
        self.total_amount = taxable_amount + self.tax_amount
        
        db.session.commit()
    
    def apply_discount(self, discount_percentage=None, discount_amount=None):
        """Apply discount to sale"""
        if discount_percentage:
            self.discount_percentage = Decimal(str(discount_percentage))
            self.discount_amount = Decimal('0.00')
        elif discount_amount:
            self.discount_amount = Decimal(str(discount_amount))
            self.discount_percentage = Decimal('0.00')
        
        self.calculate_totals()
    
    def get_discount_amount(self):
        """Get actual discount amount"""
        if self.discount_percentage > 0:
            return self.subtotal * (self.discount_percentage / 100)
        return self.discount_amount or Decimal('0.00')
    
    # =========================================================================
    # PAYMENT METHODS
    # =========================================================================
    
    def add_item(self, product_id, quantity, unit_price=None, discount=None):
        """
        Add item to sale
        
        Args:
            product_id (int): Product ID
            quantity (int): Quantity sold
            unit_price (Decimal): Override product price
            discount (Decimal): Item-level discount percentage
            
        Returns:
            SaleItem: Created sale item
        """
        from app.models.product import Product
        
        product = Product.query.get(product_id)
        if not product:
            raise ValueError(f'Product not found')
        
        if product.current_stock < quantity:
            raise ValueError(f'Insufficient stock for {product.name}')
        
        price = unit_price or product.selling_price
        
        sale_item = SaleItem(
            sale_id=self.id,
            product_id=product_id,
            quantity=quantity,
            unit_price=price,
            discount_percentage=discount or 0
        )
        
        # Reserve stock
        product.reserved_stock += quantity
        product.update_available_stock()
        
        db.session.add(sale_item)
        db.session.commit()
        
        # Recalculate totals
        self.calculate_totals()
        
        return sale_item
    
    def record_payment(self, payment_method, amount, reference=None):
        """
        Record payment for sale
        
        Args:
            payment_method (str): cash, card, cheque, transfer, mobile_money
            amount (Decimal): Payment amount
            reference (str): Reference number if applicable
        """
        if self.sale_type == 'cash':
            self.cash_paid += Decimal(str(amount))
            change = self.cash_paid - self.total_amount
            if change > 0:
                self.change_given = change
        elif self.sale_type == 'credit':
            self.credit_amount += Decimal(str(amount))
        elif self.sale_type == 'mixed':
            if payment_method == 'cash':
                self.cash_paid += Decimal(str(amount))
            else:
                self.credit_amount += Decimal(str(amount))
        
        db.session.commit()
    
    # =========================================================================
    # STATUS METHODS
    # =========================================================================
    
    def complete(self):
        """Mark sale as completed"""
        self.status = 'completed'
        
        # Update product stock
        for item in self.sale_items.all():
            product = item.product
            product.current_stock -= item.quantity
            product.reserved_stock -= item.quantity
            product.update_available_stock()
            
            # Create stock movement
            from app.models.product import StockMovement
            movement = StockMovement(
                tenant_id=self.tenant_id,
                product_id=product.id,
                movement_type='out',
                quantity=-item.quantity,
                reference_type='sale',
                reference_id=self.id,
                reference_number=self.receipt_number,
                created_by=self.created_by
            )
            db.session.add(movement)
        
        db.session.commit()
    
    def cancel(self):
        """Cancel the sale"""
        if self.status == 'completed':
            # Reverse stock reservation and movements
            for item in self.sale_items.all():
                product = item.product
                product.reserved_stock -= item.quantity
                product.current_stock += item.quantity
                product.update_available_stock()
        
        self.status = 'cancelled'
        db.session.commit()
    
    def create_invoice(self):
        """Create invoice from this sale"""
        if self.is_invoiced:
            return self.invoice
        
        invoice = Invoice(
            tenant_id=self.tenant_id,
            sale_id=self.id,
            client_id=self.client_id,
            invoice_date=self.sale_date,
            due_date=self.sale_date + timedelta(days=30),
            amount=self.total_amount,
            paid_amount=self.cash_paid,
            status='issued' if self.client_id else 'draft'
        )
        
        db.session.add(invoice)
        self.is_invoiced = True
        db.session.commit()
        
        return invoice
    
    # =========================================================================
    # DISPLAY METHODS
    # =========================================================================
    
    def get_customer_name(self):
        """Get customer name"""
        if self.client_id and self.client:
            return self.client.name
        return self.customer_name or 'Walk-in Customer'


class SaleItem(db.Model):
    """
    Sale Item model representing individual items in a sale
    """
    __tablename__ = 'sale_items'
    
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
    sale_id = db.Column(
        db.Integer,
        db.ForeignKey('sales.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    product_id = db.Column(
        db.Integer,
        db.ForeignKey('products.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    
    # Item Details
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    discount_percentage = db.Column(db.Numeric(5, 2), default=0)
    discount_amount = db.Column(db.Numeric(12, 2), default=0)
    
    # Calculated Fields
    line_subtotal = db.Column(db.Numeric(12, 2), nullable=False)
    line_discount = db.Column(db.Numeric(12, 2), default=0)
    line_total = db.Column(db.Numeric(12, 2), nullable=False)
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Table constraints
    __table_args__ = (
        Index('idx_sale_item_sale', 'sale_id'),
        Index('idx_sale_item_product', 'product_id'),
    )
    
    def __repr__(self):
        return f'<SaleItem Sale {self.sale_id} - Product {self.product_id}>'
    
    @staticmethod
    def calculate_line_total(quantity, unit_price, discount_percentage=0, discount_amount=0):
        """Calculate line total"""
        subtotal = Decimal(str(quantity)) * Decimal(str(unit_price))
        
        if discount_percentage > 0:
            discount = subtotal * (Decimal(str(discount_percentage)) / 100)
        else:
            discount = Decimal(str(discount_amount or 0))
        
        return subtotal - discount


class Invoice(db.Model):
    """
    Invoice model for formal invoicing
    Generated from sales for record keeping and credit tracking
    """
    __tablename__ = 'invoices'
    
    # Primary Key
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    
    # Tenant Association
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenants.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    
    # References
    sale_id = db.Column(
        db.Integer,
        db.ForeignKey('sales.id', ondelete='CASCADE'),
        nullable=True
    )
    client_id = db.Column(
        db.Integer,
        db.ForeignKey('clients.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )
    
    # Invoice Information
    invoice_number = db.Column(db.String(100), unique=True, nullable=False, index=True)
    invoice_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    due_date = db.Column(db.DateTime, nullable=False)
    
    # Amount Information
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    paid_amount = db.Column(db.Numeric(12, 2), default=0)
    outstanding_amount = db.Column(db.Numeric(12, 2), nullable=False, index=True)
    
    # Status
    status = db.Column(
        db.String(50),
        default='draft',
        nullable=False,
        index=True,
        comment='draft, issued, sent, overdue, paid, cancelled'
    )
    is_sent = db.Column(db.Boolean, default=False)
    is_paid = db.Column(db.Boolean, default=False, index=True)
    
    # Content
    terms = db.Column(db.Text, comment='Payment terms')
    notes = db.Column(db.Text)
    
    # Audit
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    sent_at = db.Column(db.DateTime)
    
    # Table constraints
    __table_args__ = (
        Index('idx_invoice_tenant_number', 'tenant_id', 'invoice_number'),
        Index('idx_invoice_client', 'client_id'),
        Index('idx_invoice_status', 'status'),
        Index('idx_invoice_date', 'invoice_date'),
    )
    
    def __repr__(self):
        return f'<Invoice {self.invoice_number}>'
    
    def send(self):
        """Mark invoice as sent"""
        self.is_sent = True
        self.sent_at = datetime.utcnow()
        self.status = 'sent'
        db.session.commit()
    
    def mark_paid(self):
        """Mark invoice as paid"""
        self.is_paid = True
        self.status = 'paid'
        self.outstanding_amount = Decimal('0.00')
        db.session.commit()


class Expense(db.Model):
    """
    Expense model for tracking business expenses
    Supports expense categorization and approval workflows
    """
    __tablename__ = 'expenses'
    
    # Primary Key
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    
    # Tenant Association
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenants.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    
    # Expense Details
    expense_number = db.Column(db.String(100), unique=True, nullable=False, index=True)
    expense_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Amount
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), default='USD')
    
    # Categorization
    category = db.Column(
        db.String(100),
        nullable=False,
        index=True,
        comment='utilities, rent, salaries, marketing, etc.'
    )
    subcategory = db.Column(db.String(100))
    
    # Description
    description = db.Column(db.Text, nullable=False)
    receipt_number = db.Column(db.String(100))
    vendor_name = db.Column(db.String(255))
    
    # Payment Method
    payment_method = db.Column(
        db.String(50),
        comment='cash, cheque, bank_transfer, card'
    )
    payment_reference = db.Column(db.String(100))
    
    # Attachments
    receipt_url = db.Column(db.String(500), comment='URL to receipt image/document')
    attachments = db.Column(
        JSONB if 'postgresql' in str(db.engine.url) else db.JSON,
        default=[],
        comment='Array of attachment URLs'
    )
    
    # Status & Approval
    status = db.Column(
        db.String(50),
        default='submitted',
        nullable=False,
        index=True,
        comment='submitted, approved, rejected, paid'
    )
    submitted_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True
    )
    approved_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        comment='User who approved the expense'
    )
    approved_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)
    
    # Tax Information
    is_taxable = db.Column(db.Boolean, default=False)
    tax_amount = db.Column(db.Numeric(12, 2), default=0)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    
    # Budget Allocation
    cost_center = db.Column(db.String(100), comment='Internal cost center code')
    project_code = db.Column(db.String(100), comment='Associated project code')
    
    # Notes
    notes = db.Column(db.Text)
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Table constraints
    __table_args__ = (
        Index('idx_expense_tenant_date', 'tenant_id', 'expense_date'),
        Index('idx_expense_category', 'category'),
        Index('idx_expense_status', 'status'),
        Index('idx_expense_vendor', 'vendor_name'),
        CheckConstraint('amount > 0', name='check_positive_amount'),
    )
    
    def __repr__(self):
        return f'<Expense {self.expense_number}>'
    
    # =========================================================================
    # STATUS METHODS
    # =========================================================================
    
    def approve(self, user_id):
        """Approve the expense"""
        self.status = 'approved'
        self.approved_by = user_id
        self.approved_at = datetime.utcnow()
        db.session.commit()
    
    def reject(self, user_id, reason):
        """Reject the expense"""
        self.status = 'rejected'
        self.approved_by = user_id
        self.approved_at = datetime.utcnow()
        self.rejection_reason = reason
        db.session.commit()
    
    def mark_paid(self):
        """Mark expense as paid"""
        self.status = 'paid'
        db.session.commit()


class CashFlow(db.Model):
    """
    CashFlow model for tracking cash inflows and outflows
    Provides real-time cash position monitoring
    """
    __tablename__ = 'cash_flows'
    
    # Primary Key
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    
    # Tenant Association
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenants.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    
    # Date
    transaction_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Transaction Type
    flow_type = db.Column(
        db.String(50),
        nullable=False,
        comment='inflow (revenue) or outflow (expense)'
    )
    
    # Source/Destination
    source_type = db.Column(
        db.String(100),
        nullable=False,
        comment='sale, payment, expense, loan, investment, tax, etc.'
    )
    reference_id = db.Column(db.Integer)
    reference_type = db.Column(db.String(100))
    
    # Amount
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    
    # Description
    description = db.Column(db.Text)
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Table constraints
    __table_args__ = (
        Index('idx_cashflow_tenant_date', 'tenant_id', 'transaction_date'),
        Index('idx_cashflow_source', 'source_type'),
    )
    
    def __repr__(self):
        return f'<CashFlow {self.flow_type} {self.amount}>'


class SalesMetrics(db.Model):
    """
    Sales Metrics model for pre-calculated dashboard data
    Improves performance by pre-computing aggregates
    """
    __tablename__ = 'sales_metrics'
    
    # Primary Key
    id = db.Column(db.Integer, primary_key=True)
    
    # Tenant Association
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenants.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    
    # Period
    metric_date = db.Column(db.Date, nullable=False, unique=True, index=True)
    
    # Sales Metrics
    total_sales = db.Column(db.Numeric(12, 2), default=0)
    total_cash_sales = db.Column(db.Numeric(12, 2), default=0)
    total_credit_sales = db.Column(db.Numeric(12, 2), default=0)
    number_of_transactions = db.Column(db.Integer, default=0)
    average_transaction_value = db.Column(db.Numeric(12, 2), default=0)
    
    # Revenue Metrics
    total_revenue = db.Column(db.Numeric(12, 2), default=0)
    total_tax_collected = db.Column(db.Numeric(12, 2), default=0)
    total_discounts_given = db.Column(db.Numeric(12, 2), default=0)
    
    # Expense Metrics
    total_expenses = db.Column(db.Numeric(12, 2), default=0)
    number_of_expenses = db.Column(db.Integer, default=0)
    
    # Payment Metrics
    total_payments_received = db.Column(db.Numeric(12, 2), default=0)
    number_of_payments = db.Column(db.Integer, default=0)
    
    # Debtors
    total_outstanding_debt = db.Column(db.Numeric(12, 2), default=0)
    total_overdue_debt = db.Column(db.Numeric(12, 2), default=0)
    number_of_debtors = db.Column(db.Integer, default=0)
    
    # Margins
    gross_profit = db.Column(db.Numeric(12, 2), default=0)
    net_profit = db.Column(db.Numeric(12, 2), default=0)
    profit_margin_percentage = db.Column(db.Numeric(5, 2), default=0)
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Table constraints
    __table_args__ = (
        Index('idx_metrics_tenant_date', 'tenant_id', 'metric_date'),
    )
    
    def __repr__(self):
        return f'<SalesMetrics {self.metric_date}>'
