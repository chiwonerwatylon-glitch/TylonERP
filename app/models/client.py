# app/models/client.py
"""
Client and Debtor Management Models
Handles credit customers, debt tracking, and payment management
with automated reminder system
"""

from datetime import datetime, timedelta
from sqlalchemy import event, Index, CheckConstraint, and_, or_, func
from sqlalchemy.dialects.postgresql import JSONB
from decimal import Decimal
import uuid

from app.models.tenant import db


class Client(db.Model):
    """
    Client model for credit customers
    Tracks customer information, credit limits, and payment history
    """
    __tablename__ = 'clients'
    
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
    
    # Basic Information
    name = db.Column(db.String(255), nullable=False, index=True)
    email = db.Column(db.String(255), index=True)
    phone = db.Column(db.String(20), index=True)
    phone_secondary = db.Column(db.String(20))
    
    # Business Information
    business_name = db.Column(db.String(255))
    business_type = db.Column(
        db.String(100),
        comment='retail, wholesale, distributor, individual'
    )
    registration_number = db.Column(db.String(100))
    tax_id = db.Column(db.String(50))
    
    # Address Information
    address = db.Column(db.Text)
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    country = db.Column(db.String(100))
    postal_code = db.Column(db.String(20))
    billing_address = db.Column(db.Text)
    shipping_address = db.Column(db.Text)
    
    # Credit Information
    credit_limit = db.Column(
        db.Numeric(12, 2),
        default=0,
        nullable=False,
        comment='Maximum credit allowed'
    )
    available_credit = db.Column(
        db.Numeric(12, 2),
        default=0,
        nullable=False,
        comment='Remaining credit available'
    )
    credit_days = db.Column(
        db.Integer,
        default=30,
        nullable=False,
        comment='Payment terms in days'
    )
    
    # Outstanding Balance
    total_debt = db.Column(
        db.Numeric(12, 2),
        default=0,
        nullable=False,
        index=True,
        comment='Total outstanding debt'
    )
    overdue_amount = db.Column(
        db.Numeric(12, 2),
        default=0,
        nullable=False,
        comment='Amount past due'
    )
    
    # Credit Status
    credit_status = db.Column(
        db.String(50),
        default='active',
        nullable=False,
        index=True,
        comment='active, suspended, blacklisted, inactive'
    )
    is_blacklisted = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
        index=True
    )
    blacklist_reason = db.Column(db.Text)
    blacklist_date = db.Column(db.DateTime)
    credit_suspended_until = db.Column(db.DateTime)
    
    # Transaction History
    total_purchases = db.Column(db.Numeric(12, 2), default=0)
    total_paid = db.Column(db.Numeric(12, 2), default=0)
    total_returns = db.Column(db.Numeric(12, 2), default=0)
    total_adjustments = db.Column(db.Numeric(12, 2), default=0)
    
    # Metrics
    number_of_orders = db.Column(db.Integer, default=0)
    number_of_overdue_invoices = db.Column(db.Integer, default=0, index=True)
    average_payment_days = db.Column(db.Numeric(5, 1), comment='Average days to pay')
    
    # Contact Preferences
    preferred_contact_method = db.Column(
        db.String(50),
        default='email',
        comment='email, sms, phone, mail'
    )
    do_not_contact = db.Column(db.Boolean, default=False)
    contact_frequency = db.Column(
        db.String(50),
        default='monthly',
        comment='on_purchase, weekly, bi_weekly, monthly'
    )
    
    # Payment Preferences
    payment_method = db.Column(
        db.String(100),
        comment='bank_transfer, cheque, cash, card, mobile_money'
    )
    bank_account = db.Column(db.String(100))
    bank_name = db.Column(db.String(255))
    bank_code = db.Column(db.String(50))
    
    # Tax Information
    is_tax_exempt = db.Column(db.Boolean, default=False)
    tax_certificate_number = db.Column(db.String(100))
    
    # Additional Information
    notes = db.Column(db.Text, comment='Internal notes about client')
    tags = db.Column(
        JSONB if 'postgresql' in str(db.engine.url) else db.JSON,
        default=[],
        comment='Customer tags for categorization'
    )
    metadata = db.Column(
        JSONB if 'postgresql' in str(db.engine.url) else db.JSON,
        default={},
        comment='Additional custom fields'
    )
    
    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = db.Column(db.DateTime)
    
    # Relationships
    debts = db.relationship(
        'Debt',
        backref='client',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='Debt.client_id'
    )
    payments = db.relationship(
        'Payment',
        backref='client',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='Payment.client_id'
    )
    sales = db.relationship(
        'Sale',
        backref='client',
        lazy='dynamic',
        foreign_keys='Sale.client_id'
    )
    debt_reminders = db.relationship(
        'DebtReminder',
        backref='client',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='DebtReminder.client_id'
    )
    contact_history = db.relationship(
        'ContactHistory',
        backref='client',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='ContactHistory.client_id'
    )
    
    # Table constraints
    __table_args__ = (
        Index('idx_client_tenant_name', 'tenant_id', 'name'),
        Index('idx_client_credit_status', 'tenant_id', 'credit_status'),
        Index('idx_client_overdue', 'tenant_id', 'overdue_amount'),
        Index('idx_client_active', 'tenant_id', 'is_active'),
        CheckConstraint('credit_limit >= 0', name='check_positive_credit'),
    )
    
    def __repr__(self):
        return f'<Client {self.name}>'
    
    def __str__(self):
        return self.name
    
    # =========================================================================
    # CREDIT MANAGEMENT METHODS
    # =========================================================================
    
    def can_extend_credit(self, amount):
        """
        Check if client can be extended requested credit
        
        Args:
            amount (Decimal): Credit amount requested
            
        Returns:
            bool: True if credit can be extended
        """
        if self.is_blacklisted:
            return False
        
        if self.credit_status == 'suspended':
            return False
        
        if float(amount) > float(self.available_credit):
            return False
        
        return True
    
    def get_available_credit(self):
        """Calculate available credit"""
        return float(self.credit_limit) - float(self.total_debt)
    
    def update_available_credit(self):
        """Update available credit based on debts"""
        self.available_credit = Decimal(str(self.get_available_credit()))
        db.session.commit()
    
    def use_credit(self, amount):
        """Use available credit"""
        if not self.can_extend_credit(amount):
            raise ValueError(f'Insufficient credit available')
        
        self.total_debt = Decimal(str(float(self.total_debt) + float(amount)))
        self.update_available_credit()
    
    def reduce_debt(self, amount):
        """Reduce outstanding debt"""
        self.total_debt = Decimal(str(max(0, float(self.total_debt) - float(amount))))
        self.update_available_credit()
    
    # =========================================================================
    # CREDIT STATUS METHODS
    # =========================================================================
    
    def blacklist(self, reason=''):
        """Blacklist the client"""
        self.is_blacklisted = True
        self.credit_status = 'blacklisted'
        self.blacklist_reason = reason
        self.blacklist_date = datetime.utcnow()
        self.credit_suspended_until = None
        db.session.commit()
    
    def remove_from_blacklist(self):
        """Remove client from blacklist"""
        self.is_blacklisted = False
        self.credit_status = 'active'
        self.blacklist_reason = None
        self.blacklist_date = None
        db.session.commit()
    
    def suspend_credit(self, until_date=None):
        """
        Temporarily suspend credit
        
        Args:
            until_date (datetime): Date to resume credit
        """
        self.credit_status = 'suspended'
        self.credit_suspended_until = until_date or (datetime.utcnow() + timedelta(days=30))
        db.session.commit()
    
    def resume_credit(self):
        """Resume suspended credit"""
        self.credit_status = 'active'
        self.credit_suspended_until = None
        db.session.commit()
    
    def is_credit_suspended(self):
        """Check if credit is currently suspended"""
        if self.credit_status != 'suspended':
            return False
        
        if self.credit_suspended_until and datetime.utcnow() > self.credit_suspended_until:
            self.resume_credit()
            return False
        
        return True
    
    # =========================================================================
    # DEBT ANALYSIS METHODS
    # =========================================================================
    
    def get_total_overdue(self):
        """Get total overdue amount"""
        overdue_debts = self.debts.filter(
            Debt.due_date < datetime.utcnow(),
            Debt.is_settled == False
        ).all()
        
        total = sum(float(debt.outstanding_amount) for debt in overdue_debts)
        return Decimal(str(total))
    
    def get_overdue_invoices(self):
        """Get list of overdue invoices"""
        return self.debts.filter(
            Debt.due_date < datetime.utcnow(),
            Debt.is_settled == False
        ).all()
    
    def get_upcoming_due_invoices(self, days=3):
        """Get invoices due within specified days"""
        future_date = datetime.utcnow() + timedelta(days=days)
        return self.debts.filter(
            and_(
                Debt.due_date >= datetime.utcnow(),
                Debt.due_date <= future_date,
                Debt.is_settled == False
            )
        ).all()
    
    def get_days_overdue(self):
        """Get maximum days overdue for any invoice"""
        overdue_invoices = self.get_overdue_invoices()
        if not overdue_invoices:
            return 0
        
        max_days = max(
            (datetime.utcnow() - inv.due_date).days
            for inv in overdue_invoices
        )
        return max_days
    
    def get_payment_history(self, limit=10):
        """Get recent payment history"""
        return self.payments.order_by(
            db.desc(Payment.payment_date)
        ).limit(limit).all()
    
    def calculate_average_payment_days(self):
        """Calculate average days to pay"""
        payments = self.payments.filter(Payment.debt_id != None).all()
        if not payments:
            return None
        
        total_days = 0
        count = 0
        for payment in payments:
            if payment.debt:
                days = (payment.payment_date - payment.debt.invoice_date).days
                total_days += days
                count += 1
        
        if count == 0:
            return None
        
        avg = total_days / count
        self.average_payment_days = Decimal(str(avg))
        db.session.commit()
        return avg
    
    # =========================================================================
    # RISK ASSESSMENT METHODS
    # =========================================================================
    
    def get_credit_risk_score(self):
        """
        Calculate credit risk score (0-100)
        Higher score = higher risk
        
        Returns:
            int: Risk score 0-100
        """
        score = 0
        
        # Overdue factor (max 40 points)
        overdue_pct = float(self.overdue_amount) / float(self.credit_limit) if self.credit_limit > 0 else 0
        score += min(40, int(overdue_pct * 100))
        
        # Payment history factor (max 30 points)
        days_overdue = self.get_days_overdue()
        if days_overdue > 60:
            score += 30
        elif days_overdue > 30:
            score += 20
        elif days_overdue > 0:
            score += 10
        
        # Utilization factor (max 20 points)
        utilization = float(self.total_debt) / float(self.credit_limit) if self.credit_limit > 0 else 0
        if utilization > 0.9:
            score += 20
        elif utilization > 0.7:
            score += 10
        
        # Credit status factor (max 10 points)
        if self.credit_status == 'blacklisted':
            score += 10
        elif self.credit_status == 'suspended':
            score += 5
        
        return min(100, score)
    
    def get_credit_risk_level(self):
        """Get risk level classification"""
        score = self.get_credit_risk_score()
        
        if score >= 80:
            return 'critical'
        elif score >= 60:
            return 'high'
        elif score >= 40:
            return 'medium'
        else:
            return 'low'
    
    def get_risk_level_color(self):
        """Get color for risk level"""
        level = self.get_credit_risk_level()
        colors = {
            'low': 'success',
            'medium': 'warning',
            'high': 'danger',
            'critical': 'dark'
        }
        return colors.get(level, 'secondary')
    
    # =========================================================================
    # STATUS METHODS
    # =========================================================================
    
    def activate(self):
        """Activate client account"""
        self.is_active = True
        db.session.commit()
    
    def deactivate(self):
        """Deactivate client account"""
        self.is_active = False
        db.session.commit()


