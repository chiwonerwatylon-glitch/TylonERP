# config.py
"""
Comprehensive Flask Application Configuration
Multi-tenant ERP System with Production-Grade Settings
"""

import os
import sys
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler

# Load environment variables
load_dotenv()

# Base directory
BASE_DIR = Path(__file__).resolve().parent


class BaseConfig:
    """
    Base configuration class with common settings
    Provides all essential Flask and application configurations
    """
    
    # ============================================================================
    # FLASK CORE CONFIGURATION
    # ============================================================================
    
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production-12345')
    DEBUG = False
    TESTING = False
    ENV = os.getenv('FLASK_ENV', 'development')
    PROPAGATE_EXCEPTIONS = True
    PRESERVE_CONTEXT_ON_EXCEPTION = False
    
    # ============================================================================
    # DATABASE CONFIGURATION
    # ============================================================================
    
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'postgresql://ripple_user:ripple_password@localhost:5432/ripple_erp_db'
    )
    
    # Alternative SQLite for development
    # SQLALCHEMY_DATABASE_URI = 'sqlite:///ripple_erp.db'
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_RECORD_QUERIES = False
    SQLALCHEMY_POOL_SIZE = 10
    SQLALCHEMY_POOL_RECYCLE = 3600
    SQLALCHEMY_POOL_PRE_PING = True
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 3600,
        'pool_size': 10,
        'max_overflow': 20,
        'connect_args': {
            'connect_timeout': 10,
        }
    }
    
    # ============================================================================
    # SESSION & COOKIE CONFIGURATION
    # ============================================================================
    
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    SESSION_COOKIE_NAME = 'ripple_session'
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_DOMAIN = None
    SESSION_REFRESH_EACH_REQUEST = True
    
    # ============================================================================
    # FILE UPLOAD CONFIGURATION
    # ============================================================================
    
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB max upload
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    TEMP_UPLOAD_FOLDER = os.path.join(BASE_DIR, 'temp', 'uploads')
    
    ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}
    ALLOWED_DOCUMENT_EXTENSIONS = {'pdf', 'csv', 'xlsx', 'xls', 'doc', 'docx', 'txt'}
    ALLOWED_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_DOCUMENT_EXTENSIONS
    
    # Ensure upload folders exist
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(TEMP_UPLOAD_FOLDER, exist_ok=True)
    
    # ============================================================================
    # EMAIL CONFIGURATION
    # ============================================================================
    
    MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True') == 'True'
    MAIL_USE_SSL = os.getenv('MAIL_USE_SSL', 'False') == 'True'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@ripplerp.com')
    MAIL_SUPPRESS_SEND = os.getenv('MAIL_SUPPRESS_SEND', 'False') == 'True'
    
    # ============================================================================
    # REDIS CONFIGURATION (Caching & Task Queues)
    # ============================================================================
    
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    REDIS_POOL_SIZE = 5
    REDIS_CONNECTION_POOL_KWARGS = {
        'max_connections': 10,
        'retry_on_timeout': True
    }
    
    # Cache Configuration
    CACHE_TYPE = 'redis'
    CACHE_REDIS_URL = REDIS_URL
    CACHE_DEFAULT_TIMEOUT = 300
    CACHE_KEY_PREFIX = 'ripple_'
    
    # ============================================================================
    # AWS S3 CONFIGURATION
    # ============================================================================
    
    AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID', '')
    AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY', '')
    AWS_S3_BUCKET = os.getenv('AWS_S3_BUCKET', 'ripple-erp-bucket')
    AWS_S3_REGION = os.getenv('AWS_S3_REGION', 'us-east-1')
    AWS_S3_ENDPOINT_URL = os.getenv('AWS_S3_ENDPOINT_URL', None)
    AWS_S3_CUSTOM_DOMAIN = os.getenv('AWS_S3_CUSTOM_DOMAIN', None)
    AWS_S3_USE_SSL = os.getenv('AWS_S3_USE_SSL', 'True') == 'True'
    AWS_STORAGE_BUCKET_NAME = AWS_S3_BUCKET
    AWS_S3_SIGNATURE_VERSION = 's3v4'
    AWS_QUERYSTRING_AUTH = False
    
    # ============================================================================
    # JWT & SECURITY CONFIGURATION
    # ============================================================================
    
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', SECRET_KEY)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)
    JWT_ALGORITHM = 'HS256'
    JWT_TOKEN_LOCATION = ['headers', 'cookies']
    JWT_HEADER_NAME = 'Authorization'
    JWT_HEADER_TYPE = 'Bearer'
    
    # ============================================================================
    # PAGINATION CONFIGURATION
    # ============================================================================
    
    ITEMS_PER_PAGE = 20
    MAX_ITEMS_PER_PAGE = 100
    DEFAULT_PAGE_SIZE = 20
    
    # ============================================================================
    # APPLICATION FEATURE FLAGS
    # ============================================================================
    
    FEATURES = {
        'stock_management': True,
        'revenue_tracking': True,
        'debtor_management': True,
        'automated_reminders': True,
        'camera_identification': True,
        'api_access': False,
        'analytics_dashboard': True,
        'invoice_generation': True,
        'bulk_import': True,
        'export_to_csv': True,
        'multi_warehouse': True,
        'barcode_scanning': True,
        'qr_code_generation': True,
        'mobile_app': False,
    }
    
    # ============================================================================
    # PAYMENT METHODS & CATEGORIES
    # ============================================================================
    
    PAYMENT_METHODS = [
        ('cash', 'Cash'),
        ('credit', 'Credit'),
        ('cheque', 'Cheque'),
        ('bank_transfer', 'Bank Transfer'),
        ('mobile_money', 'Mobile Money'),
        ('debit_card', 'Debit Card'),
        ('credit_card', 'Credit Card'),
    ]
    
    PAYMENT_METHOD_CHOICES = {method[0]: method[1] for method in PAYMENT_METHODS}
    
    EXPENSE_CATEGORIES = [
        ('utilities', 'Utilities & Services'),
        ('rent', 'Rent & Property'),
        ('salaries', 'Salaries & Wages'),
        ('marketing', 'Marketing & Advertising'),
        ('supplies', 'Office Supplies'),
        ('maintenance', 'Maintenance & Repairs'),
        ('transport', 'Transport & Delivery'),
        ('insurance', 'Insurance'),
        ('professional_fees', 'Professional Fees'),
        ('training', 'Training & Development'),
        ('travel', 'Travel & Accommodation'),
        ('other', 'Other'),
    ]
    
    EXPENSE_CATEGORY_CHOICES = {cat[0]: cat[1] for cat in EXPENSE_CATEGORIES}
    
    # ============================================================================
    # BUSINESS LOGIC CONFIGURATION
    # ============================================================================
    
    # Stock Management
    REORDER_LEVEL_PERCENTAGE = 0.30  # 30% of max stock triggers warning
    LOW_STOCK_LEVEL_PERCENTAGE = 0.15  # 15% of max stock triggers critical
    CRITICAL_STOCK_ALERT = True
    AUTO_GENERATE_PO = False  # Auto-generate purchase orders when stock is low
    
    # Debtor Management
    DEFAULT_CREDIT_DAYS = 30
    REMINDER_ON_PURCHASE = 0  # Send reminder immediately on credit purchase
    REMINDER_BEFORE_DUE = 3   # Send reminder 3 days before due date
    REMINDER_ON_DUE_DATE = 0  # Send reminder on due date
    OVERDUE_REMINDER_INTERVAL = 7  # Send reminder every 7 days if overdue
    
    # Invoice & Receipt Settings
    INVOICE_PREFIX = 'INV'
    RECEIPT_PREFIX = 'RCP'
    PURCHASE_ORDER_PREFIX = 'PO'
    EXPENSE_PREFIX = 'EXP'
    
    INVOICE_TERMS_DEFAULT = """
    Payment Terms: Net 30 days
    Please make payment to the account details provided.
    Thank you for your business.
    """
    
    # Tax Configuration
    DEFAULT_TAX_RATE = 0.0  # 0% by default (configure per tenant)
    ALLOW_ZERO_TAX_SALES = True
    
    # Discount Configuration
    MAX_DISCOUNT_PERCENTAGE = 50.0
    ALLOW_CUSTOM_DISCOUNTS = True
    
    # ============================================================================
    # LOGGING CONFIGURATION
    # ============================================================================
    
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.path.join(BASE_DIR, 'logs', 'ripple_erp.log')
    LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT = 10
    
    # Create logs directory
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    
    # ============================================================================
    # PAGINATION & FILTERING
    # ============================================================================
    
    SEARCH_PAGINATION_SIZE = 25
    DEFAULT_SORT_ORDER = 'DESC'
    
    # ============================================================================
    # API CONFIGURATION
    # ============================================================================
    
    JSON_SORT_KEYS = False
    JSON_PRETTY_PRINT = True
    JSONIFY_PRETTYPRINT_REGULAR = True
    
    # ============================================================================
    # SECURITY HEADERS
    # ============================================================================
    
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_SSL_REDIRECT = True
    
    # ============================================================================
    # TIMEZONE & LOCALE
    # ============================================================================
    
    TIMEZONE = 'UTC'
    BABEL_DEFAULT_LOCALE = 'en_US'
    BABEL_DEFAULT_TIMEZONE = TIMEZONE
    SUPPORTED_LOCALES = ['en', 'es', 'fr', 'de', 'pt']
    
    # ============================================================================
    # CACHE TIMEOUTS (in seconds)
    # ============================================================================
    
    CACHE_PRODUCT_TIMEOUT = 600  # 10 minutes
    CACHE_DASHBOARD_TIMEOUT = 300  # 5 minutes
    CACHE_REPORT_TIMEOUT = 3600  # 1 hour
    CACHE_USER_PERMISSIONS_TIMEOUT = 1800  # 30 minutes
    
    # ============================================================================
    # BULK OPERATION LIMITS
    # ============================================================================
    
    MAX_BULK_IMPORT_ROWS = 5000
    MAX_BULK_EXPORT_ROWS = 50000
    BULK_OPERATION_BATCH_SIZE = 100
    
    # ============================================================================
    # AUDIT & COMPLIANCE
    # ============================================================================
    
    ENABLE_AUDIT_LOGS = True
    AUDIT_LOG_RETENTION_DAYS = 365
    ENABLE_ACTIVITY_TRACKING = True
    TRACK_USER_ACTIONS = True
    ENCRYPT_SENSITIVE_DATA = True
    
    # ============================================================================
    # SUBSCRIPTION TIERS CONFIGURATION
    # ============================================================================
    
    SUBSCRIPTION_TIERS = {
        'starter': {
            'name': 'Starter',
            'max_users': 2,
            'max_products': 500,
            'max_clients': 100,
            'storage_limit_gb': 5,
            'features': [
                'basic_inventory',
                'manual_sales_entry',
                'basic_reports',
            ],
            'price_monthly': 29.99,
            'price_yearly': 299.99,
        },
        'professional': {
            'name': 'Professional',
            'max_users': 5,
            'max_products': 5000,
            'max_clients': 1000,
            'storage_limit_gb': 50,
            'features': [
                'basic_inventory',
                'advanced_inventory',
                'sales_tracking',
                'debtors_management',
                'barcode_scanning',
                'advanced_reports',
                'api_access',
            ],
            'price_monthly': 99.99,
            'price_yearly': 999.99,
        },
        'enterprise': {
            'name': 'Enterprise',
            'max_users': 100,
            'max_products': 50000,
            'max_clients': 10000,
            'storage_limit_gb': 500,
            'features': [
                'basic_inventory',
                'advanced_inventory',
                'multi_warehouse',
                'sales_tracking',
                'debtors_management',
                'barcode_scanning',
                'camera_identification',
                'advanced_reports',
                'api_access',
                'custom_integrations',
                'dedicated_support',
            ],
            'price_monthly': 499.99,
            'price_yearly': 4999.99,
        },
    }
    
    # ============================================================================
    # MOBILE & EXTERNAL INTEGRATION
    # ============================================================================
    
    MOBILE_APP_API_VERSION = 'v1'
    ENABLE_API_V2 = False
    API_RATE_LIMIT = '100 per hour'
    
    # ============================================================================
    # NOTIFICATION SETTINGS
    # ============================================================================
    
    NOTIFICATION_CHANNELS = {
        'email': os.getenv('NOTIFICATION_EMAIL', 'True') == 'True',
        'sms': os.getenv('NOTIFICATION_SMS', 'False') == 'True',
        'push': os.getenv('NOTIFICATION_PUSH', 'False') == 'True',
        'in_app': True,
    }
    
    # SMS Gateway Configuration (Twilio, AWS SNS, etc.)
    SMS_PROVIDER = os.getenv('SMS_PROVIDER', 'twilio')
    TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', '')
    TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '')
    TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER', '')
    
    # ============================================================================
    # IMAGE PROCESSING (OpenCV)
    # ============================================================================
    
    IMAGE_PROCESSING_ENABLED = True
    OPENCV_TRAINED_MODEL = os.path.join(BASE_DIR, 'models', 'product_detector.pb')
    MAX_IMAGE_DIMENSION = 2048
    IMAGE_COMPRESSION_QUALITY = 85
    GENERATE_THUMBNAILS = True
    THUMBNAIL_SIZE = (300, 300)
    
    # ============================================================================
    # BARCODE & QR CODE
    # ============================================================================
    
    BARCODE_FONT_SIZE = 30
    QR_CODE_BORDER = 4
    BARCODE_FORMAT = 'CODE128'  # CODE128, EAN13, UPC, QR_CODE
    
    # ============================================================================
    # REPORT GENERATION
    # ============================================================================
    
    ENABLE_PDF_REPORTS = True
    ENABLE_EXCEL_EXPORT = True
    PDF_GENERATOR = 'weasyprint'  # weasyprint or reportlab
    
    # ============================================================================
    # DATA RETENTION POLICY
    # ============================================================================
    
    RETAIN_DELETED_RECORDS_DAYS = 30  # Soft delete before permanent removal
    AUTO_ARCHIVE_MONTHS = 12  # Auto-archive old transactions after 12 months
    
    # ============================================================================
    # BACKUP CONFIGURATION
    # ============================================================================
    
    BACKUP_ENABLED = True
    BACKUP_FREQUENCY = 'daily'  # daily, weekly, monthly
    BACKUP_RETENTION_DAYS = 30
    BACKUP_STORAGE = 's3'  # s3 or local
    
    # ============================================================================
    # CELERY TASK QUEUE CONFIGURATION
    # ============================================================================
    
    CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/1')
    CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/2')
    CELERY_TASK_SERIALIZER = 'json'
    CELERY_RESULT_SERIALIZER = 'json'
    CELERY_ACCEPT_CONTENT = ['json']
    CELERY_TIMEZONE = 'UTC'
    CELERY_TASK_TRACK_STARTED = True
    CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes
    CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # 25 minutes
    
    # ============================================================================
    # SCHEDULED TASKS
    # ============================================================================
    
    BEAT_SCHEDULE = {
        'send-payment-reminders': {
            'task': 'app.tasks.debtor_reminders.send_payment_reminders',
            'schedule': timedelta(hours=6),  # Every 6 hours
        },
        'process-stock-alerts': {
            'task': 'app.tasks.inventory.process_stock_alerts',
            'schedule': timedelta(hours=1),  # Every hour
        },
        'calculate-daily-metrics': {
            'task': 'app.tasks.analytics.calculate_daily_metrics',
            'schedule': timedelta(hours=24),  # Daily at midnight
        },
        'cleanup-temp-files': {
            'task': 'app.tasks.maintenance.cleanup_temp_files',
            'schedule': timedelta(days=1),  # Daily
        },
    }


