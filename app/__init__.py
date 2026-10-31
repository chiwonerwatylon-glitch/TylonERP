"""
============================================================================
TylonERP - Application Factory Module
Version: 1.0.0
Brand: Multi-tenant Stock, Revenue & Debtor Management System
Framework: Flask 2.x, SQLAlchemy ORM, PostgreSQL
============================================================================

This module implements the Flask Application Factory pattern, initializing
all extensions, registering blueprints, and configuring the application
for production deployment.

Features:
    - Application factory pattern for multiple environments
    - Extension initialization (SQLAlchemy, JWT, Cache, etc.)
    - Blueprint registration with URL prefixes
    - Error handlers and HTTP status code handlers
    - Request/response middleware
    - Security headers
    - Logging configuration
    - Database migration support
    - API error responses
    - Request context processors
    - CLI commands
    - Tenant isolation middleware
    - Rate limiting
    - CORS support
"""

import os
import json
import logging
import logging.handlers
from datetime import timedelta
from functools import wraps

from flask import Flask, request, jsonify, g, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, create_access_token
from flask_cors import CORS
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_marshmallow import Marshmallow
from flask_migrate import Migrate
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================================================
# 1. EXTENSION INITIALIZATION
# ============================================================================

# Database
db = SQLAlchemy()

# JWT Authentication
jwt = JWTManager()

# API Serialization
ma = Marshmallow()

# Database Migrations
migrate = Migrate()

# Caching
cache = Cache(config={'CACHE_TYPE': 'simple'})

# Rate Limiting
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=os.getenv('REDIS_URL', 'memory://'),
)

# CORS
cors = CORS()

# ============================================================================
# 2. LOGGER CONFIGURATION
# ============================================================================

def setup_logging(app):
    """
    Configure application logging with file and console handlers.
    
    Args:
        app (Flask): Flask application instance
        
    Returns:
        None
    """
    if not app.debug and not app.testing:
        # Create logs directory
        if not os.path.exists('logs'):
            os.mkdir('logs')
        
        # File handler for errors
        file_handler = logging.handlers.RotatingFileHandler(
            'logs/tylonerp_errors.log',
            maxBytes=10485760,  # 10MB
            backupCount=10,
        )
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.ERROR)
        app.logger.addHandler(file_handler)
        
        # File handler for info
        info_handler = logging.handlers.RotatingFileHandler(
            'logs/tylonerp_info.log',
            maxBytes=10485760,  # 10MB
            backupCount=10,
        )
        info_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        info_handler.setLevel(logging.INFO)
        app.logger.addHandler(info_handler)
        
        app.logger.setLevel(logging.INFO)
        app.logger.info('TylonERP startup')


# ============================================================================
# 3. APPLICATION FACTORY
# ============================================================================

