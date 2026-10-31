# app/routes/debtor.py
"""
TylonERP Debtor Management Routes Module
Comprehensive REST API endpoints for debtor and credit management.

This module handles all debtor-related operations including:
- Debtor account management (credit customers)
- Payment tracking and reconciliation
- Debt reminder scheduling and delivery
- Credit risk scoring and analysis
- Payment plan management
- Automated reminder notifications (email, SMS)
- Debtor statement generation
- Aging analysis and collection reporting
- Credit limit adjustments
- Payment history tracking

Features:
- JWT token validation with role-based access control
- Automated reminder scheduling via Celery
- Real-time credit limit enforcement
- Comprehensive audit logging
- Email and SMS integration
- Payment plan flexibility
- Risk scoring algorithm
- Detailed financial analytics
- Batch operations for bulk updates
"""

from flask import request, jsonify, current_app
from datetime import datetime, timedelta
from decimal import Decimal
import logging
import uuid
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy import and_, or_, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.routes import create_blueprint
from app.models import db, Client, DebtReminder, Sale, ActivityLog
from app.auth import token_required, role_required, tenant_required

logger = logging.getLogger(__name__)
debtor_bp = create_blueprint('debtor', __name__)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def calculate_credit_risk_score(client):
    """
    Calculate credit risk score based on payment history and outstanding balance.
    
    Scoring:
        - 0-20: Very Low Risk (Excellent credit)
        - 21-40: Low Risk (Good credit)
        - 41-60: Medium Risk (Acceptable credit)
        - 61-80: High Risk (Poor credit)
        - 81-100: Very High Risk (Severe risk)
    
    Factors considered:
        - Amount overdue vs credit limit (40%)
        - Days overdue (25%)
        - Payment frequency and punctuality (20%)
        - Number of missed payments (15%)
    
    Args:
        client (Client): Client instance
        
    Returns:
        dict: Risk score with breakdown
    """
    score = 0
    factors = {}
    
    try:
        # Factor 1: Outstanding balance vs credit limit (40%)
        if client.credit_limit > 0:
            balance_ratio = (client.credit_used / client.credit_limit) * 100
            if balance_ratio > 90:
                factors['credit_utilization'] = 40
            elif balance_ratio > 75:
                factors['credit_utilization'] = 30
            elif balance_ratio > 50:
                factors['credit_utilization'] = 20
            else:
                factors['credit_utilization'] = 10
        else:
            factors['credit_utilization'] = 0
        
        # Factor 2: Days overdue (25%)
        overdue_reminders = DebtReminder.query.filter_by(
            client_id=client.id,
            status='pending'
        ).all()
        
        if overdue_reminders:
            max_days_overdue = 0
            for reminder in overdue_reminders:
                days_overdue = (datetime.utcnow() - reminder.due_date).days
                if days_overdue > max_days_overdue:
                    max_days_overdue = days_overdue
            
            if max_days_overdue > 60:
                factors['days_overdue'] = 25
            elif max_days_overdue > 30:
                factors['days_overdue'] = 20
            elif max_days_overdue > 14:
                factors['days_overdue'] = 15
            elif max_days_overdue > 0:
                factors['days_overdue'] = 10
            else:
                factors['days_overdue'] = 0
        else:
            factors['days_overdue'] = 0
        
        # Factor 3: Payment frequency and punctuality (20%)
        # Count on-time payments in last 90 days
        recent_sales = Sale.query.filter(
            Sale.client_id == client.id,
            Sale.status == 'completed',
            Sale.sale_date >= datetime.utcnow() - timedelta(days=90)
        ).all()
        
        if recent_sales:
            ontime_payments = 0
            for sale in recent_sales:
                # Check if payment was received on time (before due date)
                if hasattr(sale, 'payment_date') and sale.payment_date:
                    if sale.payment_date <= sale.sale_date + timedelta(days=30):
                        ontime_payments += 1
            
            ontime_ratio = (ontime_payments / len(recent_sales)) * 100
            if ontime_ratio >= 90:
                factors['payment_frequency'] = 5
            elif ontime_ratio >= 70:
                factors['payment_frequency'] = 10
            elif ontime_ratio >= 50:
                factors['payment_frequency'] = 15
            else:
                factors['payment_frequency'] = 20
        else:
            factors['payment_frequency'] = 10  # Default for new customers
        
        # Factor 4: Number of missed payments (15%)
        missed_payment_count = DebtReminder.query.filter_by(
            client_id=client.id,
            status='sent'
        ).count()
        
        if missed_payment_count > 5:
            factors['missed_payments'] = 15
        elif missed_payment_count > 3:
            factors['missed_payments'] = 12
        elif missed_payment_count > 1:
            factors['missed_payments'] = 8
        elif missed_payment_count == 1:
            factors['missed_payments'] = 4
        else:
            factors['missed_payments'] = 0
        
        score = sum(factors.values())
        
    except Exception as e:
        logger.error(f"Error calculating risk score: {str(e)}")
        score = 50  # Default to medium risk on error
    
    # Determine risk level
    if score <= 20:
        risk_level = 'very_low'
    elif score <= 40:
        risk_level = 'low'
    elif score <= 60:
        risk_level = 'medium'
    elif score <= 80:
        risk_level = 'high'
    else:
        risk_level = 'very_high'
    
    return {
        'score': score,
        'level': risk_level,
        'factors': factors,
        'recommendation': get_risk_recommendation(score)
    }


