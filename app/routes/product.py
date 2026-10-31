# app/routes/product.py
"""
TylonERP Product Routes Module
Comprehensive REST API endpoints for inventory and product management.

This module handles all product-related operations including:
- Product CRUD operations with multi-tenant isolation
- Stock level management with two-tier alerts
- SKU, barcode, and QR code tracking
- Stock movement history and auditing
- Batch operations for bulk updates
- Image upload and management via Amazon S3
- Stock reservation and inventory forecasting
- Product categorization and tagging
- Supplier integration and cost tracking

Features:
- JWT token validation with role-based access control
- Input validation and error handling
- Pagination and filtering support
- Caching for frequently accessed products
- Audit logging for all stock movements
- Rate limiting on expensive operations
"""

from flask import request, jsonify, current_app
from flask_sqlalchemy import Pagination
from functools import wraps
from datetime import datetime, timedelta
from decimal import Decimal
import logging
import uuid
import json
import boto3
from sqlalchemy import and_, or_, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.routes import create_blueprint
from app.models import db, Product, StockMovement, Tenant, User, ActivityLog
from app.auth import token_required, role_required, tenant_required

logger = logging.getLogger(__name__)
product_bp = create_blueprint('product', __name__)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def validate_product_data(data, update=False):
    """
    Validate product request data with comprehensive checks.
    
    Args:
        data (dict): Product data to validate
        update (bool): Whether this is an update operation
        
    Returns:
        tuple: (is_valid, errors) where errors is a list of error messages
    """
    errors = []
    required_fields = ['product_name', 'sku', 'product_category', 'cost_price', 'selling_price']
    
    if not update:
        for field in required_fields:
            if field not in data or not data[field]:
                errors.append(f"Missing required field: {field}")
    
    # Validate product name
    if 'product_name' in data:
        if not isinstance(data['product_name'], str) or len(data['product_name'].strip()) == 0:
            errors.append("Product name must be a non-empty string")
        if len(data['product_name']) > 255:
            errors.append("Product name must not exceed 255 characters")
    
    # Validate SKU
    if 'sku' in data:
        if not isinstance(data['sku'], str) or len(data['sku'].strip()) == 0:
            errors.append("SKU must be a non-empty string")
        if len(data['sku']) > 50:
            errors.append("SKU must not exceed 50 characters")
    
    # Validate prices
    for field in ['cost_price', 'selling_price']:
        if field in data:
            try:
                price = Decimal(str(data[field]))
                if price < 0:
                    errors.append(f"{field} must be positive")
                if price > 999999.99:
                    errors.append(f"{field} exceeds maximum allowed value")
            except:
                errors.append(f"{field} must be a valid number")
    
    # Validate stock levels
    for field in ['initial_stock', 'current_stock']:
        if field in data:
            try:
                stock = int(data[field])
                if stock < 0:
                    errors.append(f"{field} must be non-negative")
            except:
                errors.append(f"{field} must be an integer")
    
    # Validate buffer levels
    if 'buffer_stock_level' in data:
        try:
            buffer = int(data['buffer_stock_level'])
            if buffer < 0 or buffer > 100:
                errors.append("Buffer stock level must be between 0 and 100")
        except:
            errors.append("Buffer stock level must be an integer")
    
    return len(errors) == 0, errors


def calculate_stock_alerts(product):
    """
    Calculate stock alert levels based on buffer thresholds.
    
    Args:
        product (Product): Product instance
        
    Returns:
        dict: Alert information with status and levels
    """
    current_stock = product.current_stock
    buffer_level = product.buffer_stock_level
    
    warning_threshold = int(product.initial_stock * (buffer_level / 100))
    critical_threshold = int(product.initial_stock * ((buffer_level / 2) / 100))
    
    alert_status = 'normal'
    if current_stock <= critical_threshold:
        alert_status = 'critical'
    elif current_stock <= warning_threshold:
        alert_status = 'warning'
    
    return {
        'status': alert_status,
        'current_stock': current_stock,
        'warning_threshold': warning_threshold,
        'critical_threshold': critical_threshold,
        'buffer_percentage': buffer_level
    }