def create_app(config_name='development'):
    """
    Application factory function that creates and configures the Flask app.
    
    Args:
        config_name (str): Configuration environment name
            - 'development': Development environment
            - 'testing': Testing environment
            - 'production': Production environment
    
    Returns:
        Flask: Configured Flask application instance
        
    Raises:
        ValueError: If invalid config_name is provided
    """
    
    # Create Flask app
    app = Flask(__name__, instance_relative_config=True)
    
    # ========================================================================
    # 3.1 CONFIGURATION LOADING
    # ========================================================================
    
    try:
        from config import config as config_dict
    except ImportError:
        app.logger.error('config.py not found')
        raise
    
    if config_name not in config_dict:
        raise ValueError(f"Unknown configuration: {config_name}")
    
    app.config.from_object(config_dict[config_name])
    
    # Override with environment variables
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
        'DATABASE_URL',
        app.config.get('SQLALCHEMY_DATABASE_URI')
    )
    app.config['REDIS_URL'] = os.getenv(
        'REDIS_URL',
        app.config.get('REDIS_URL')
    )
    app.config['JWT_SECRET_KEY'] = os.getenv(
        'JWT_SECRET_KEY',
        app.config.get('JWT_SECRET_KEY')
    )
    
    # ========================================================================
    # 3.2 EXTENSION INITIALIZATION
    # ========================================================================
    
    db.init_app(app)
    jwt.init_app(app)
    ma.init_app(app)
    migrate.init_app(app, db)
    cache.init_app(app)
    limiter.init_app(app)
    cors.init_app(app, resources={
        r"/api/*": {
            "origins": app.config.get('CORS_ORIGINS', ['*']),
            "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
            "supports_credentials": True,
        }
    })
    
    # ========================================================================
    # 3.3 APPLICATION CONTEXT
    # ========================================================================
    
    with app.app_context():
        # Create database tables
        db.create_all()
    
    # ========================================================================
    # 3.4 LOGGING SETUP
    # ========================================================================
    
    setup_logging(app)
    
    # ========================================================================
    # 3.5 BLUEPRINT REGISTRATION
    # ========================================================================
    
    register_blueprints(app)
    
    # ========================================================================
    # 3.6 REQUEST/RESPONSE HANDLERS
    # ========================================================================
    
    register_request_handlers(app)
    register_response_handlers(app)
    
    # ========================================================================
    # 3.7 ERROR HANDLERS
    # ========================================================================
    
    register_error_handlers(app)
    
    # ========================================================================
    # 3.8 CONTEXT PROCESSORS
    # ========================================================================
    
    register_context_processors(app)
    
    # ========================================================================
    # 3.9 CLI COMMANDS
    # ========================================================================
    
    register_cli_commands(app)
    
    # ========================================================================
    # 3.10 SECURITY HEADERS
    # ========================================================================
    
    setup_security_headers(app)
    
    return app


# ============================================================================
# 4. BLUEPRINT REGISTRATION
# ============================================================================

def register_blueprints(app):
    """
    Register all application blueprints.
    
    Args:
        app (Flask): Flask application instance
        
    Returns:
        None
    """
    from app.routes import (
        auth_bp,
        dashboard_bp,
        product_bp,
        sale_bp,
        debtor_bp,
        client_bp,
        expense_bp,
        report_bp,
        settings_bp,
    )
    
    # API Routes
    app.register_blueprint(auth_bp, url_prefix='/api/v1/auth')
    app.register_blueprint(dashboard_bp, url_prefix='/api/v1/dashboard')
    app.register_blueprint(product_bp, url_prefix='/api/v1/products')
    app.register_blueprint(sale_bp, url_prefix='/api/v1/sales')
    app.register_blueprint(debtor_bp, url_prefix='/api/v1/debtors')
    app.register_blueprint(client_bp, url_prefix='/api/v1/clients')
    app.register_blueprint(expense_bp, url_prefix='/api/v1/expenses')
    app.register_blueprint(report_bp, url_prefix='/api/v1/reports')
    app.register_blueprint(settings_bp, url_prefix='/api/v1/settings')
    
    app.logger.info('All blueprints registered successfully')


# ============================================================================
# 5. REQUEST/RESPONSE HANDLERS
# ============================================================================

def register_request_handlers(app):
    """
    Register request middleware handlers.
    
    Args:
        app (Flask): Flask application instance
        
    Returns:
        None
    """
    
    @app.before_request
    def before_request():
        """
        Execute before each request.
        - Store request start time
        - Extract and validate tenant information
        - Log request details
        """
        from datetime import datetime
        
        # Store request start time for timing
        g.request_start_time = datetime.utcnow()
        
        # Extract tenant from request
        g.tenant_id = request.headers.get('X-Tenant-ID') or \
                      request.args.get('tenant_id')
        
        # Log request
        app.logger.debug(
            f"REQUEST: {request.method} {request.path} "
            f"from {get_remote_address()} "
            f"[Tenant: {g.tenant_id}]"
        )
        
        # Store request context
        g.request_method = request.method
        g.request_path = request.path
        g.request_remote_addr = get_remote_address()


