# app/models/tenant.py
"""
Multi-tenant support models and user management
Handles tenant organizations, users, roles, and permissions
"""

from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event, Index, CheckConstraint, and_, or_
from sqlalchemy.dialects.postgresql import JSONB, UUID
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
import json

db = SQLAlchemy()


class Tenant(db.Model):
    """
    Tenant model representing an organization or business unit
    Supports multi-tenant architecture with isolated data
    """
    __tablename__ = 'tenants'
    
    # Primary Key
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4)
    
    # Basic Information
    name = db.Column(db.String(255), unique=True, nullable=False, index=True)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    country = db.Column(db.String(100))
    postal_code = db.Column(db.String(20))
    
    # Business Details
    business_registration = db.Column(db.String(100))
    tax_id = db.Column(db.String(50))
    business_type = db.Column(db.String(100))
    
    # Media
    logo_url = db.Column(db.String(500))
    favicon_url = db.Column(db.String(500))
    banner_url = db.Column(db.String(500))
    
    # Settings
    currency = db.Column(db.String(3), default='USD', nullable=False)
    timezone = db.Column(db.String(50), default='UTC', nullable=False)
    language = db.Column(db.String(10), default='en', nullable=False)
    date_format = db.Column(db.String(20), default='YYYY-MM-DD')
    time_format = db.Column(db.String(20), default='24H')
    
    # Subscription Information
    subscription_tier = db.Column(
        db.String(50),
        default='starter',
        nullable=False,
        index=True,
        comment='starter, professional, enterprise'
    )
    subscription_starts = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    subscription_expires = db.Column(db.DateTime)
    subscription_auto_renew = db.Column(db.Boolean, default=True)
    subscription_payment_method = db.Column(db.String(50))
    
    # Trial Period
    is_trial = db.Column(db.Boolean, default=False)
    trial_ends_at = db.Column(db.DateTime)
    
    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    is_verified = db.Column(db.Boolean, default=False)
    is_suspended = db.Column(db.Boolean, default=False)
    suspension_reason = db.Column(db.Text)
    
    # Feature Limits
    max_users = db.Column(db.Integer, default=5, nullable=False)
    max_products = db.Column(db.Integer, default=1000, nullable=False)
    max_clients = db.Column(db.Integer, default=100, nullable=False)
    max_sales_per_month = db.Column(db.Integer, default=10000)
    storage_limit_gb = db.Column(db.Integer, default=10, nullable=False)
    storage_used_gb = db.Column(db.Numeric(10, 2), default=0)
    
    # Feature Flags
    features = db.Column(
        JSONB if 'postgresql' in str(db.engine.url) else db.JSON,
        default={
            'stock_management': True,
            'revenue_tracking': True,
            'debtor_management': True,
            'automated_reminders': True,
            'camera_identification': False,
            'api_access': False,
            'analytics': True,
            'invoice_generation': True,
            'bulk_import': False,
            'multi_warehouse': False,
            'barcode_scanning': True,
            'qr_code_generation': False,
            'mobile_app': False,
            'custom_reports': False,
            'employee_management': False,
            'accounting_integration': False,
        },
        nullable=False
    )
    
    # Security Settings
    enforce_two_factor = db.Column(db.Boolean, default=False)
    require_password_change = db.Column(db.Boolean, default=False)
    password_expiry_days = db.Column(db.Integer, default=90)
    session_timeout_minutes = db.Column(db.Integer, default=30)
    
    # Integration Settings
    integrations = db.Column(
        JSONB if 'postgresql' in str(db.engine.url) else db.JSON,
        default={},
        nullable=False
    )
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = db.Column(db.DateTime)
    
    # Relationships
    users = db.relationship(
        'User',
        backref='tenant',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='User.tenant_id'
    )
    products = db.relationship(
        'Product',
        backref='tenant',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='Product.tenant_id'
    )
    sales = db.relationship(
        'Sale',
        backref='tenant',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='Sale.tenant_id'
    )
    clients = db.relationship(
        'Client',
        backref='tenant',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='Client.tenant_id'
    )
    stock_alerts = db.relationship(
        'StockAlert',
        backref='tenant',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='StockAlert.tenant_id'
    )
    invoices = db.relationship(
        'Invoice',
        backref='tenant',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='Invoice.tenant_id'
    )
    expenses = db.relationship(
        'Expense',
        backref='tenant',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='Expense.tenant_id'
    )
    activity_logs = db.relationship(
        'ActivityLog',
        backref='tenant',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='ActivityLog.tenant_id'
    )
    
    # Table constraints
    __table_args__ = (
        Index('idx_tenant_active_subscription', 'is_active', 'subscription_tier'),
        Index('idx_tenant_creation_date', 'created_at'),
        Index('idx_tenant_slug', 'slug'),
    )
    
    def __repr__(self):
        return f'<Tenant {self.name} ({self.slug})>'
    
    def __str__(self):
        return self.name
    
    # =========================================================================
    # FEATURE & SUBSCRIPTION METHODS
    # =========================================================================
    
    def is_feature_enabled(self, feature):
        """
        Check if a feature is enabled for this tenant
        
        Args:
            feature (str): Feature name to check
            
        Returns:
            bool: True if feature is enabled, False otherwise
        """
        return self.features.get(feature, False) if self.features else False
    
    def enable_feature(self, feature):
        """Enable a specific feature"""
        if not self.features:
            self.features = {}
        self.features[feature] = True
        db.session.commit()
    
    def disable_feature(self, feature):
        """Disable a specific feature"""
        if not self.features:
            self.features = {}
        self.features[feature] = False
        db.session.commit()
    
    def is_subscription_active(self):
        """Check if subscription is currently active"""
        if not self.subscription_expires:
            return True
        return datetime.utcnow() < self.subscription_expires
    
    def is_subscription_expiring_soon(self, days=7):
        """Check if subscription expires within specified days"""
        if not self.subscription_expires:
            return False
        days_until_expiry = (self.subscription_expires - datetime.utcnow()).days
        return 0 <= days_until_expiry <= days
    
    def get_subscription_days_remaining(self):
        """Get number of days remaining in subscription"""
        if not self.subscription_expires:
            return None
        remaining = (self.subscription_expires - datetime.utcnow()).days
        return max(0, remaining)
    
    def get_subscription_tier_config(self):
        """Get configuration for current subscription tier"""
        from config import CONFIG
        return CONFIG.SUBSCRIPTION_TIERS.get(self.subscription_tier, {})
    
    # =========================================================================
    # CAPACITY & USAGE METHODS
    # =========================================================================
    
    def can_add_product(self):
        """Check if tenant can add more products"""
        current_products = self.products.count()
        return current_products < self.max_products
    
    def can_add_user(self):
        """Check if tenant can add more users"""
        current_users = self.users.count()
        return current_users < self.max_users
    
    def can_add_client(self):
        """Check if tenant can add more clients"""
        current_clients = self.clients.count()
        return current_clients < self.max_clients
    
    def get_product_count(self):
        """Get current product count"""
        return self.products.count()
    
    def get_user_count(self):
        """Get current user count"""
        return self.users.count()
    
    def get_client_count(self):
        """Get current client count"""
        return self.clients.count()
    
    def get_storage_percentage_used(self):
        """Get storage usage percentage"""
        if self.storage_limit_gb == 0:
            return 0
        return (float(self.storage_used_gb) / self.storage_limit_gb) * 100
    
    def is_storage_full(self):
        """Check if storage is full"""
        return float(self.storage_used_gb) >= self.storage_limit_gb
    
    # =========================================================================
    # STATUS METHODS
    # =========================================================================
    
    def suspend(self, reason=''):
        """Suspend the tenant"""
        self.is_suspended = True
        self.suspension_reason = reason
        db.session.commit()
    
    def unsuspend(self):
        """Unsuspend the tenant"""
        self.is_suspended = False
        self.suspension_reason = None
        db.session.commit()
    
    def verify(self):
        """Mark tenant as verified"""
        self.is_verified = True
        db.session.commit()
    
    def deactivate(self):
        """Deactivate the tenant"""
        self.is_active = False
        db.session.commit()
    
    def activate(self):
        """Activate the tenant"""
        self.is_active = True
        db.session.commit()
    
    def can_perform_action(self):
        """Check if tenant can perform actions"""
        return self.is_active and not self.is_suspended and self.is_subscription_active()
    
    # =========================================================================
    # INTEGRATION METHODS
    # =========================================================================
    
    def get_integration(self, integration_name):
        """Get integration configuration"""
        if not self.integrations:
            return None
        return self.integrations.get(integration_name)
    
    def set_integration(self, integration_name, config):
        """Set integration configuration"""
        if not self.integrations:
            self.integrations = {}
        self.integrations[integration_name] = config
        db.session.commit()
    
    def remove_integration(self, integration_name):
        """Remove integration"""
        if self.integrations and integration_name in self.integrations:
            del self.integrations[integration_name]
            db.session.commit()