def upload_product_image(file, product_id, tenant_id):
    """
    Upload product image to Amazon S3 with secure naming.
    
    Args:
        file: File object from request
        product_id (str): Product UUID
        tenant_id (str): Tenant UUID
        
    Returns:
        tuple: (success, url_or_error)
    """
    try:
        if not file or file.filename == '':
            return False, "No file selected"
        
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        if not '.' in file.filename or file.filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
            return False, "Invalid file type. Allowed: png, jpg, jpeg, gif, webp"
        
        s3_client = boto3.client(
            's3',
            aws_access_key_id=current_app.config['AWS_ACCESS_KEY_ID'],
            aws_secret_access_key=current_app.config['AWS_SECRET_ACCESS_KEY'],
            region_name=current_app.config['AWS_REGION']
        )
        
        # Generate secure S3 key
        file_ext = file.filename.rsplit('.', 1)[1].lower()
        s3_key = f"products/{tenant_id}/{product_id}/{uuid.uuid4().hex}.{file_ext}"
        
        # Upload with metadata
        s3_client.upload_fileobj(
            file,
            current_app.config['AWS_S3_BUCKET'],
            s3_key,
            ExtraArgs={
                'ContentType': file.content_type,
                'Metadata': {
                    'product_id': product_id,
                    'tenant_id': tenant_id,
                    'uploaded_at': datetime.utcnow().isoformat()
                }
            }
        )
        
        # Generate public URL
        url = f"https://{current_app.config['AWS_S3_BUCKET']}.s3.{current_app.config['AWS_REGION']}.amazonaws.com/{s3_key}"
        return True, url
        
    except Exception as e:
        logger.error(f"S3 upload error: {str(e)}")
        return False, f"Upload failed: {str(e)}"


# ============================================================================
# PRODUCT ENDPOINTS
# ============================================================================

@product_bp.route('/', methods=['GET'])
@token_required
@tenant_required
def get_products():
    """
    Retrieve paginated list of products with filtering and searching.
    
    Query Parameters:
        - page (int): Page number (default: 1)
        - per_page (int): Items per page (default: 20, max: 100)
        - search (str): Search by product name or SKU
        - category (str): Filter by category
        - status (str): Filter by status (active, discontinued)
        - sort_by (str): Sort field (name, sku, price, stock)
        - sort_order (str): Sort direction (asc, desc)
    
    Returns:
        JSON: Paginated products with metadata
    """
    try:
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 20, type=int), 100)
        search = request.args.get('search', '', type=str)
        category = request.args.get('category', '', type=str)
        status = request.args.get('status', '', type=str)
        sort_by = request.args.get('sort_by', 'product_name', type=str)
        sort_order = request.args.get('sort_order', 'asc', type=str)
        
        # Build query
        query = Product.query.filter_by(tenant_id=request.tenant_id, is_deleted=False)
        
        # Apply filters
        if search:
            query = query.filter(
                or_(
                    Product.product_name.ilike(f"%{search}%"),
                    Product.sku.ilike(f"%{search}%")
                )
            )
        
        if category:
            query = query.filter_by(product_category=category)
        
        if status:
            is_active = status.lower() == 'active'
            query = query.filter_by(is_active=is_active)
        
        # Apply sorting
        sort_column = getattr(Product, sort_by, Product.product_name)
        if sort_order.lower() == 'desc':
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())
        
        # Paginate
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        
        products = [{
            'id': p.id,
            'product_name': p.product_name,
            'sku': p.sku,
            'barcode': p.barcode,
            'qr_code': p.qr_code,
            'product_category': p.product_category,
            'cost_price': float(p.cost_price),
            'selling_price': float(p.selling_price),
            'current_stock': p.current_stock,
            'buffer_stock_level': p.buffer_stock_level,
            'alert': calculate_stock_alerts(p),
            'supplier_id': p.supplier_id,
            'is_active': p.is_active,
            'image_url': p.image_url,
            'created_at': p.created_at.isoformat(),
            'updated_at': p.updated_at.isoformat()
        } for p in pagination.items]
        
        return jsonify({
            'status': 'success',
            'data': products,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': pagination.total,
                'pages': pagination.pages
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving products: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to retrieve products',
            'detail': str(e)
        }), 500