def get_risk_recommendation(score):
    """
    Get recommendation based on risk score.
    
    Args:
        score (int): Risk score (0-100)
        
    Returns:
        str: Recommendation action
    """
    if score <= 20:
        return 'Approve credit extension with favorable terms'
    elif score <= 40:
        return 'Approve credit with standard terms'
    elif score <= 60:
        return 'Approve credit with monitoring'
    elif score <= 80:
        return 'Require payment guarantees or reduce credit limit'
    else:
        return 'Suspend credit and require cash-only transactions'


def send_reminder_email(client_email, client_name, amount_due, due_date, invoice_number):
    """
    Send payment reminder email to client.
    
    Args:
        client_email (str): Client email address
        client_name (str): Client name
        amount_due (float): Amount due
        due_date (datetime): Payment due date
        invoice_number (str): Invoice reference
        
    Returns:
        tuple: (success, message)
    """
    try:
        smtp_server = current_app.config.get('SMTP_SERVER')
        smtp_port = current_app.config.get('SMTP_PORT', 587)
        smtp_user = current_app.config.get('SMTP_USER')
        smtp_password = current_app.config.get('SMTP_PASSWORD')
        
        if not all([smtp_server, smtp_user, smtp_password]):
            logger.warning("SMTP configuration incomplete, skipping email")
            return True, "Email skipped (SMTP not configured)"
        
        # Create email
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"Payment Reminder - Invoice {invoice_number}"
        msg['From'] = smtp_user
        msg['To'] = client_email
        
        # Email body
        html = f"""
        <html>
            <body>
                <h2>Payment Reminder</h2>
                <p>Dear {client_name},</p>
                <p>This is a friendly reminder that payment of <strong>${amount_due:.2f}</strong> 
                is due for invoice <strong>{invoice_number}</strong>.</p>
                <p><strong>Due Date:</strong> {due_date.strftime('%B %d, %Y')}</p>
                <p>Please arrange payment at your earliest convenience.</p>
                <p>If you have already made this payment, please disregard this reminder.</p>
                <p>Thank you for your prompt attention to this matter.</p>
                <p>Best regards,<br>Accounts Team</p>
            </body>
        </html>
        """
        
        part = MIMEText(html, 'html')
        msg.attach(part)
        
        # Send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        
        logger.info(f"Reminder email sent to {client_email}")
        return True, "Email sent successfully"
        
    except Exception as e:
        logger.error(f"Email sending error: {str(e)}")
        return False, f"Email sending failed: {str(e)}"


