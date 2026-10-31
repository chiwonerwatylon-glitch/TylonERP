# app/routes/sale.py
"""
TylonERP Sales Routes Module
Comprehensive REST API endpoints for sales transaction management.

This module handles all sales-related operations including:
- Sale transaction creation (cash, credit, mixed payment)
- Invoice generation and management
- Sales item management and stock reservation
- Payment tracking and reconciliation
- Sales analytics and reporting
- Return processing and refund management
- Commission calculation for sales staff
- Sales metrics aggregation for dashboards
- Revenue tracking by payment method

Features:
- JWT token validation with role-based access control
- Real-time stock reservation and deduction
- Automatic debtor credit tracking
- Invoice numbering and PDF generation
- Payment method flexibility
- Comprehensive audit logging
- Error handling with rollback support
- Pagination and filtering support
"""

from flask import request, jsonify, current_app, send_file
from flask_sqlalchemy import Pagination
from datetime import datetime, timedelta
from decimal import Decimal
import logging
import uuid
import json
from io import BytesIO
from sqlalchemy import and_, or_, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.routes import create_blueprint
from app.models import db, Sale, SaleItem, Product, Client, SalesMetrics, ActivityLog
from app.auth import token_required, role_required, tenant_required

logger = logging.getLogger(__name__)
sale_bp = create_blueprint('sale', __name__)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def validate_sale_data(data, is_new=True):
    """
    Validate sale request data comprehensively.
    
    Args:
        data (dict): Sale data to validate
        is_new (bool): Whether this is a new sale
        
    Returns:
        tuple: (is_valid, errors)
    """
    errors = []
    
    if is_new:
        required_fields = ['sale_date', 'items', 'payment_method']
        for field in required_fields:
            if field not in data or not data[field]:
                errors.append(f"Missing required field: {field}")
    
    # Validate sale date
    if 'sale_date' in data:
        try:
            datetime.fromisoformat(data['sale_date'].replace('Z', '+00:00'))
        except:
            errors.append("Invalid sale_date format (use ISO 8601)")
    
    # Validate payment method
    if 'payment_method' in data:
        valid_methods = ['cash', 'credit', 'mixed', 'cheque', 'bank_transfer']
        if data['payment_method'] not in valid_methods:
            errors.append(f"Invalid payment_method. Must be one of: {', '.join(valid_methods)}")
    
    # Validate items
    if 'items' in data:
        if not isinstance(data['items'], list) or len(data['items']) == 0:
            errors.append("Items must be a non-empty list")
        else:
            for idx, item in enumerate(data['items']):
                if 'product_id' not in item:
                    errors.append(f"Item {idx}: Missing product_id")
                if 'quantity' not in item or item['quantity'] <= 0:
                    errors.append(f"Item {idx}: Quantity must be positive")
                if 'unit_price' not in item or item['unit_price'] < 0:
                    errors.append(f"Item {idx}: Unit price must be non-negative")
    
    # Validate amounts for mixed payment
    if data.get('payment_method') == 'mixed':
        if 'cash_amount' not in data or 'credit_amount' not in data:
            errors.append("Mixed payment requires both cash_amount and credit_amount")
        else:
            try:
                cash = Decimal(str(data.get('cash_amount', 0)))
                credit = Decimal(str(data.get('credit_amount', 0)))
                if cash < 0 or credit < 0:
                    errors.append("Payment amounts cannot be negative")
            except:
                errors.append("Payment amounts must be valid numbers")
    
    return len(errors) == 0, errors


def generate_invoice_number(tenant_id):
    """
    Generate unique invoice number with sequential numbering.
    
    Args:
        tenant_id (str): Tenant UUID
        
    Returns:
        str: Formatted invoice number
    """
    latest_sale = Sale.query.filter_by(tenant_id=tenant_id).order_by(
        Sale.invoice_number.desc()
    ).first()
    
    sequence = 1
    if latest_sale and latest_sale.invoice_number:
        try:
            # Extract number from invoice format
            parts = latest_sale.invoice_number.split('-')
            if len(parts) > 1:
                sequence = int(parts[-1]) + 1
        except:
            sequence = 1
    
    timestamp = datetime.utcnow().strftime('%Y%m%d')
    return f"INV-{timestamp}-{sequence:06d}"


