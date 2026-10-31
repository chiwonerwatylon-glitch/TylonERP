"""
============================================================================
TylonERP - Main Application Module
Version: 1.0.0
Brand: Multi-tenant Stock, Revenue & Debtor Management System
Framework: Flask 2.x with SQLAlchemy ORM

This module serves as the main application entry point for WSGI servers
(Gunicorn, uWSGI) and provides Flask app initialization hooks.

Features:
    - WSGI application instance creation
    - Environment-based configuration loading
    - Database initialization
    - Application context management
    - Shell context processor setup
    - Health check endpoints
    - Metrics and monitoring
    - Static file serving configuration
============================================================================
"""

import os
import sys
import logging
from pathlib import Path

from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from flask_talisman import Talisman
from werkzeug.exceptions import HTTPException

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

# ============================================================================
# 1. ENVIRONMENT SETUP
# ============================================================================

ENV = os.getenv('FLASK_ENV', 'development')
DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
TESTING = os.getenv('TESTING', 'False').lower() == 'true'

# ============================================================================
# 2. LOGGER CONFIGURATION
# ============================================================================

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# ============================================================================
# 3. APPLICATION INITIALIZATION
# ============================================================================

def create_wsgi_app():
    """
    Create and configure the Flask WSGI application.
    
    This function is the main entry point for WSGI servers like Gunicorn.
    It initializes the application with the appropriate configuration based
    on the FLASK_ENV environment variable.
    
    Returns:
        Flask: Configured Flask application instance
        
    Example:
        # In Gunicorn configuration or supervisor
        app = create_wsgi_app()
        
        # Or use with gunicorn directly
        gunicorn -w 4 -b 0.0.0.0:5000 "app:create_wsgi_app()"
    """
    from app import create_app
    
    # Determine environment
    if TESTING:
        config_env = 'testing'
    elif ENV == 'production':
        config_env = 'production'
    else:
        config_env = 'development'
    
    logger.info(f'Creating Flask app in {config_env} environment')
    
    # Create app using factory
    app = create_app(config_name=config_env)
    
    # Additional WSGI configuration
    configure_wsgi(app)
    
    logger.info('Flask app initialized successfully')
    return app


def configure_wsgi(app):
    """
    Configure WSGI-specific settings.
    
    Args:
        app (Flask): Flask application instance
        
    Returns:
        None
    """
    
    # Trust proxy headers for production deployments
    if app.config.get('ENV') == 'production':
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        
        # Enable security headers in production
        Talisman(app, force_https=True, strict_transport_security=True)
    else:
        # Disable HTTPS requirement in development
        Talisman(app, force_https=False)


# ============================================================================
# 4. HEALTH CHECK & MONITORING
# ============================================================================

def setup_health_checks(app):
    """
    Setup health check and monitoring endpoints.
    
    Args:
        app (Flask): Flask application instance
        
    Returns:
        None
    """
    
    @app.route('/health', methods=['GET'])
    def health_check():
        """
        Simple health check endpoint.
        
        Returns:
            {
                "status": "healthy",
                "environment": "production",
                "version": "1.0.0"
            }
        """
        return jsonify({
            'status': 'healthy',
            'environment': app.config.get('ENV'),
            'version': '1.0.0',
            'service': 'TylonERP',
        }), 200
    
    @app.route('/health/deep', methods=['GET'])
    def deep_health_check():
        """
        Deep health check including database connectivity.
        
        Returns:
            {
                "status": "healthy",
                "components": {
                    "database": "ok",
                    "cache": "ok",
                    "filesystem": "ok"
                }
            }
        """
        from app import db
        import tempfile
        
        checks = {
            'database': 'error',
            'cache': 'ok',
            'filesystem': 'error',
        }
        
        # Check database
        try:
            db.session.execute('SELECT 1')
            checks['database'] = 'ok'
        except Exception as e:
            logger.error(f'Database health check failed: {str(e)}')
            checks['database'] = f'error: {str(e)}'
        
        # Check filesystem
        try:
            with tempfile.TemporaryFile() as tmp:
                tmp.write(b'test')
            checks['filesystem'] = 'ok'
        except Exception as e:
            logger.error(f'Filesystem health check failed: {str(e)}')
            checks['filesystem'] = f'error: {str(e)}'
        
        # Determine overall status
        overall_status = 'healthy' if all(
            v == 'ok' for v in checks.values()
        ) else 'degraded'
        
        status_code = 200 if overall_status == 'healthy' else 503
        
        return jsonify({
            'status': overall_status,
            'components': checks,
        }), status_code
    
    @app.route('/metrics', methods=['GET'])
    def metrics():
        """
        Application metrics endpoint.
        
        Returns:
            {
                "requests_total": 1234,
                "requests_per_minute": 45,
                "error_rate": 0.02,
                "avg_response_time_ms": 125
            }
        """
        # This is a placeholder - implement with Prometheus or similar
        return jsonify({
            'requests_total': 0,
            'requests_per_minute': 0,
            'error_rate': 0.0,
            'avg_response_time_ms': 0,
        }), 200