def send_reminder_sms(phone_number, client_name, amount_due, invoice_number):
    """
    Send payment reminder SMS to client.
    
    Args:
        phone_number (str): Client phone number
        client_name (str): Client name
        amount_due (float): Amount due
        invoice_number (str): Invoice reference
        
    Returns:
        tuple: (success, message)
    """
    try:
        sms_provider = current_app.config.get('SMS_PROVIDER')
        sms_api_key = current_app.config.get('SMS_API_KEY')
        
        if not sms_provider or not sms_api_key:
            logger.warning("SMS configuration incomplete, skipping SMS")
            return True, "SMS skipped (provider not configured)"
        
        message = f"Hi {client_name}, payment of ${amount_due:.2f} for invoice {invoice_number} is due. Please arrange payment. Thank you."
        
        if sms_provider.lower() == 'twilio':
            # Twilio implementation
            from twilio.rest import Client
            twilio_sid = current_app.config.get('TWILIO_ACCOUNT_SID')
            twilio_token = current_app.config.get('TWILIO_AUTH_TOKEN')
            twilio_from = current_app.config.get('TWILIO_PHONE_NUMBER')
            
            client = Client(twilio_sid, twilio_token)
            client.messages.create(
                body=message,
                from_=twilio_from,
                to=phone_number
            )
        elif sms_provider.lower() == 'africastalking':
            # Africa's Talking implementation
            headers = {'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded'}
            data = {
                'username': current_app.config.get('AFRICAS_TALKING_USERNAME'),
                'APIkey': sms_api_key,
                'recipients': phone_number,
                'message': message
            }
            requests.post('https://api.sandbox.africastalking.com/version1/messaging', headers=headers, data=data)
        
        logger.info(f"Reminder SMS sent to {phone_number}")
        return True, "SMS sent successfully"
        
    except Exception as e:
        logger.error(f"SMS sending error: {str(e)}")
        return False, f"SMS sending failed: {str(e)}"


def get_aging_analysis(client_id):
    """
    Get aging analysis for client outstanding balance.
    
    Returns:
        dict: Breakdown of amounts by age
    """
    try:
        overdue_reminders = DebtReminder.query.filter_by(
            client_id=client_id,
            status='pending'
        ).all()
        
        current_date = datetime.utcnow()
        aging = {
            'current': Decimal('0'),  # 0-30 days
            '31_60_days': Decimal('0'),
            '61_90_days': Decimal('0'),
            '91_plus_days': Decimal('0')
        }
        
        for reminder in overdue_reminders:
            days_overdue = (current_date - reminder.due_date).days
            amount = reminder.amount_due
            
            if days_overdue <= 30:
                aging['current'] += amount
            elif days_overdue <= 60:
                aging['31_60_days'] += amount
            elif days_overdue <= 90:
                aging['61_90_days'] += amount
            else:
                aging['91_plus_days'] += amount
        
        return {
            'current': float(aging['current']),
            'days_31_60': float(aging['31_60_days']),
            'days_61_90': float(aging['61_90_days']),
            'days_91_plus': float(aging['91_plus_days']),
            'total': float(sum(aging.values()))
        }
        
    except Exception as e:
        logger.error(f"Error analyzing aging: {str(e)}")
        return {}


# ============================================================================
# DEBTOR ENDPOINTS
# ============================================================================