class DevelopmentConfig(BaseConfig):
    """Development environment configuration"""
    DEBUG = True
    TESTING = False
    ENV = 'development'
    
    # Less strict security for development
    SESSION_COOKIE_SECURE = False
    
    # Database echo for debugging
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_RECORD_QUERIES = True
    
    # Disable email in development
    MAIL_SUPPRESS_SEND = True
    
    # Disable SSL redirect in development
    SECURE_SSL_REDIRECT = False


class TestingConfig(BaseConfig):
    """Testing environment configuration"""
    TESTING = True
    ENV = 'testing'
    
    # Use in-memory SQLite for tests
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    
    # Disable CSRF for testing
    WTF_CSRF_ENABLED = False
    
    # Disable secure cookies
    SESSION_COOKIE_SECURE = False
    
    # Disable mail sending
    MAIL_SUPPRESS_SEND = True
    
    # Disable Redis
    CACHE_TYPE = 'simple'
    
    # Fast password hashing for tests
    BCRYPT_LOG_ROUNDS = 4


class StagingConfig(BaseConfig):
    """Staging environment configuration"""
    DEBUG = False
    TESTING = False
    ENV = 'staging'
    
    # Staging-specific optimizations
    SQLALCHEMY_ECHO = False


class ProductionConfig(BaseConfig):
    """Production environment configuration"""
    DEBUG = False
    TESTING = False
    ENV = 'production'
    
    # Enforce security in production
    SESSION_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    
    # Production database with connection pooling
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_RECORD_QUERIES = False
    
    # Production email settings
    MAIL_SUPPRESS_SEND = False


# Configuration dictionary
config_dict = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'staging': StagingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}

# Load appropriate configuration
def get_config():
    """Get configuration based on environment"""
    env = os.getenv('FLASK_ENV', 'development')
    return config_dict.get(env, DevelopmentConfig)

# Set up logging
def setup_logging(app):
    """Configure logging for the application"""
    if not app.debug and not app.testing:
        if not os.path.exists('logs'):
            os.mkdir('logs')
        
        file_handler = RotatingFileHandler(
            app.config['LOG_FILE'],
            maxBytes=app.config['LOG_MAX_BYTES'],
            backupCount=app.config['LOG_BACKUP_COUNT']
        )
        
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        
        app.logger.setLevel(logging.INFO)
        app.logger.info('Ripple ERP Application Startup')

# Get active configuration
CONFIG = get_config()
