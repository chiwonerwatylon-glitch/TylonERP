# app/routes/__init__.py
"""
TylonERP Routes Package
Centralized blueprint registration and route initialization system.

This module handles the registration of all route blueprints (authentication,
products, sales, debtors, clients, and dashboard) with the Flask application.
It provides a clean, modular approach to organizing API endpoints and web routes
across the multi-tenant ERP system.

Features:
- Blueprint registration with URL prefix mapping
- Request context setup for tenant isolation
- Error handler registration
- Cross-Origin Resource Sharing (CORS) configuration
- Rate limiting and request validation
"""

from flask import Blueprint, request, jsonify
from flask_cors import CORS
from functools import wraps
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def init_routes(app):
    """
    Initialize and register all route blueprints with Flask application.
    
    This function centralizes the registration of all route modules, ensuring
    consistent URL prefixing, error handling, and middleware setup across
    the entire application.
    
    Args:
        app (Flask): Flask application instance
        
    Returns:
        None
        
    Raises:
        ImportError: If any route module fails to import
        RuntimeError: If blueprint registration fails
    """
    try:
        # Import all route blueprints
        from app.routes.auth import auth_bp
        from app.routes.product import product_bp
        from app.routes.sale import sale_bp
        from app.routes.debtor import debtor_bp
        from app.routes.client import client_bp
        from app.routes.dashboard import dashboard_bp
        
        # Configure CORS
        CORS(app, resources={
            r"/api/*": {
                "origins": app.config.get('ALLOWED_ORIGINS', ['http://localhost:3000']),
                "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
                "allow_headers": ["Content-Type", "Authorization", "X-Tenant-ID"],
                "expose_headers": ["X-Total-Count", "X-Page-Count"],
                "supports_credentials": True
            }
        })
        
        # Register blueprints with URL prefixes
        blueprints = [
            (auth_bp, '/api/auth', 'Authentication endpoints'),
            (product_bp, '/api/products', 'Product management endpoints'),
            (sale_bp, '/api/sales', 'Sales transaction endpoints'),
            (debtor_bp, '/api/debtors', 'Debtor management endpoints'),
            (client_bp, '/api/clients', 'Client management endpoints'),
            (dashboard_bp, '/api/dashboard', 'Dashboard analytics endpoints'),
        ]
        
        for blueprint, url_prefix, description in blueprints:
            try:
                app.register_blueprint(blueprint, url_prefix=url_prefix)
                logger.info(f"✓ Registered blueprint: {blueprint.name} → {url_prefix} ({description})")
            except Exception as e:
                logger.error(f"✗ Failed to register blueprint {blueprint.name}: {str(e)}")
                raise RuntimeError(f"Blueprint registration failed for {blueprint.name}: {str(e)}")
        
        # Register error handlers
        register_error_handlers(app)
        
        # Register request/response hooks
        register_request_hooks(app)
        
        logger.info("✓ All routes initialized successfully")
        
    except ImportError as e:
        logger.error(f"✗ Route import error: {str(e)}")
        raise ImportError(f"Failed to import route modules: {str(e)}")


def register_error_handlers(app):
    """
    Register global error handlers for consistent error responses.
    
    Args:
        app (Flask): Flask application instance
    """
    
    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({
            'status': 'error',
            'code': 400,
            'message': 'Bad Request',
            'detail': str(error)
        }), 400
    
    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify({
            'status': 'error',
            'code': 401,
            'message': 'Unauthorized',
            'detail': 'Authentication required'
        }), 401
    
    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({
            'status': 'error',
            'code': 403,
            'message': 'Forbidden',
            'detail': 'Insufficient permissions'
        }), 403
    
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({
            'status': 'error',
            'code': 404,
            'message': 'Not Found',
            'detail': 'Resource not found'
        }), 404
    
    @app.errorhandler(409)
    def conflict(error):
        return jsonify({
            'status': 'error',
            'code': 409,
            'message': 'Conflict',
            'detail': str(error)
        }), 409
    
    @app.errorhandler(422)
    def unprocessable_entity(error):
        return jsonify({
            'status': 'error',
            'code': 422,
            'message': 'Unprocessable Entity',
            'detail': str(error)
        }), 422
    
    @app.errorhandler(429)
    def rate_limit_exceeded(error):
        return jsonify({
            'status': 'error',
            'code': 429,
            'message': 'Rate Limit Exceeded',
            'detail': 'Too many requests'
        }), 429
    
    @app.errorhandler(500)
    def internal_server_error(error):
        logger.error(f"Internal server error: {str(error)}")
        return jsonify({
            'status': 'error',
            'code': 500,
            'message': 'Internal Server Error',
            'detail': 'An unexpected error occurred'
        }), 500


def register_request_hooks(app):
    """
    Register before/after request hooks for middleware operations.
    
    Args:
        app (Flask): Flask application instance
    """
    
    @app.before_request
    def before_request():
        """Execute before each request."""
        request.start_time = datetime.utcnow()
        
        # Extract tenant ID from header or session
        tenant_id = request.headers.get('X-Tenant-ID')
        if tenant_id:
            request.tenant_id = tenant_id
    
    @app.after_request
    def after_request(response):
        """Execute after each request."""
        if hasattr(request, 'start_time'):
            elapsed = (datetime.utcnow() - request.start_time).total_seconds()
            response.headers['X-Response-Time'] = f"{elapsed:.3f}s"
        
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        return response


def create_blueprint(name, import_name):
    """
    Factory function for creating route blueprints with consistent configuration.
    
    Args:
        name (str): Blueprint name
        import_name (str): Import name for the blueprint module
        
    Returns:
        Blueprint: Configured Flask Blueprint instance
    """
    bp = Blueprint(
        name,
        import_name,
        template_folder='templates',
        static_folder='static'
    )
    return bp


__all__ = [
    'init_routes',
    'register_error_handlers',
    'register_request_hooks',
    'create_blueprint',
]