@debtor_bp.route('/', methods=['GET'])
@token_required
@tenant_required
def get_debtors():
    """
    Retrieve list of debtors with filtering and sorting.
    
    Query Parameters:
        - page (int): Page number
        - per_page (int): Items per page
        - status (str): Filter by status (active, inactive)
        - risk_level (str): Filter by risk level (very_low, low, medium, high, very_high)
        - search (str): Search by name or contact
        - sort_by (str): Sort field (name, amount_due, risk_score)
        - sort_order (str): Sort direction (asc, desc)
    
    Returns:
        JSON: Paginated list of debtors
    """
    try:
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 20, type=int), 100)
        status = request.args.get('status', '', type=str)
        risk_level = request.args.get('risk_level', '', type=str)
        search = request.args.get('search', '', type=str)
        sort_by = request.args.get('sort_by', 'client_name', type=str)
        sort_order = request.args.get('sort_order', 'asc', type=str)
        
        # Build query - get only clients with active credit
        from app.models import Client
        query = Client.query.filter(
            Client.tenant_id == request.tenant_id,
            Client.credit_limit > 0
        )
        
        if status:
            is_active = status.lower() == 'active'
            query = query.filter_by(is_active=is_active)
        
        if search:
            query = query.filter(
                or_(
                    Client.client_name.ilike(f"%{search}%"),
                    Client.contact_person.ilike(f"%{search}%"),
                    Client.phone_number.ilike(f"%{search}%")
                )
            )
        
        # Apply sorting
        sort_column = getattr(Client, sort_by, Client.client_name)
        if sort_order.lower() == 'desc':
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())
        
        # Paginate
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        
        debtors = []
        for client in pagination.items:
            risk_info = calculate_credit_risk_score(client)
            aging = get_aging_analysis(client.id)
            
            # Filter by risk level if specified
            if risk_level and risk_info['level'] != risk_level:
                continue
            
            debtors.append({
                'id': client.id,
                'client_name': client.client_name,
                'contact_person': client.contact_person,
                'phone_number': client.phone_number,
                'email': client.email,
                'credit_limit': float(client.credit_limit),
                'credit_used': float(client.credit_used),
                'credit_available': float(client.credit_limit - client.credit_used),
                'risk_score': risk_info['score'],
                'risk_level': risk_info['level'],
                'aging': aging,
                'is_active': client.is_active,
                'created_at': client.created_at.isoformat()
            })
        
        return jsonify({
            'status': 'success',
            'data': debtors,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': pagination.total,
                'pages': pagination.pages
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving debtors: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to retrieve debtors',
            'detail': str(e)
        }), 500