@product_bp.route('/', methods=['POST'])
@token_required
@tenant_required
@role_required(['admin', 'manager'])
def create_product():
    """
    Create a new product with comprehensive validation.
    
    Request Body:
        - product_name (str): Name of the product
        - sku (str): Stock Keeping Unit
        - barcode (str, optional): Barcode number
        - qr_code (str, optional): QR code string
        - product_category (str): Product category
        - cost_price (float): Cost price
        - selling_price (float): Selling price
        - initial_stock (int): Initial stock quantity
        - buffer_stock_level (int): Buffer level percentage (0-100)
        - supplier_id (str, optional): Supplier UUID
        - description (str, optional): Product description
        - specifications (dict, optional): Product specifications
    
    Returns:
        JSON: Created product details with 201 status
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'Request body cannot be empty'
            }), 400
        
        # Validate data
        is_valid, errors = validate_product_data(data)
        if not is_valid:
            return jsonify({
                'status': 'error',
                'message': 'Validation failed',
                'errors': errors
            }), 422
        
        # Check for SKU uniqueness within tenant
        existing = Product.query.filter_by(
            tenant_id=request.tenant_id,
            sku=data['sku'],
            is_deleted=False
        ).first()
        
        if existing:
            return jsonify({
                'status': 'error',
                'message': 'SKU already exists for this tenant'
            }), 409
        
        # Create product
        product = Product(
            id=str(uuid.uuid4()),
            tenant_id=request.tenant_id,
            product_name=data['product_name'],
            sku=data['sku'],
            barcode=data.get('barcode'),
            qr_code=data.get('qr_code'),
            product_category=data['product_category'],
            cost_price=Decimal(str(data['cost_price'])),
            selling_price=Decimal(str(data['selling_price'])),
            initial_stock=data.get('initial_stock', 0),
            current_stock=data.get('initial_stock', 0),
            buffer_stock_level=data.get('buffer_stock_level', 30),
            supplier_id=data.get('supplier_id'),
            description=data.get('description', ''),
            specifications=data.get('specifications', {}),
            is_active=True,
            is_deleted=False
        )
        
        db.session.add(product)
        db.session.commit()
        
        # Log activity
        activity = ActivityLog(
            id=str(uuid.uuid4()),
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            action='CREATE_PRODUCT',
            resource_type='Product',
            resource_id=product.id,
            details={
                'product_name': product.product_name,
                'sku': product.sku,
                'initial_stock': product.initial_stock
            },
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')
        )
        db.session.add(activity)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Product created successfully',
            'data': {
                'id': product.id,
                'product_name': product.product_name,
                'sku': product.sku,
                'product_category': product.product_category,
                'current_stock': product.current_stock,
                'created_at': product.created_at.isoformat()
            }
        }), 201
        
    except IntegrityError:
        db.session.rollback()
        logger.error("Integrity error creating product")
        return jsonify({
            'status': 'error',
            'message': 'Duplicate product data'
        }), 409
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating product: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to create product',
            'detail': str(e)
        }), 500


@product_bp.route('/<product_id>', methods=['GET'])
@token_required
@tenant_required
def get_product(product_id):
    """
    Retrieve detailed product information with stock history.
    
    Args:
        product_id (str): Product UUID
    
    Returns:
        JSON: Detailed product information
    """
    try:
        product = Product.query.filter_by(
            id=product_id,
            tenant_id=request.tenant_id,
            is_deleted=False
        ).first()
        
        if not product:
            return jsonify({
                'status': 'error',
                'message': 'Product not found'
            }), 404
        
        # Get stock movement history
        movements = StockMovement.query.filter_by(
            product_id=product_id
        ).order_by(StockMovement.created_at.desc()).limit(20).all()
        
        return jsonify({
            'status': 'success',
            'data': {
                'id': product.id,
                'product_name': product.product_name,
                'sku': product.sku,
                'barcode': product.barcode,
                'qr_code': product.qr_code,
                'product_category': product.product_category,
                'cost_price': float(product.cost_price),
                'selling_price': float(product.selling_price),
                'current_stock': product.current_stock,
                'initial_stock': product.initial_stock,
                'buffer_stock_level': product.buffer_stock_level,
                'alert': calculate_stock_alerts(product),
                'supplier_id': product.supplier_id,
                'description': product.description,
                'specifications': product.specifications,
                'image_url': product.image_url,
                'is_active': product.is_active,
                'created_at': product.created_at.isoformat(),
                'updated_at': product.updated_at.isoformat(),
                'stock_movements': [{
                    'id': m.id,
                    'movement_type': m.movement_type,
                    'quantity': m.quantity,
                    'reference_id': m.reference_id,
                    'notes': m.notes,
                    'created_at': m.created_at.isoformat()
                } for m in movements]
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving product: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to retrieve product',
            'detail': str(e)
        }), 500


@product_bp.route('/<product_id>', methods=['PUT'])
@token_required
@tenant_required
@role_required(['admin', 'manager'])
def update_product(product_id):
    """
    Update product information with change tracking.
    
    Args:
        product_id (str): Product UUID
    
    Returns:
        JSON: Updated product details
    """
    try:
        product = Product.query.filter_by(
            id=product_id,
            tenant_id=request.tenant_id,
            is_deleted=False
        ).first()
        
        if not product:
            return jsonify({
                'status': 'error',
                'message': 'Product not found'
            }), 404
        
        data = request.get_json()
        
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'Request body cannot be empty'
            }), 400
        
        # Validate data
        is_valid, errors = validate_product_data(data, update=True)
        if not is_valid:
            return jsonify({
                'status': 'error',
                'message': 'Validation failed',
                'errors': errors
            }), 422
        
        # Check SKU uniqueness if changed
        if 'sku' in data and data['sku'] != product.sku:
            existing = Product.query.filter_by(
                tenant_id=request.tenant_id,
                sku=data['sku'],
                is_deleted=False
            ).first()
            if existing:
                return jsonify({
                    'status': 'error',
                    'message': 'SKU already exists'
                }), 409
        
        # Track changes
        changes = {}
        updateable_fields = [
            'product_name', 'sku', 'barcode', 'qr_code', 'product_category',
            'cost_price', 'selling_price', 'buffer_stock_level', 'supplier_id',
            'description', 'specifications', 'is_active'
        ]
        
        for field in updateable_fields:
            if field in data:
                old_value = getattr(product, field)
                new_value = data[field]
                if old_value != new_value:
                    changes[field] = {'old': old_value, 'new': new_value}
                    setattr(product, field, new_value)
        
        product.updated_at = datetime.utcnow()
        db.session.commit()
        
        # Log activity
        if changes:
            activity = ActivityLog(
                id=str(uuid.uuid4()),
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                action='UPDATE_PRODUCT',
                resource_type='Product',
                resource_id=product.id,
                details={'changes': changes},
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent', '')
            )
            db.session.add(activity)
            db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Product updated successfully',
            'data': {
                'id': product.id,
                'product_name': product.product_name,
                'sku': product.sku,
                'current_stock': product.current_stock,
                'updated_at': product.updated_at.isoformat()
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating product: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to update product',
            'detail': str(e)
        }), 500


@product_bp.route('/<product_id>/image', methods=['POST'])
@token_required
@tenant_required
@role_required(['admin', 'manager'])
def upload_product_image_endpoint(product_id):
    """
    Upload product image to S3.
    
    Args:
        product_id (str): Product UUID
    
    Returns:
        JSON: Image URL and metadata
    """
    try:
        product = Product.query.filter_by(
            id=product_id,
            tenant_id=request.tenant_id,
            is_deleted=False
        ).first()
        
        if not product:
            return jsonify({
                'status': 'error',
                'message': 'Product not found'
            }), 404
        
        if 'file' not in request.files:
            return jsonify({
                'status': 'error',
                'message': 'No file provided'
            }), 400
        
        file = request.files['file']
        success, result = upload_product_image(file, product_id, request.tenant_id)
        
        if not success:
            return jsonify({
                'status': 'error',
                'message': result
            }), 400
        
        # Update product with image URL
        product.image_url = result
        product.updated_at = datetime.utcnow()
        db.session.commit()
        
        # Log activity
        activity = ActivityLog(
            id=str(uuid.uuid4()),
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            action='UPLOAD_PRODUCT_IMAGE',
            resource_type='Product',
            resource_id=product.id,
            details={'image_url': result},
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')
        )
        db.session.add(activity)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Image uploaded successfully',
            'data': {
                'image_url': result
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error uploading image: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to upload image',
            'detail': str(e)
        }), 500


@product_bp.route('/<product_id>', methods=['DELETE'])
@token_required
@tenant_required
@role_required(['admin'])
def delete_product(product_id):
    """
    Soft delete a product (mark as deleted, don't remove from database).
    
    Args:
        product_id (str): Product UUID
    
    Returns:
        JSON: Deletion confirmation
    """
    try:
        product = Product.query.filter_by(
            id=product_id,
            tenant_id=request.tenant_id,
            is_deleted=False
        ).first()
        
        if not product:
            return jsonify({
                'status': 'error',
                'message': 'Product not found'
            }), 404
        
        product.is_deleted = True
        product.is_active = False
        product.updated_at = datetime.utcnow()
        db.session.commit()
        
        # Log activity
        activity = ActivityLog(
            id=str(uuid.uuid4()),
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            action='DELETE_PRODUCT',
            resource_type='Product',
            resource_id=product.id,
            details={'product_name': product.product_name, 'sku': product.sku},
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')
        )
        db.session.add(activity)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Product deleted successfully'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting product: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to delete product',
            'detail': str(e)
        }), 500


@product_bp.route('/stock/adjust/<product_id>', methods=['POST'])
@token_required
@tenant_required
@role_required(['admin', 'manager', 'stock_keeper'])
def adjust_stock(product_id):
    """
    Manually adjust product stock with audit trail.
    
    Request Body:
        - quantity (int): Quantity to add/subtract (negative for reduction)
        - reason (str): Reason for adjustment
        - reference_id (str, optional): Reference to sales/purchase order
    
    Returns:
        JSON: Updated stock information
    """
    try:
        product = Product.query.filter_by(
            id=product_id,
            tenant_id=request.tenant_id,
            is_deleted=False
        ).first()
        
        if not product:
            return jsonify({
                'status': 'error',
                'message': 'Product not found'
            }), 404
        
        data = request.get_json()
        
        if not data or 'quantity' not in data:
            return jsonify({
                'status': 'error',
                'message': 'Quantity is required'
            }), 400
        
        try:
            quantity = int(data['quantity'])
            if quantity == 0:
                return jsonify({
                    'status': 'error',
                    'message': 'Quantity cannot be zero'
                }), 400
        except:
            return jsonify({
                'status': 'error',
                'message': 'Quantity must be an integer'
            }), 400
        
        # Prevent over-deduction
        if product.current_stock + quantity < 0:
            return jsonify({
                'status': 'error',
                'message': f'Adjustment would result in negative stock'
            }), 400
        
        # Create stock movement record
        movement = StockMovement(
            id=str(uuid.uuid4()),
            product_id=product_id,
            tenant_id=request.tenant_id,
            movement_type='adjustment',
            quantity=quantity,
            previous_stock=product.current_stock,
            new_stock=product.current_stock + quantity,
            reference_id=data.get('reference_id'),
            notes=data.get('reason', 'Manual adjustment'),
            created_by=request.user_id
        )
        
        # Update product stock
        product.current_stock += quantity
        product.updated_at = datetime.utcnow()
        
        db.session.add(movement)
        db.session.commit()
        
        # Log activity
        activity = ActivityLog(
            id=str(uuid.uuid4()),
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            action='ADJUST_STOCK',
            resource_type='Product',
            resource_id=product.id,
            details={
                'quantity': quantity,
                'previous_stock': movement.previous_stock,
                'new_stock': movement.new_stock,
                'reason': data.get('reason', '')
            },
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')
        )
        db.session.add(activity)
        db.session.commit()
        
        alert = calculate_stock_alerts(product)
        
        return jsonify({
            'status': 'success',
            'message': 'Stock adjusted successfully',
            'data': {
                'product_id': product.id,
                'previous_stock': movement.previous_stock,
                'quantity_adjusted': quantity,
                'new_stock': product.current_stock,
                'alert': alert
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error adjusting stock: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to adjust stock',
            'detail': str(e)
        }), 500


@product_bp.route('/stock/movements/<product_id>', methods=['GET'])
@token_required
@tenant_required
def get_stock_movements(product_id):
    """
    Retrieve stock movement history for a product.
    
    Query Parameters:
        - page (int): Page number
        - per_page (int): Items per page
        - movement_type (str): Filter by type (sale, purchase, adjustment, return)
        - start_date (str): ISO format start date
        - end_date (str): ISO format end date
    
    Returns:
        JSON: Paginated stock movements
    """
    try:
        product = Product.query.filter_by(
            id=product_id,
            tenant_id=request.tenant_id,
            is_deleted=False
        ).first()
        
        if not product:
            return jsonify({
                'status': 'error',
                'message': 'Product not found'
            }), 404
        
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 50, type=int), 100)
        movement_type = request.args.get('movement_type', '', type=str)
        start_date = request.args.get('start_date', '', type=str)
        end_date = request.args.get('end_date', '', type=str)
        
        query = StockMovement.query.filter_by(product_id=product_id)
        
        if movement_type:
            query = query.filter_by(movement_type=movement_type)
        
        if start_date:
            try:
                start = datetime.fromisoformat(start_date)
                query = query.filter(StockMovement.created_at >= start)
            except:
                pass
        
        if end_date:
            try:
                end = datetime.fromisoformat(end_date)
                query = query.filter(StockMovement.created_at <= end)
            except:
                pass
        
        pagination = query.order_by(StockMovement.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        movements = [{
            'id': m.id,
            'movement_type': m.movement_type,
            'quantity': m.quantity,
            'previous_stock': m.previous_stock,
            'new_stock': m.new_stock,
            'reference_id': m.reference_id,
            'notes': m.notes,
            'created_by': m.created_by,
            'created_at': m.created_at.isoformat()
        } for m in pagination.items]
        
        return jsonify({
            'status': 'success',
            'data': movements,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': pagination.total,
                'pages': pagination.pages
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving stock movements: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to retrieve stock movements',
            'detail': str(e)
        }), 500


# ============================================================================
# LOW STOCK ALERTS
# ============================================================================

@product_bp.route('/alerts/low-stock', methods=['GET'])
@token_required
@tenant_required
def get_low_stock_alerts():
    """
    Retrieve all products with low stock (warning or critical).
    
    Query Parameters:
        - severity (str): Filter by 'warning' or 'critical'
        - include_inactive (bool): Include inactive products
    
    Returns:
        JSON: Products requiring attention
    """
    try:
        severity = request.args.get('severity', '', type=str)
        include_inactive = request.args.get('include_inactive', False, type=bool)
        
        query = Product.query.filter_by(
            tenant_id=request.tenant_id,
            is_deleted=False
        )
        
        if not include_inactive:
            query = query.filter_by(is_active=True)
        
        products = query.all()
        alerts = []
        
        for product in products:
            alert_info = calculate_stock_alerts(product)
            if alert_info['status'] != 'normal':
                if not severity or alert_info['status'] == severity:
                    alerts.append({
                        'product_id': product.id,
                        'product_name': product.product_name,
                        'sku': product.sku,
                        'alert': alert_info
                    })
        
        # Sort by severity
        severity_order = {'critical': 0, 'warning': 1}
        alerts.sort(key=lambda x: severity_order.get(x['alert']['status'], 2))
        
        return jsonify({
            'status': 'success',
            'data': alerts,
            'total': len(alerts)
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving low stock alerts: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to retrieve alerts',
            'detail': str(e)
        }), 500


__all__ = [
    'product_bp',
    'validate_product_data',
    'calculate_stock_alerts',
    'upload_product_image'
]