class User(db.Model):
    """
    User model representing application users
    Supports role-based access control and permissions
    """
    __tablename__ = 'users'
    
    # Primary Key
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4)
    
    # Tenant Association
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenants.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    
    # Authentication
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username = db.Column(db.String(100), nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    
    # Profile Information
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    avatar_url = db.Column(db.String(500))
    bio = db.Column(db.Text)
    
    # Role & Permissions
    role = db.Column(
        db.String(50),
        default='staff',
        nullable=False,
        index=True,
        comment='admin, manager, staff, viewer'
    )
    
    permissions = db.Column(
        JSONB if 'postgresql' in str(db.engine.url) else db.JSON,
        default={
            'view_dashboard': True,
            'manage_products': False,
            'manage_sales': False,
            'manage_clients': False,
            'manage_expenses': False,
            'view_reports': False,
            'manage_users': False,
            'system_settings': False,
            'manage_stock': False,
            'manage_invoices': False,
            'manage_debtors': False,
        },
        nullable=False
    )
    
    # Account Status
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    is_verified = db.Column(db.Boolean, default=False)
    is_locked = db.Column(db.Boolean, default=False)
    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    
    # Two-Factor Authentication
    two_factor_enabled = db.Column(db.Boolean, default=False)
    two_factor_secret = db.Column(db.String(32))
    backup_codes = db.Column(db.JSON)
    
    # Password Management
    last_password_change = db.Column(db.DateTime)
    password_reset_token = db.Column(db.String(255), unique=True, sparse=True)
    password_reset_expires = db.Column(db.DateTime)
    require_password_change = db.Column(db.Boolean, default=False)
    
    # Session Management
    last_login = db.Column(db.DateTime)
    last_login_ip = db.Column(db.String(45))
    last_login_user_agent = db.Column(db.String(500))
    
    # Email Verification
    email_verified_at = db.Column(db.DateTime)
    email_verification_token = db.Column(db.String(255), unique=True, sparse=True)
    
    # Preferences
    preferences = db.Column(
        JSONB if 'postgresql' in str(db.engine.url) else db.JSON,
        default={
            'theme': 'dark',
            'notifications_email': True,
            'notifications_sms': False,
            'notifications_in_app': True,
            'dashboard_widgets': [],
            'items_per_page': 20,
        },
        nullable=False
    )
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = db.Column(db.DateTime)
    
    # Relationships
    activity_logs = db.relationship(
        'ActivityLog',
        backref='user',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='ActivityLog.user_id'
    )
    sales = db.relationship(
        'Sale',
        backref='created_by_user',
        lazy='dynamic',
        foreign_keys='Sale.created_by'
    )
    
    # Table constraints
    __table_args__ = (
        Index('idx_user_tenant_email', 'tenant_id', 'email'),
        Index('idx_user_active', 'is_active'),
        Index('idx_user_role', 'role'),
        CheckConstraint("email ~ '^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$'", name='valid_email'),
    )
    
    def __repr__(self):
        return f'<User {self.username} ({self.email})>'
    
    def __str__(self):
        return self.username
    
    # =========================================================================
    # PASSWORD METHODS
    # =========================================================================
    
    def set_password(self, password):
        """
        Hash and set user password
        
        Args:
            password (str): Plain text password
        """
        self.password_hash = generate_password_hash(
            password,
            method='pbkdf2:sha256',
            salt_length=16
        )
        self.last_password_change = datetime.utcnow()
    
    def check_password(self, password):
        """
        Verify password against hash
        
        Args:
            password (str): Plain text password to verify
            
        Returns:
            bool: True if password matches, False otherwise
        """
        return check_password_hash(self.password_hash, password)
    
    def generate_password_reset_token(self):
        """Generate password reset token"""
        import secrets
        token = secrets.token_urlsafe(32)
        self.password_reset_token = token
        self.password_reset_expires = datetime.utcnow() + timedelta(hours=24)
        db.session.commit()
        return token
    
    def reset_password(self, new_password):
        """Reset password using token"""
        self.set_password(new_password)
        self.password_reset_token = None
        self.password_reset_expires = None
        db.session.commit()
    
    def is_password_expired(self):
        """Check if password has expired"""
        if not self.last_password_change:
            return False
        days_since_change = (datetime.utcnow() - self.last_password_change).days
        return days_since_change > self.tenant.password_expiry_days
    
    # =========================================================================
    # AUTHENTICATION & AUTHORIZATION METHODS
    # =========================================================================
    
    def has_permission(self, permission):
        """
        Check if user has specific permission
        
        Args:
            permission (str): Permission name to check
            
        Returns:
            bool: True if user has permission, False otherwise
        """
        if self.role == 'admin':
            return True
        
        if not self.permissions:
            return False
        
        return self.permissions.get(permission, False)
    
    def has_role(self, *roles):
        """
        Check if user has any of the specified roles
        
        Args:
            *roles: Role names to check
            
        Returns:
            bool: True if user has any of the roles
        """
        return self.role in roles
    
    def has_all_permissions(self, *permissions):
        """Check if user has all specified permissions"""
        return all(self.has_permission(perm) for perm in permissions)
    
    def grant_permission(self, permission):
        """Grant a permission to user"""
        if not self.permissions:
            self.permissions = {}
        self.permissions[permission] = True
        db.session.commit()
    
    def revoke_permission(self, permission):
        """Revoke a permission from user"""
        if not self.permissions:
            self.permissions = {}
        self.permissions[permission] = False
        db.session.commit()
    
    def set_role(self, role):
        """
        Set user role and update permissions accordingly
        
        Args:
            role (str): Role name (admin, manager, staff, viewer)
        """
        self.role = role
        
        if role == 'admin':
            self.permissions = {
                'view_dashboard': True,
                'manage_products': True,
                'manage_sales': True,
                'manage_clients': True,
                'manage_expenses': True,
                'view_reports': True,
                'manage_users': True,
                'system_settings': True,
                'manage_stock': True,
                'manage_invoices': True,
                'manage_debtors': True,
            }
        elif role == 'manager':
            self.permissions = {
                'view_dashboard': True,
                'manage_products': True,
                'manage_sales': True,
                'manage_clients': True,
                'manage_expenses': True,
                'view_reports': True,
                'manage_users': False,
                'system_settings': False,
                'manage_stock': True,
                'manage_invoices': True,
                'manage_debtors': True,
            }
        elif role == 'staff':
            self.permissions = {
                'view_dashboard': True,
                'manage_products': False,
                'manage_sales': True,
                'manage_clients': False,
                'manage_expenses': False,
                'view_reports': False,
                'manage_users': False,
                'system_settings': False,
                'manage_stock': False,
                'manage_invoices': False,
                'manage_debtors': False,
            }
        else:  # viewer
            self.permissions = {
                'view_dashboard': True,
                'manage_products': False,
                'manage_sales': False,
                'manage_clients': False,
                'manage_expenses': False,
                'view_reports': False,
                'manage_users': False,
                'system_settings': False,
                'manage_stock': False,
                'manage_invoices': False,
                'manage_debtors': False,
            }
        
        db.session.commit()
    
    # =========================================================================
    # ACCOUNT STATUS METHODS
    # =========================================================================
    
    def is_account_locked(self):
        """Check if account is locked"""
        if not self.is_locked:
            return False
        
        if self.locked_until and datetime.utcnow() > self.locked_until:
            self.is_locked = False
            self.failed_login_attempts = 0
            db.session.commit()
            return False
        
        return True
    
    def record_failed_login(self):
        """Record failed login attempt"""
        self.failed_login_attempts += 1
        
        if self.failed_login_attempts >= 5:
            self.is_locked = True
            self.locked_until = datetime.utcnow() + timedelta(minutes=30)
        
        db.session.commit()
    
    def record_successful_login(self, ip_address='', user_agent=''):
        """Record successful login"""
        self.last_login = datetime.utcnow()
        self.last_login_ip = ip_address
        self.last_login_user_agent = user_agent
        self.failed_login_attempts = 0
        self.is_locked = False
        self.locked_until = None
        db.session.commit()
    
    def unlock_account(self):
        """Unlock account"""
        self.is_locked = False
        self.locked_until = None
        self.failed_login_attempts = 0
        db.session.commit()
    
    def activate(self):
        """Activate user account"""
        self.is_active = True
        db.session.commit()
    
    def deactivate(self):
        """Deactivate user account"""
        self.is_active = False
        db.session.commit()
    
    # =========================================================================
    # VERIFICATION METHODS
    # =========================================================================
    
    def generate_email_verification_token(self):
        """Generate email verification token"""
        import secrets
        token = secrets.token_urlsafe(32)
        self.email_verification_token = token
        db.session.commit()
        return token
    
    def verify_email(self):
        """Mark email as verified"""
        self.is_verified = True
        self.email_verified_at = datetime.utcnow()
        self.email_verification_token = None
        db.session.commit()
    
    # =========================================================================
    # PREFERENCE METHODS
    # =========================================================================
    
    def get_preference(self, key, default=None):
        """Get user preference"""
        if not self.preferences:
            return default
        return self.preferences.get(key, default)
    
    def set_preference(self, key, value):
        """Set user preference"""
        if not self.preferences:
            self.preferences = {}
        self.preferences[key] = value
        db.session.commit()
    
    # =========================================================================
    # DISPLAY METHODS
    # =========================================================================
    
    def get_full_name(self):
        """Get user's full name"""
        if self.first_name and self.last_name:
            return f'{self.first_name} {self.last_name}'
        return self.first_name or self.last_name or self.username
    
    def get_initials(self):
        """Get user's initials"""
        first = self.first_name[0] if self.first_name else ''
        last = self.last_name[0] if self.last_name else ''
        return (first + last).upper()


class ActivityLog(db.Model):
    """
    Activity Log model for audit trail
    Tracks all user actions for security and compliance
    """
    __tablename__ = 'activity_logs'
    
    # Primary Key
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4)
    
    # Association
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenants.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        index=True
    )
    
    # Activity Details
    action = db.Column(db.String(255), nullable=False, index=True)
    action_type = db.Column(
        db.String(50),
        nullable=False,
        comment='CREATE, READ, UPDATE, DELETE, LOGIN, EXPORT'
    )
    resource_type = db.Column(db.String(100), nullable=False, index=True)
    resource_id = db.Column(db.Integer)
    resource_name = db.Column(db.String(255))
    
    # Change Tracking
    old_values = db.Column(
        JSONB if 'postgresql' in str(db.engine.url) else db.JSON
    )
    new_values = db.Column(
        JSONB if 'postgresql' in str(db.engine.url) else db.JSON
    )
    
    # Request Information
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))
    http_method = db.Column(db.String(10))
    endpoint = db.Column(db.String(255))
    status_code = db.Column(db.Integer)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Table constraints
    __table_args__ = (
        Index('idx_activity_tenant_user_action', 'tenant_id', 'user_id', 'action'),
        Index('idx_activity_resource', 'resource_type', 'resource_id'),
        Index('idx_activity_timestamp', 'created_at'),
    )
    
    def __repr__(self):
        return f'<ActivityLog {self.action}>'
    
    def get_change_summary(self):
        """Get human-readable summary of changes"""
        if not self.old_values or not self.new_values:
            return None
        
        changes = []
        for key, old_val in self.old_values.items():
            new_val = self.new_values.get(key)
            if old_val != new_val:
                changes.append(f'{key}: {old_val} → {new_val}')
        
        return ', '.join(changes)


@event.listens_for(User, 'before_insert')
@event.listens_for(User, 'before_update')
def before_user_save(mapper, connection, target):
    """Validate user before save"""
    if not target.username:
        target.username = target.email.split('@')[0]


@event.listens_for(Tenant, 'after_insert')
def after_tenant_created(mapper, connection, target):
    """Actions to perform after tenant creation"""
    # Could trigger initialization tasks
    pass