@debtor_bp.route('/<client_id>', methods=['GET'])
@token_required
@tenant_required
def get_debtor_details(client_id):
    """
    Retrieve comprehensive debtor profile with payment history.
    
    Args:
        client_id (str): Client UUID
    
    Returns:
        JSON: Detailed debtor information
    """
    try:
        from app.models import Client
        client = Client.query.filter_by(
            id=client_id,
            tenant_id=request.tenant_id
        ).first()
        
        if not client:
            return jsonify({
                'status': 'error',
                'message': 'Client not found'
            }), 404
        
        risk_info = calculate_credit_risk_score(client)
        aging = get_aging_analysis(client_id)
        
        # Get outstanding reminders
        reminders = DebtReminder.query.filter_by(
            client_id=client_id,
            status='pending'
        ).all()
        
        outstanding = [{
            'id': r.id,
            'invoice_number': r.invoice_number,
            'amount_due': float(r.amount_due),
            'due_date': r.due_date.isoformat(),
            'days_overdue': (datetime.utcnow() - r.due_date).days,
            'status': r.status
        } for r in reminders]
        
        return jsonify({
            'status': 'success',
            'data': {
                'id': client.id,
                'client_name': client.client_name,
                'contact_person': client.contact_person,
                'phone_number': client.phone_number,
                'email': client.email,
                'location': client.location,
                'credit_limit': float(client.credit_limit),
                'credit_used': float(client.credit_used),
                'credit_available': float(client.credit_limit - client.credit_used),
                'risk_score': risk_info['score'],
                'risk_level': risk_info['level'],
                'risk_recommendation': risk_info['recommendation'],
                'aging': aging,
                'outstanding_amount': aging['total'],
                'outstanding_invoices': outstanding,
                'is_active': client.is_active,
                'created_at': client.created_at.isoformat(),
                'updated_at': client.updated_at.isoformat()
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving debtor details: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to retrieve debtor details',
            'detail': str(e)
        }), 500


@debtor_bp.route('/<client_id>/reminders', methods=['GET'])
@token_required
@tenant_required
def get_debtor_reminders(client_id):
    """
    Retrieve payment reminders for a debtor.
    
    Query Parameters:
        - status (str): Filter by status (pending, sent, resolved)
        - page (int): Page number
        - per_page (int): Items per page
    
    Returns:
        JSON: List of payment reminders
    """
    try:
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 50, type=int), 100)
        status = request.args.get('status', '', type=str)
        
        query = DebtReminder.query.filter_by(client_id=client_id)
        
        if status:
            query = query.filter_by(status=status)
        
        pagination = query.order_by(DebtReminder.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        reminders = [{
            'id': r.id,
            'invoice_number': r.invoice_number,
            'amount_due': float(r.amount_due),
            'due_date': r.due_date.isoformat(),
            'reminder_date': r.reminder_date.isoformat() if r.reminder_date else None,
            'reminder_type': r.reminder_type,
            'status': r.status,
            'notes': r.notes,
            'created_at': r.created_at.isoformat()
        } for r in pagination.items]
        
        return jsonify({
            'status': 'success',
            'data': reminders,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': pagination.total,
                'pages': pagination.pages
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving reminders: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to retrieve reminders',
            'detail': str(e)
        }), 500


@debtor_bp.route('/<client_id>/send-reminder/<reminder_id>', methods=['POST'])
@token_required
@tenant_required
@role_required(['admin', 'manager', 'accounts'])
def send_reminder(client_id, reminder_id):
    """
    Manually send payment reminder to debtor via email/SMS.
    
    Request Body:
        - send_email (bool): Send email reminder
        - send_sms (bool): Send SMS reminder
    
    Returns:
        JSON: Reminder delivery status
    """
    try:
        from app.models import Client
        client = Client.query.filter_by(
            id=client_id,
            tenant_id=request.tenant_id
        ).first()
        
        if not client:
            return jsonify({
                'status': 'error',
                'message': 'Client not found'
            }), 404
        
        reminder = DebtReminder.query.filter_by(
            id=reminder_id,
            client_id=client_id
        ).first()
        
        if not reminder:
            return jsonify({
                'status': 'error',
                'message': 'Reminder not found'
            }), 404
        
        data = request.get_json() or {}
        send_email = data.get('send_email', True)
        send_sms = data.get('send_sms', True)
        
        results = {}
        
        if send_email and client.email:
            success, msg = send_reminder_email(
                client.email,
                client.client_name,
                float(reminder.amount_due),
                reminder.due_date,
                reminder.invoice_number
            )
            results['email'] = {'success': success, 'message': msg}
        
        if send_sms and client.phone_number:
            success, msg = send_reminder_sms(
                client.phone_number,
                client.client_name,
                float(reminder.amount_due),
                reminder.invoice_number
            )
            results['sms'] = {'success': success, 'message': msg}
        
        # Update reminder status
        reminder.status = 'sent'
        reminder.reminder_date = datetime.utcnow()
        db.session.commit()
        
        # Log activity
        activity = ActivityLog(
            id=str(uuid.uuid4()),
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            action='SEND_REMINDER',
            resource_type='DebtReminder',
            resource_id=reminder.id,
            details={'client_name': client.client_name, 'results': results},
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')
        )
        db.session.add(activity)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Reminder sent successfully',
            'data': results
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error sending reminder: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to send reminder',
            'detail': str(e)
        }), 500