def register_response_handlers(app):
    """
    Register response middleware handlers.
    
    Args:
        app (Flask): Flask application instance
        
    Returns:
        None
    """
    
    @app.after_request
    def after_request(response):
        """
        Execute after each request.
        - Add security headers
        - Add request timing header
        - Log response details
        """
        from datetime import datetime
        
        # Calculate request duration
        if hasattr(g, 'request_start_time'):
            duration = (datetime.utcnow() - g.request_start_time).total_seconds()
            response.headers['X-Request-Duration'] = f"{duration:.3f}s"
        
        # Log response
        app.logger.debug(
            f"RESPONSE: {request.method} {request.path} "
            f"Status {response.status_code}"
        )
        
        return response


# ============================================================================
# 6. ERROR HANDLERS
# ============================================================================

def register_error_handlers(app):
    """
    Register HTTP error and exception handlers.
    
    Args:
        app (Flask): Flask application instance
        
    Returns:
        None
    """
    
    @app.errorhandler(400)
    def bad_request(error):
        """Handle 400 Bad Request errors."""
        return jsonify({
            'success': False,
            'error': 'Bad Request',
            'message': str(error),
            'status': 400,
        }), 400
    
    @app.errorhandler(401)
    def unauthorized(error):
        """Handle 401 Unauthorized errors."""
        return jsonify({
            'success': False,
            'error': 'Unauthorized',
            'message': 'Authentication required',
            'status': 401,
        }), 401
    
    @app.errorhandler(403)
    def forbidden(error):
        """Handle 403 Forbidden errors."""
        return jsonify({
            'success': False,
            'error': 'Forbidden',
            'message': 'You do not have permission to access this resource',
            'status': 403,
        }), 403
    
    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 Not Found errors."""
        return jsonify({
            'success': False,
            'error': 'Not Found',
            'message': 'The requested resource was not found',
            'status': 404,
        }), 404
    
    @app.errorhandler(422)
    def unprocessable_entity(error):
        """Handle 422 Unprocessable Entity errors."""
        return jsonify({
            'success': False,
            'error': 'Unprocessable Entity',
            'message': 'Invalid request data',
            'status': 422,
        }), 422
    
    @app.errorhandler(429)
    def rate_limit_exceeded(error):
        """Handle 429 Rate Limit errors."""
        return jsonify({
            'success': False,
            'error': 'Rate Limit Exceeded',
            'message': 'Too many requests. Please try again later.',
            'status': 429,
        }), 429
    
    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 Internal Server errors."""
        db.session.rollback()
        app.logger.error(f'Internal Server Error: {str(error)}')
        return jsonify({
            'success': False,
            'error': 'Internal Server Error',
            'message': 'An unexpected error occurred',
            'status': 500,
        }), 500
    
    @app.errorhandler(Exception)
    def handle_exception(error):
        """Handle all unhandled exceptions."""
        db.session.rollback()
        
        # Log exception
        app.logger.error(f'Unhandled Exception: {str(error)}', exc_info=True)
        
        # Return error response
        return jsonify({
            'success': False,
            'error': 'Server Error',
            'message': 'An unexpected error occurred',
            'status': 500,
        }), 500


# ============================================================================
# 7. CONTEXT PROCESSORS
# ============================================================================

def register_context_processors(app):
    """
    Register Jinja2 context processors for template rendering.
    
    Args:
        app (Flask): Flask application instance
        
    Returns:
        None
    """
    
    @app.context_processor
    def inject_config():
        """Inject configuration into template context."""
        return {
            'app_name': 'TylonERP',
            'app_version': '1.0.0',
            'environment': app.config.get('ENV', 'development'),
            'debug': app.debug,
        }
    
    @app.context_processor
    def inject_user():
        """Inject current user into template context."""
        from flask_jwt_extended import get_jwt_identity
        try:
            user_id = get_jwt_identity()
            return {'current_user_id': user_id}
        except:
            return {'current_user_id': None}


# ============================================================================
# 8. SECURITY HEADERS
# ============================================================================