def calculate_sale_totals(items):
    """
    Calculate subtotal, tax, and total for sale items.
    
    Args:
        items (list): List of sale items with unit_price and quantity
        
    Returns:
        dict: Totals breakdown
    """
    subtotal = Decimal('0')
    tax_amount = Decimal('0')
    
    for item in items:
        item_subtotal = Decimal(str(item.get('unit_price', 0))) * item.get('quantity', 0)
        subtotal += item_subtotal
    
    # Apply tax rate from config
    tax_rate = Decimal(str(current_app.config.get('DEFAULT_TAX_RATE', 0.15)))
    tax_amount = subtotal * tax_rate
    total = subtotal + tax_amount
    
    return {
        'subtotal': float(subtotal),
        'tax_amount': float(tax_amount),
        'total': float(total),
        'tax_rate': float(tax_rate)
    }


def reserve_stock(items, tenant_id):
    """
    Reserve stock for sale items with validation.
    
    Args:
        items (list): Sale items to reserve
        tenant_id (str): Tenant UUID
        
    Returns:
        tuple: (success, result_or_error)
    """
    try:
        for item in items:
            product = Product.query.filter_by(
                id=item['product_id'],
                tenant_id=tenant_id,
                is_deleted=False
            ).with_for_update().first()
            
            if not product:
                return False, f"Product {item['product_id']} not found"
            
            if product.current_stock < item['quantity']:
                return False, f"Insufficient stock for {product.product_name}. Available: {product.current_stock}, Required: {item['quantity']}"
            
            product.current_stock -= item['quantity']
        
        return True, "Stock reserved successfully"
        
    except Exception as e:
        logger.error(f"Stock reservation error: {str(e)}")
        return False, str(e)


def release_stock(items, tenant_id):
    """
    Release reserved stock (for cancellation or return).
    
    Args:
        items (list): Sale items to release
        tenant_id (str): Tenant UUID
        
    Returns:
        tuple: (success, result_or_error)
    """
    try:
        for item in items:
            product = Product.query.filter_by(
                id=item['product_id'],
                tenant_id=tenant_id,
                is_deleted=False
            ).with_for_update().first()
            
            if product:
                quantity = item['quantity'] if isinstance(item, dict) else item.quantity
                product.current_stock += quantity
        
        return True, "Stock released successfully"
        
    except Exception as e:
        logger.error(f"Stock release error: {str(e)}")
        return False, str(e)


# ============================================================================
# SALE ENDPOINTS
# ============================================================================