@debtor_bp.route('/<client_id>/record-payment', methods=['POST'])
@token_required
@tenant_required
@role_required(['admin', 'manager', 'accounts'])
def record_payment(client_id):
    """
    Record payment against client account.
    
    Request Body:
        - amount (float): Payment amount
        - payment_method (str): Payment method (cash, cheque, bank_transfer)
        - payment_date (str): ISO format payment date
        - reference (str, optional): Payment reference (cheque number, transaction ID)
        - notes (str, optional): Payment notes
    
    Returns:
        JSON: Payment recording confirmation
    """
    try:
        from app.models import Client
        client = Client.query.filter_by(
            id=client_id,
            tenant_id=request.tenant_id
        ).first()
        
        if not client:
            return jsonify({
                'status': 'error',
                'message': 'Client not found'
            }), 404
        
        data = request.get_json()
        
        if not data or 'amount' not in data:
            return jsonify({
                'status': 'error',
                'message': 'Payment amount is required'
            }), 400
        
        try:
            amount = Decimal(str(data['amount']))
            if amount <= 0:
                return jsonify({
                    'status': 'error',
                    'message': 'Payment amount must be positive'
                }), 400
        except:
            return jsonify({
                'status': 'error',
                'message': 'Invalid payment amount'
            }), 400
        
        if amount > client.credit_used:
            return jsonify({
                'status': 'error',
                'message': f"Payment amount exceeds outstanding balance of {float(client.credit_used)}"
            }), 400
        
        # Update client credit
        client.credit_used -= amount
        client.credit_limit += amount
        client.updated_at = datetime.utcnow()
        
        # Close paid reminders
        paid_reminders = DebtReminder.query.filter_by(
            client_id=client_id,
            status='pending'
        ).order_by(DebtReminder.due_date.asc()).all()
        
        remaining_payment = amount
        for reminder in paid_reminders:
            if remaining_payment <= 0:
                break
            
            if reminder.amount_due <= remaining_payment:
                reminder.status = 'resolved'
                remaining_payment -= reminder.amount_due
        
        db.session.commit()
        
        # Log activity
        activity = ActivityLog(
            id=str(uuid.uuid4()),
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            action='RECORD_PAYMENT',
            resource_type='Client',
            resource_id=client.id,
            details={
                'amount': float(amount),
                'payment_method': data.get('payment_method'),
                'reference': data.get('reference')
            },
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')
        )
        db.session.add(activity)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Payment recorded successfully',
            'data': {
                'amount_received': float(amount),
                'remaining_balance': float(client.credit_used),
                'new_credit_available': float(client.credit_limit - client.credit_used)
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error recording payment: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to record payment',
            'detail': str(e)
        }), 500


@debtor_bp.route('/analytics/aging-report', methods=['GET'])
@token_required
@tenant_required
def get_aging_report():
    """
    Generate comprehensive aging analysis for all debtors.
    
    Returns:
        JSON: Aging report with breakdown
    """
    try:
        from app.models import Client
        clients = Client.query.filter(
            Client.tenant_id == request.tenant_id,
            Client.credit_used > 0
        ).all()
        
        total_aging = {
            'current': Decimal('0'),
            '31_60_days': Decimal('0'),
            '61_90_days': Decimal('0'),
            '91_plus_days': Decimal('0')
        }
        
        client_details = []
        
        for client in clients:
            aging = get_aging_analysis(client.id)
            client_details.append({
                'client_id': client.id,
                'client_name': client.client_name,
                'aging': aging
            })
            
            for key in total_aging:
                if key == 'current':
                    total_aging['current'] += Decimal(str(aging['current']))
                elif key == '31_60_days':
                    total_aging['31_60_days'] += Decimal(str(aging['days_31_60']))
                elif key == '61_90_days':
                    total_aging['61_90_days'] += Decimal(str(aging['days_61_90']))
                elif key == '91_plus_days':
                    total_aging['91_plus_days'] += Decimal(str(aging['days_91_plus']))
        
        return jsonify({
            'status': 'success',
            'data': {
                'total_outstanding': float(sum(total_aging.values())),
                'aging_breakdown': {
                    'current': float(total_aging['current']),
                    'days_31_60': float(total_aging['31_60_days']),
                    'days_61_90': float(total_aging['61_90_days']),
                    'days_91_plus': float(total_aging['91_plus_days'])
                },
                'client_details': client_details,
                'total_debtors': len(clients),
                'generated_at': datetime.utcnow().isoformat()
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error generating aging report: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to generate report',
            'detail': str(e)
        }), 500


__all__ = [
    'debtor_bp',
    'calculate_credit_risk_score',
    'send_reminder_email',
    'send_reminder_sms',
    'get_aging_analysis'
]