def setup_security_headers(app):
    """
    Setup security headers for all responses.
    
    Args:
        app (Flask): Flask application instance
        
    Returns:
        None
    """
    
    @app.after_request
    def add_security_headers(response):
        """Add security headers to response."""
        
        # Content Security Policy
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "cdn.jsdelivr.net cdnjs.cloudflare.com charts.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net cdnjs.cloudflare.com; "
            "img-src 'self' data: https:; "
            "font-src 'self' cdn.jsdelivr.net cdnjs.cloudflare.com; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        
        # Prevent clickjacking
        response.headers['X-Frame-Options'] = 'DENY'
        
        # Prevent MIME type sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        
        # Enable XSS protection
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        # Referrer Policy
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Feature Policy
        response.headers['Permissions-Policy'] = (
            'geolocation=(), '
            'microphone=(), '
            'camera=(), '
            'payment=(), '
            'usb=(), '
            'magnetometer=(), '
            'gyroscope=(), '
            'accelerometer=()'
        )
        
        # HTTP Strict Transport Security
        if app.config.get('ENV') == 'production':
            response.headers['Strict-Transport-Security'] = (
                'max-age=31536000; includeSubDomains; preload'
            )
        
        return response


# ============================================================================
# 9. CLI COMMANDS
# ============================================================================

def register_cli_commands(app):
    """
    Register Flask CLI commands.
    
    Args:
        app (Flask): Flask application instance
        
    Returns:
        None
    """
    
    @app.cli.command()
    def init_db():
        """Initialize the database."""
        db.create_all()
        print('Database initialized.')
    
    @app.cli.command()
    def drop_db():
        """Drop all database tables."""
        if app.config.get('ENV') == 'production':
            print('Cannot drop database in production environment!')
            return
        db.drop_all()
        print('Database dropped.')
    
    @app.cli.command()
    def seed_db():
        """Seed the database with initial data."""
        from app.models import Tenant, User
        
        # Create default tenant
        tenant = Tenant(
            name='Default Tenant',
            slug='default',
            plan='enterprise',
        )
        db.session.add(tenant)
        db.session.commit()
        print(f'Created tenant: {tenant.name}')
        
        # Create admin user
        user = User(
            email='admin@tylonerp.local',
            first_name='Admin',
            last_name='User',
            role='admin',
            tenant_id=tenant.id,
        )
        user.set_password('admin123')
        db.session.add(user)
        db.session.commit()
        print(f'Created user: {user.email}')
    
    @app.cli.command()
    def create_admin():
        """Create an admin user."""
        import getpass
        from app.models import Tenant, User
        
        email = input('Email: ').strip()
        password = getpass.getpass('Password: ')
        
        if not email or not password:
            print('Email and password are required.')
            return
        
        # Get or create default tenant
        tenant = Tenant.query.filter_by(slug='default').first()
        if not tenant:
            tenant = Tenant(name='Default Tenant', slug='default')
            db.session.add(tenant)
            db.session.commit()
        
        # Check if user exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            print(f'User {email} already exists.')
            return
        
        # Create admin user
        user = User(
            email=email,
            first_name='Admin',
            last_name='User',
            role='admin',
            tenant_id=tenant.id,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print(f'Admin user created: {email}')
    
    @app.cli.command()
    def test():
        """Run unit tests."""
        import unittest
        tests = unittest.TestLoader().discover('tests')
        unittest.TextTestRunner(verbosity=2).run(tests)
    
    @app.cli.command()
    def lint():
        """Run code linting."""
        import subprocess
        subprocess.run(['flake8', 'app/', 'tests/'])
    
    @app.cli.command()
    def format_code():
        """Format code with black."""
        import subprocess
        subprocess.run(['black', 'app/', 'tests/', 'config.py'])
    
    @app.cli.command()
    def celery_worker():
        """Start Celery worker."""
        from celery import Celery
        from celery.bin import worker
        
        celery_app = Celery(__name__)
        celery_app.config_from_object('celeryconfig')
        
        w = worker.worker(app=celery_app)
        w.run()
    
    @app.cli.command()
    def celery_beat():
        """Start Celery beat scheduler."""
        from celery import Celery
        from celery.bin import beat
        
        celery_app = Celery(__name__)
        celery_app.config_from_object('celeryconfig')
        
        b = beat.beat(app=celery_app)
        b.run()


# ============================================================================
# 10. CUSTOM JWT HANDLERS
# ============================================================================

def setup_jwt_handlers(app):
    """
    Setup custom JWT handlers.
    
    Args:
        app (Flask): Flask application instance
        
    Returns:
        None
    """
    
    @jwt.additional_claims_loader
    def add_claims_to_access_token(identity):
        """Add custom claims to JWT token."""
        from app.models import User
        
        user = User.query.get(identity)
        if user:
            return {
                'email': user.email,
                'role': user.role,
                'tenant_id': str(user.tenant_id),
            }
        return {}
    
    @jwt.user_lookup_loader
    def user_lookup_callback(jwt_data):
        """Lookup user from JWT data."""
        from app.models import User
        identity = jwt_data['sub']
        return User.query.get(identity)
    
    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_data):
        """Check if token is in blocklist."""
        from app.models import TokenBlacklist
        jti = jwt_data['jti']
        return TokenBlacklist.query.filter_by(jti=jti).first() is not None