@sale_bp.route('/', methods=['GET'])
@token_required
@tenant_required
def get_sales():
    """
    Retrieve paginated list of sales with filtering.
    
    Query Parameters:
        - page (int): Page number
        - per_page (int): Items per page
        - status (str): Filter by status (draft, completed, cancelled)
        - payment_method (str): Filter by payment method
        - start_date (str): ISO format start date
        - end_date (str): ISO format end date
        - search (str): Search by invoice number or client name
        - sort_by (str): Sort field (sale_date, total_amount, status)
        - sort_order (str): Sort direction (asc, desc)
    
    Returns:
        JSON: Paginated sales list
    """
    try:
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 20, type=int), 100)
        status = request.args.get('status', '', type=str)
        payment_method = request.args.get('payment_method', '', type=str)
        start_date = request.args.get('start_date', '', type=str)
        end_date = request.args.get('end_date', '', type=str)
        search = request.args.get('search', '', type=str)
        sort_by = request.args.get('sort_by', 'sale_date', type=str)
        sort_order = request.args.get('sort_order', 'desc', type=str)
        
        # Build query
        query = Sale.query.filter_by(tenant_id=request.tenant_id)
        
        # Apply filters
        if status:
            query = query.filter_by(status=status)
        
        if payment_method:
            query = query.filter_by(payment_method=payment_method)
        
        if start_date:
            try:
                start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                query = query.filter(Sale.sale_date >= start)
            except:
                pass
        
        if end_date:
            try:
                end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                query = query.filter(Sale.sale_date <= end)
            except:
                pass
        
        if search:
            query = query.filter(
                or_(
                    Sale.invoice_number.ilike(f"%{search}%"),
                    Sale.client_name.ilike(f"%{search}%")
                )
            )
        
        # Apply sorting
        sort_column = getattr(Sale, sort_by, Sale.sale_date)
        if sort_order.lower() == 'asc':
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())
        
        # Paginate
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        
        sales = [{
            'id': s.id,
            'invoice_number': s.invoice_number,
            'client_id': s.client_id,
            'client_name': s.client_name,
            'sale_date': s.sale_date.isoformat(),
            'status': s.status,
            'payment_method': s.payment_method,
            'subtotal': float(s.subtotal),
            'tax_amount': float(s.tax_amount),
            'total_amount': float(s.total_amount),
            'items_count': len(s.items) if s.items else 0,
            'created_at': s.created_at.isoformat()
        } for s in pagination.items]
        
        return jsonify({
            'status': 'success',
            'data': sales,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': pagination.total,
                'pages': pagination.pages
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving sales: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to retrieve sales',
            'detail': str(e)
        }), 500