# ============================================================================
# 5. STATIC FILES & ASSET CONFIGURATION
# ============================================================================

def configure_static_files(app):
    """
    Configure static file serving.
    
    Args:
        app (Flask): Flask application instance
        
    Returns:
        None
    """
    
    # Set cache control headers for static assets
    @app.after_request
    def set_cache_headers(response):
        """Set appropriate cache headers for static files."""
        if request.path.startswith('/static/'):
            # Cache static assets for 30 days
            response.cache_control.max_age = 2592000
            response.cache_control.public = True
        else:
            # Don't cache dynamic content
            response.cache_control.no_cache = True
            response.cache_control.no_store = True
            response.cache_control.must_revalidate = True
        
        return response


# ============================================================================
# 6. SHELL CONTEXT PROCESSOR
# ============================================================================

def setup_shell_context(app):
    """
    Setup interactive shell context for Flask CLI.
    
    This allows you to access app, db, and models in `flask shell`.
    
    Args:
        app (Flask): Flask application instance
        
    Returns:
        None
    """
    
    @app.shell_context_processor
    def make_shell_context():
        """Create shell context."""
        from app import db
        from app.models import (
            Tenant, User, Product, Sale, Client,
            StockMovement, DebtReminder, ActivityLog
        )
        
        return {
            'db': db,
            'Tenant': Tenant,
            'User': User,
            'Product': Product,
            'Sale': Sale,
            'Client': Client,
            'StockMovement': StockMovement,
            'DebtReminder': DebtReminder,
            'ActivityLog': ActivityLog,
        }


# ============================================================================
# 7. REQUEST/RESPONSE LOGGING
# ============================================================================

def setup_request_logging(app):
    """
    Setup detailed request/response logging.
    
    Args:
        app (Flask): Flask application instance
        
    Returns:
        None
    """
    
    @app.before_request
    def log_request():
        """Log incoming request details."""
        logger.debug(
            f"Request: {request.method} {request.path} "
            f"from {request.remote_addr} "
            f"- User-Agent: {request.headers.get('User-Agent', 'Unknown')}"
        )
    
    @app.after_request
    def log_response(response):
        """Log response details."""
        if request.path.startswith('/static/'):
            # Skip logging for static files
            return response
        
        logger.debug(
            f"Response: {request.method} {request.path} "
            f"- Status {response.status_code} "
            f"- Content-Type: {response.content_type}"
        )
        
        return response


# ============================================================================
# 8. ERROR HANDLER CUSTOMIZATION
# ============================================================================

def setup_custom_error_handlers(app):
    """
    Setup custom error handlers for better error responses.
    
    Args:
        app (Flask): Flask application instance
        
    Returns:
        None
    """
    
    @app.errorhandler(404)
    def page_not_found(error):
        """Handle 404 errors with custom response."""
        if request.path.startswith('/api/'):
            return jsonify({
                'success': False,
                'error': 'Not Found',
                'message': 'The requested endpoint does not exist',
                'status': 404,
            }), 404
        
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 errors with custom response."""
        from app import db
        db.session.rollback()
        
        logger.error(f'Internal Server Error: {str(error)}', exc_info=True)
        
        if request.path.startswith('/api/'):
            return jsonify({
                'success': False,
                'error': 'Internal Server Error',
                'message': 'An unexpected error occurred',
                'status': 500,
            }), 500
        
        return render_template('errors/500.html'), 500


# ============================================================================
# 9. MAIN WSGI APPLICATION INSTANCE
# ============================================================================

# Create the main WSGI application instance
app = create_wsgi_app()

# Setup additional features
setup_health_checks(app)
configure_static_files(app)
setup_shell_context(app)
setup_request_logging(app)
setup_custom_error_handlers(app)

# ============================================================================
# 10. DEVELOPMENT SERVER ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    """
    Development server entry point.
    
    NOTE: Do NOT use this in production!
    Use Gunicorn, uWSGI, or other WSGI servers instead.
    
    Example:
        python app.py
        python app.py --host 0.0.0.0 --port 8000
    """
    
    import argparse
    
    parser = argparse.ArgumentParser(description='TylonERP Development Server')
    parser.add_argument('--host', default='127.0.0.1', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--reload', action='store_true', help='Enable auto-reload')
    
    args = parser.parse_args()
    
    logger.info(f'Starting TylonERP on {args.host}:{args.port}')
    logger.warning('⚠️  This is the development server. Do NOT use in production!')
    
    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug or DEBUG,
        use_reloader=args.reload,
        use_debugger=DEBUG,
    )


# ============================================================================
# 11. MODULE EXPORTS
# ============================================================================

__all__ = [
    'app',
    'create_wsgi_app',
    'configure_wsgi',
    'setup_health_checks',
    'setup_shell_context',
]