# ============================================================================
# 11. DECORATORS
# ============================================================================

def require_tenant(f):
    """
    Decorator to require valid tenant ID in request.
    
    Args:
        f: Flask route function
        
    Returns:
        function: Decorated function
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.get('tenant_id'):
            return jsonify({
                'success': False,
                'error': 'Missing Tenant ID',
                'message': 'X-Tenant-ID header is required',
            }), 400
        return f(*args, **kwargs)
    return decorated_function


def require_role(*roles):
    """
    Decorator to require specific user role.
    
    Args:
        *roles: Required roles
        
    Returns:
        function: Decorator function
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from flask_jwt_extended import get_jwt
            
            claims = get_jwt()
            user_role = claims.get('role')
            
            if user_role not in roles:
                return jsonify({
                    'success': False,
                    'error': 'Forbidden',
                    'message': 'Insufficient permissions',
                }), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ============================================================================
# 12. UTILITY FUNCTIONS
# ============================================================================

def api_response(success=True, data=None, message='', status=200):
    """
    Create standardized API response.
    
    Args:
        success (bool): Success flag
        data (dict): Response data
        message (str): Response message
        status (int): HTTP status code
        
    Returns:
        tuple: (response dict, status code)
    """
    response = {
        'success': success,
        'data': data,
        'message': message,
        'status': status,
    }
    return jsonify(response), status


def paginate_query(query, page=1, per_page=20):
    """
    Paginate query results.
    
    Args:
        query: SQLAlchemy query object
        page (int): Page number
        per_page (int): Results per page
        
    Returns:
        dict: Paginated results
    """
    paginated = query.paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    
    return {
        'items': paginated.items,
        'total': paginated.total,
        'pages': paginated.pages,
        'current_page': page,
        'per_page': per_page,
        'has_prev': paginated.has_prev,
        'has_next': paginated.has_next,
    }


def get_pagination_params():
    """
    Extract pagination parameters from request.
    
    Returns:
        tuple: (page, per_page)
    """
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        
        # Validate
        page = max(1, page)
        per_page = min(100, max(1, per_page))
        
        return page, per_page
    except (ValueError, TypeError):
        return 1, 20


# ============================================================================
# 13. INIT BLUEPRINTS (Placeholder Imports)
# ============================================================================

# These are imported in register_blueprints()
# Ensure these modules exist:
# - app/routes/auth.py
# - app/routes/dashboard.py
# - app/routes/products.py
# - app/routes/sales.py
# - app/routes/debtors.py
# - app/routes/clients.py
# - app/routes/expenses.py
# - app/routes/reports.py
# - app/routes/settings.py

# ============================================================================
# 14. MODULE EXPORTS
# ============================================================================

__all__ = [
    'create_app',
    'db',
    'jwt',
    'ma',
    'migrate',
    'cache',
    'limiter',
    'cors',
    'api_response',
    'paginate_query',
    'get_pagination_params',
    'require_tenant',
    'require_role',
    'setup_jwt_handlers',
]
