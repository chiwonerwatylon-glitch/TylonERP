# app/models/__init__.py
"""
TylonERP Models Package
Centralized import point for all database models and ORM classes.

This module provides organized access to all SQLAlchemy models used throughout
the TylonERP system, including Tenant, User, Product, StockMovement, Client,
Sale, SaleItem, DebtReminder, and ActivityLog.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow

# Initialize SQLAlchemy ORM and Marshmallow serializer
db = SQLAlchemy()
ma = Marshmallow()


def init_models(app):
    """
    Initialize database models with Flask application.
    
    Args:
        app (Flask): Flask application instance
        
    Returns:
        None
    """
    db.init_app(app)
    ma.init_app(app)
    
    # Import all models to register them with SQLAlchemy
    from app.models.tenant import Tenant, User, ActivityLog
    from app.models.product import Product, StockMovement
    from app.models.client import Client, DebtReminder, CreditRiskScore
    from app.models.sale import Sale, SaleItem, SalesMetrics
    
    return db, ma


# Import and expose all models for easy access
from app.models.tenant import Tenant, User, ActivityLog
from app.models.product import Product, StockMovement
from app.models.client import Client, DebtReminder, CreditRiskScore
from app.models.sale import Sale, SaleItem, SalesMetrics

__all__ = [
    # Core ORM
    'db',
    'ma',
    'init_models',
    
    # Tenant Models
    'Tenant',
    'User',
    'ActivityLog',
    
    # Product Models
    'Product',
    'StockMovement',
    
    # Client Models
    'Client',
    'DebtReminder',
    'CreditRiskScore',
    
    # Sales Models
    'Sale',
    'SaleItem',
    'SalesMetrics',
]