@sale_bp.route('/', methods=['POST'])
@token_required
@tenant_required
@role_required(['admin', 'manager', 'sales_staff'])
def create_sale():
    """
    Create new sale transaction with comprehensive validation.
    
    Request Body:
        - sale_date (str): ISO format date
        - client_id (str, optional): Client UUID for credit sales
        - client_name (str): Client name
        - items (list): Array of {product_id, quantity, unit_price}
        - payment_method (str): cash, credit, mixed, cheque, bank_transfer
        - cash_amount (float, optional): Amount paid in cash
        - credit_amount (float, optional): Amount on credit
        - notes (str, optional): Sale notes
        - tax_rate (float, optional): Custom tax rate
    
    Returns:
        JSON: Created sale details with 201 status
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'Request body cannot be empty'
            }), 400
        
        # Validate data
        is_valid, errors = validate_sale_data(data)
        if not is_valid:
            return jsonify({
                'status': 'error',
                'message': 'Validation failed',
                'errors': errors
            }), 422
        
        # Validate client if credit sale
        client = None
        if data['payment_method'] in ['credit', 'mixed'] or data.get('client_id'):
            if not data.get('client_id'):
                return jsonify({
                    'status': 'error',
                    'message': 'Client ID required for credit sales'
                }), 400
            
            client = Client.query.filter_by(
                id=data['client_id'],
                tenant_id=request.tenant_id
            ).first()
            
            if not client:
                return jsonify({
                    'status': 'error',
                    'message': 'Client not found'
                }), 404
        
        # Reserve stock
        success, message = reserve_stock(data['items'], request.tenant_id)
        if not success:
            return jsonify({
                'status': 'error',
                'message': 'Stock reservation failed',
                'detail': message
            }), 400
        
        # Calculate totals
        totals = calculate_sale_totals(data['items'])
        
        # Generate invoice number
        invoice_number = generate_invoice_number(request.tenant_id)
        
        # Determine payment amounts
        total_amount = Decimal(str(totals['total']))
        
        if data['payment_method'] == 'cash':
            cash_amount = total_amount
            credit_amount = Decimal('0')
        elif data['payment_method'] == 'credit':
            cash_amount = Decimal('0')
            credit_amount = total_amount
        elif data['payment_method'] == 'mixed':
            cash_amount = Decimal(str(data.get('cash_amount', 0)))
            credit_amount = Decimal(str(data.get('credit_amount', 0)))
            if cash_amount + credit_amount != total_amount:
                release_stock(data['items'], request.tenant_id)
                return jsonify({
                    'status': 'error',
                    'message': 'Payment amounts do not equal total'
                }), 400
        else:  # cheque, bank_transfer
            cash_amount = Decimal('0')
            credit_amount = Decimal('0')
        
        # Create sale record
        sale = Sale(
            id=str(uuid.uuid4()),
            tenant_id=request.tenant_id,
            invoice_number=invoice_number,
            client_id=client.id if client else None,
            client_name=data.get('client_name', client.client_name if client else 'Walk-in Customer'),
            sale_date=datetime.fromisoformat(data['sale_date'].replace('Z', '+00:00')),
            status='completed',
            payment_method=data['payment_method'],
            subtotal=Decimal(str(totals['subtotal'])),
            tax_amount=Decimal(str(totals['tax_amount'])),
            total_amount=total_amount,
            cash_amount=cash_amount,
            credit_amount=credit_amount,
            notes=data.get('notes', ''),
            created_by=request.user_id
        )
        
        # Create sale items
        for item_data in data['items']:
            product = Product.query.filter_by(id=item_data['product_id']).first()
            
            sale_item = SaleItem(
                id=str(uuid.uuid4()),
                sale_id=sale.id,
                product_id=item_data['product_id'],
                product_name=product.product_name,
                quantity=item_data['quantity'],
                unit_price=Decimal(str(item_data['unit_price'])),
                subtotal=Decimal(str(item_data['unit_price'])) * item_data['quantity']
            )
            sale.items.append(sale_item)
            
            # Create stock movement record
            from app.models import StockMovement
            movement = StockMovement(
                id=str(uuid.uuid4()),
                product_id=item_data['product_id'],
                tenant_id=request.tenant_id,
                movement_type='sale',
                quantity=-item_data['quantity'],
                previous_stock=product.current_stock + item_data['quantity'],
                new_stock=product.current_stock,
                reference_id=invoice_number,
                notes=f"Sale via {invoice_number}",
                created_by=request.user_id
            )
            db.session.add(movement)
        
        db.session.add(sale)
        
        # Update client credit if applicable
        if client and credit_amount > 0:
            client.credit_limit -= credit_amount
            client.credit_used += credit_amount
        
        db.session.commit()
        
        # Log activity
        activity = ActivityLog(
            id=str(uuid.uuid4()),
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            action='CREATE_SALE',
            resource_type='Sale',
            resource_id=sale.id,
            details={
                'invoice_number': invoice_number,
                'total_amount': float(total_amount),
                'payment_method': data['payment_method']
            },
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')
        )
        db.session.add(activity)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Sale created successfully',
            'data': {
                'id': sale.id,
                'invoice_number': invoice_number,
                'total_amount': float(total_amount),
                'status': sale.status,
                'created_at': sale.created_at.isoformat()
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating sale: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to create sale',
            'detail': str(e)
        }), 500


@sale_bp.route('/<sale_id>', methods=['GET'])
@token_required
@tenant_required
def get_sale(sale_id):
    """
    Retrieve detailed sale information with items.
    
    Args:
        sale_id (str): Sale UUID
    
    Returns:
        JSON: Detailed sale information
    """
    try:
        sale = Sale.query.filter_by(
            id=sale_id,
            tenant_id=request.tenant_id
        ).first()
        
        if not sale:
            return jsonify({
                'status': 'error',
                'message': 'Sale not found'
            }), 404
        
        return jsonify({
            'status': 'success',
            'data': {
                'id': sale.id,
                'invoice_number': sale.invoice_number,
                'client_id': sale.client_id,
                'client_name': sale.client_name,
                'sale_date': sale.sale_date.isoformat(),
                'status': sale.status,
                'payment_method': sale.payment_method,
                'subtotal': float(sale.subtotal),
                'tax_amount': float(sale.tax_amount),
                'total_amount': float(sale.total_amount),
                'cash_amount': float(sale.cash_amount),
                'credit_amount': float(sale.credit_amount),
                'notes': sale.notes,
                'items': [{
                    'id': item.id,
                    'product_id': item.product_id,
                    'product_name': item.product_name,
                    'quantity': item.quantity,
                    'unit_price': float(item.unit_price),
                    'subtotal': float(item.subtotal)
                } for item in sale.items],
                'created_by': sale.created_by,
                'created_at': sale.created_at.isoformat()
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving sale: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to retrieve sale',
            'detail': str(e)
        }), 500


@sale_bp.route('/<sale_id>/cancel', methods=['POST'])
@token_required
@tenant_required
@role_required(['admin', 'manager'])
def cancel_sale(sale_id):
    """
    Cancel a sale and release reserved stock.
    
    Args:
        sale_id (str): Sale UUID
    
    Returns:
        JSON: Cancellation confirmation
    """
    try:
        sale = Sale.query.filter_by(
            id=sale_id,
            tenant_id=request.tenant_id
        ).first()
        
        if not sale:
            return jsonify({
                'status': 'error',
                'message': 'Sale not found'
            }), 404
        
        if sale.status == 'cancelled':
            return jsonify({
                'status': 'error',
                'message': 'Sale is already cancelled'
            }), 409
        
        # Release stock
        items = [{'product_id': item.product_id, 'quantity': item.quantity} for item in sale.items]
        success, message = release_stock(items, request.tenant_id)
        
        if not success:
            return jsonify({
                'status': 'error',
                'message': 'Failed to release stock',
                'detail': message
            }), 400
        
        # Update sale status
        sale.status = 'cancelled'
        sale.updated_at = datetime.utcnow()
        
        # Revert client credit
        if sale.client_id:
            client = Client.query.filter_by(id=sale.client_id).first()
            if client and sale.credit_amount > 0:
                client.credit_limit += sale.credit_amount
                client.credit_used -= sale.credit_amount
        
        db.session.commit()
        
        # Log activity
        activity = ActivityLog(
            id=str(uuid.uuid4()),
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            action='CANCEL_SALE',
            resource_type='Sale',
            resource_id=sale.id,
            details={'invoice_number': sale.invoice_number},
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')
        )
        db.session.add(activity)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Sale cancelled successfully'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error cancelling sale: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to cancel sale',
            'detail': str(e)
        }), 500


@sale_bp.route('/analytics/summary', methods=['GET'])
@token_required
@tenant_required
def get_sales_summary():
    """
    Retrieve sales analytics summary.
    
    Query Parameters:
        - days (int): Number of past days to include (default: 30)
        - group_by (str): Grouping (daily, weekly, monthly)
    
    Returns:
        JSON: Sales analytics
    """
    try:
        days = request.args.get('days', 30, type=int)
        group_by = request.args.get('group_by', 'daily', type=str)
        
        start_date = datetime.utcnow() - timedelta(days=days)
        
        query = Sale.query.filter(
            Sale.tenant_id == request.tenant_id,
            Sale.sale_date >= start_date,
            Sale.status == 'completed'
        )
        
        sales = query.all()
        
        total_sales = sum(Decimal(s.total_amount) for s in sales)
        total_items = sum(len(s.items) for s in sales)
        avg_sale_value = total_sales / len(sales) if sales else 0
        
        # Group by payment method
        payment_breakdown = {}
        for sale in sales:
            method = sale.payment_method
            if method not in payment_breakdown:
                payment_breakdown[method] = 0
            payment_breakdown[method] += float(sale.total_amount)
        
        return jsonify({
            'status': 'success',
            'data': {
                'total_sales': float(total_sales),
                'total_transactions': len(sales),
                'total_items_sold': total_items,
                'average_sale_value': float(avg_sale_value),
                'payment_breakdown': payment_breakdown,
                'period': {
                    'start_date': start_date.isoformat(),
                    'end_date': datetime.utcnow().isoformat(),
                    'days': days
                }
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving sales summary: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to retrieve summary',
            'detail': str(e)
        }), 500


__all__ = [
    'sale_bp',
    'validate_sale_data',
    'generate_invoice_number',
    'calculate_sale_totals',
    'reserve_stock'
]