class Debt(db.Model):
    """
    Debt model representing individual customer debts
    Tracks invoice amounts, due dates, and payment status
    """
    __tablename__ = 'debts'
    
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
    client_id = db.Column(
        db.Integer,
        db.ForeignKey('clients.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    sale_id = db.Column(
        db.Integer,
        db.ForeignKey('sales.id', ondelete='CASCADE'),
        nullable=True
    )
    
    # Debt Information
    invoice_number = db.Column(db.String(100), unique=True, nullable=False, index=True)
    invoice_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    due_date = db.Column(db.DateTime, nullable=False, index=True)
    
    # Amount Information
    original_amount = db.Column(db.Numeric(12, 2), nullable=False)
    paid_amount = db.Column(db.Numeric(12, 2), default=0)
    outstanding_amount = db.Column(db.Numeric(12, 2), nullable=False, index=True)
    late_fees = db.Column(db.Numeric(12, 2), default=0)
    
    # Status
    is_settled = db.Column(db.Boolean, default=False, nullable=False, index=True)
    is_disputed = db.Column(db.Boolean, default=False)
    dispute_reason = db.Column(db.Text)
    
    # Due Status
    is_overdue = db.Column(db.Boolean, default=False, nullable=False, index=True)
    days_overdue = db.Column(db.Integer, default=0, comment='Calculated number of days overdue')
    
    # Payment Terms
    discount_if_paid_by = db.Column(
        db.DateTime,
        comment='Early payment discount if paid by this date'
    )
    discount_percentage = db.Column(db.Numeric(5, 2), default=0)
    
    # Description
    description = db.Column(db.Text, comment='Debt description or reason')
    notes = db.Column(db.Text)
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    payments = db.relationship(
        'Payment',
        backref='debt',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='Payment.debt_id'
    )
    reminders = db.relationship(
        'DebtReminder',
        backref='debt',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='DebtReminder.debt_id'
    )
    
    # Table constraints
    __table_args__ = (
        Index('idx_debt_tenant_client', 'tenant_id', 'client_id'),
        Index('idx_debt_invoice', 'invoice_number'),
        Index('idx_debt_due_date', 'due_date'),
        Index('idx_debt_status', 'is_settled', 'is_overdue'),
    )
    
    def __repr__(self):
        return f'<Debt {self.invoice_number}>'
    
    # =========================================================================
    # STATUS METHODS
    # =========================================================================
    
    def update_overdue_status(self):
        """Update overdue status and calculate days overdue"""
        if not self.is_settled and datetime.utcnow() > self.due_date:
            self.is_overdue = True
            self.days_overdue = (datetime.utcnow() - self.due_date).days
        else:
            self.is_overdue = False
            self.days_overdue = 0
        
        db.session.commit()
    
    def record_payment(self, amount, payment_date=None):
        """
        Record a payment against this debt
        
        Args:
            amount (Decimal): Payment amount
            payment_date (datetime): Date of payment
        """
        payment = Payment(
            tenant_id=self.tenant_id,
            client_id=self.client_id,
            debt_id=self.id,
            amount=amount,
            payment_date=payment_date or datetime.utcnow()
        )
        db.session.add(payment)
        
        self.paid_amount = Decimal(str(float(self.paid_amount) + float(amount)))
        self.outstanding_amount = self.original_amount - self.paid_amount
        
        if self.outstanding_amount <= 0:
            self.is_settled = True
        
        self.updated_at = datetime.utcnow()
        db.session.commit()
        
        return payment
    
    def settle(self):
        """Mark debt as settled"""
        self.is_settled = True
        self.is_overdue = False
        self.outstanding_amount = Decimal('0.00')
        db.session.commit()
    
    def mark_disputed(self, reason):
        """Mark debt as disputed"""
        self.is_disputed = True
        self.dispute_reason = reason
        db.session.commit()
    
    # =========================================================================
    # CALCULATION METHODS
    # =========================================================================
    
    def calculate_days_until_due(self):
        """Calculate days until debt is due"""
        days = (self.due_date - datetime.utcnow()).days
        return max(0, days)
    
    def is_eligible_for_discount(self):
        """Check if debt is eligible for early payment discount"""
        if not self.discount_if_paid_by or self.discount_percentage <= 0:
            return False
        return datetime.utcnow() <= self.discount_if_paid_by
    
    def get_discounted_amount(self):
        """Get amount if early payment discount is applied"""
        if self.is_eligible_for_discount():
            discount = self.outstanding_amount * (self.discount_percentage / 100)
            return self.outstanding_amount - discount
        return self.outstanding_amount
    
    def get_payment_percentage(self):
        """Get payment completion percentage"""
        if self.original_amount == 0:
            return 100
        return (float(self.paid_amount) / float(self.original_amount)) * 100


class Payment(db.Model):
    """
    Payment model for tracking client payments
    Records all payments received from debtors
    """
    __tablename__ = 'payments'
    
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
    client_id = db.Column(
        db.Integer,
        db.ForeignKey('clients.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    debt_id = db.Column(
        db.Integer,
        db.ForeignKey('debts.id', ondelete='SET NULL'),
        index=True,
        comment='NULL if payment is not against specific debt'
    )
    
    # Payment Details
    payment_number = db.Column(db.String(100), unique=True, nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    payment_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Payment Method
    payment_method = db.Column(
        db.String(50),
        nullable=False,
        comment='cash, cheque, bank_transfer, card, mobile_money'
    )
    reference_number = db.Column(
        db.String(100),
        comment='Cheque number, bank reference, transaction ID'
    )
    
    # Status
    is_verified = db.Column(db.Boolean, default=False)
    verification_date = db.Column(db.DateTime)
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    
    # Description & Notes
    description = db.Column(db.Text)
    notes = db.Column(db.Text)
    
    # Audit
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Table constraints
    __table_args__ = (
        Index('idx_payment_tenant_client', 'tenant_id', 'client_id'),
        Index('idx_payment_date', 'payment_date'),
        Index('idx_payment_verified', 'is_verified'),
    )
    
    def __repr__(self):
        return f'<Payment {self.payment_number}>'
    
    def verify(self, user_id):
        """Verify the payment"""
        self.is_verified = True
        self.verification_date = datetime.utcnow()
        self.verified_by = user_id
        db.session.commit()


class DebtReminder(db.Model):
    """
    Debt Reminder model for automated payment reminders
    Handles scheduling and tracking of reminder communications
    """
    __tablename__ = 'debt_reminders'
    
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
    client_id = db.Column(
        db.Integer,
        db.ForeignKey('clients.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    debt_id = db.Column(
        db.Integer,
        db.ForeignKey('debts.id', ondelete='CASCADE'),
        nullable=True
    )
    
    # Reminder Details
    reminder_type = db.Column(
        db.String(50),
        nullable=False,
        comment='purchase_notification, pre_due_reminder, due_date_reminder, overdue_reminder'
    )
    scheduled_date = db.Column(db.DateTime, nullable=False, index=True)
    
    # Content
    subject = db.Column(db.String(255))
    message = db.Column(db.Text)
    reminder_count = db.Column(db.Integer, default=0, comment='Number of times reminded')
    
    # Delivery
    delivery_method = db.Column(
        db.String(50),
        default='email',
        comment='email, sms, push, in_app'
    )
    recipient = db.Column(db.String(255), comment='Email or phone number')
    
    # Status
    is_sent = db.Column(db.Boolean, default=False, nullable=False, index=True)
    sent_at = db.Column(db.DateTime)
    is_read = db.Column(db.Boolean, default=False)
    read_at = db.Column(db.DateTime)
    
    # Bounce Handling
    has_bounced = db.Column(db.Boolean, default=False)
    bounce_reason = db.Column(db.Text)
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Table constraints
    __table_args__ = (
        Index('idx_reminder_tenant_client', 'tenant_id', 'client_id'),
        Index('idx_reminder_scheduled', 'scheduled_date'),
        Index('idx_reminder_status', 'is_sent', 'is_read'),
    )
    
    def __repr__(self):
        return f'<DebtReminder {self.reminder_type}>'
    
    # =========================================================================
    # STATUS METHODS
    # =========================================================================
    
    def mark_sent(self):
        """Mark reminder as sent"""
        self.is_sent = True
        self.sent_at = datetime.utcnow()
        self.reminder_count += 1
        db.session.commit()
    
    def mark_read(self):
        """Mark reminder as read"""
        self.is_read = True
        self.read_at = datetime.utcnow()
        db.session.commit()
    
    def mark_bounced(self, reason=''):
        """Mark reminder as bounced"""
        self.has_bounced = True
        self.bounce_reason = reason
        db.session.commit()
    
    def is_due_to_send(self):
        """Check if reminder is due to be sent"""
        return (
            not self.is_sent and
            datetime.utcnow() >= self.scheduled_date
        )
    
    def should_resend(self):
        """Check if reminder should be resent"""
        if not self.is_sent:
            return False
        
        # Resend if was bounced
        if self.has_bounced:
            return True
        
        # Resend if not read after 7 days
        if not self.is_read and self.sent_at:
            days_since_sent = (datetime.utcnow() - self.sent_at).days
            return days_since_sent >= 7
        
        return False


class ContactHistory(db.Model):
    """
    Contact History model for tracking communication with clients
    Records all communication attempts
    """
    __tablename__ = 'contact_history'
    
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
    client_id = db.Column(
        db.Integer,
        db.ForeignKey('clients.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    
    # Contact Details
    contact_type = db.Column(
        db.String(50),
        nullable=False,
        comment='reminder_email, reminder_sms, phone_call, in_person, letter'
    )
    contact_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    contact_method = db.Column(db.String(50), comment='email, sms, phone, in_person, letter')
    
    # Content
    subject = db.Column(db.String(255))
    message = db.Column(db.Text)
    response = db.Column(db.Text)
    
    # Outcome
    outcome = db.Column(
        db.String(100),
        comment='no_response, promise_to_pay, partial_payment, full_payment, dispute, do_not_contact'
    )
    outcome_notes = db.Column(db.Text)
    
    # By Whom
    contacted_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL')
    )
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Table constraints
    __table_args__ = (
        Index('idx_contact_tenant_client', 'tenant_id', 'client_id'),
        Index('idx_contact_date', 'contact_date'),
    )
    
    def __repr__(self):
        return f'<ContactHistory {self.contact_type}>'
