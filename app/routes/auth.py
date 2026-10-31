# app/routes/auth.py
"""
Authentication and Authorization Routes
Handles user registration, login, password management,
and session management with comprehensive security
"""

from flask import (
    Blueprint, request, jsonify, render_template, redirect, url_for,
    session, current_app, flash
)
from flask_login import (
    login_user, logout_user, login_required, current_user
)
from functools import wraps
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import and_, or_
import jwt
import secrets
import qrcode
from io import BytesIO
import base64

from app import db
from app.models.tenant import Tenant, User, ActivityLog
from app.forms.auth_forms import (
    RegistrationForm, LoginForm, PasswordChangeForm,
    PasswordResetRequestForm, PasswordResetForm, TwoFactorForm
)

bp = Blueprint('auth', __name__, url_prefix='/auth')


# ============================================================================
# DECORATORS FOR PERMISSION & ROLE CHECKING
# ============================================================================

def tenant_required(f):
    """Decorator to ensure user belongs to specified tenant"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        
        if not current_user.is_active:
            flash('Your account is disabled', 'danger')
            logout_user()
            return redirect(url_for('auth.login'))
        
        if not current_user.tenant.is_active:
            flash('Your organization account is disabled', 'danger')
            logout_user()
            return redirect(url_for('auth.login'))
        
        if current_user.tenant.is_suspended:
            flash(
                f'Your organization account is suspended: {current_user.tenant.suspension_reason}',
                'danger'
            )
            logout_user()
            return redirect(url_for('auth.login'))
        
        return f(*args, **kwargs)
    
    return decorated_function


def role_required(*roles):
    """Decorator to check user role"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            if current_user.role not in roles:
                log_activity(
                    tenant_id=current_user.tenant_id,
                    user_id=current_user.id,
                    action='unauthorized_access',
                    action_type='READ',
                    resource_type='restricted_resource',
                    status_code=403
                )
                return jsonify({'error': 'Insufficient permissions'}), 403
            
            return f(*args, **kwargs)
        
        return decorated_function
    
    return decorator


def permission_required(permission):
    """Decorator to check specific permission"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            if not current_user.has_permission(permission):
                log_activity(
                    tenant_id=current_user.tenant_id,
                    user_id=current_user.id,
                    action='unauthorized_permission',
                    action_type='READ',
                    resource_type='restricted_permission',
                    status_code=403
                )
                return jsonify({'error': 'Permission denied'}), 403
            
            return f(*args, **kwargs)
        
        return decorated_function
    
    return decorator


def two_factor_required(f):
    """Decorator for routes requiring 2FA verification"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        
        if current_user.tenant.enforce_two_factor and not session.get('two_factor_verified'):
            return redirect(url_for('auth.verify_two_factor'))
        
        return f(*args, **kwargs)
    
    return decorated_function


def activity_logger(action_type, resource_type):
    """Decorator to log activity"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            result = f(*args, **kwargs)
            
            if current_user.is_authenticated:
                log_activity(
                    tenant_id=current_user.tenant_id,
                    user_id=current_user.id,
                    action=f.__name__,
                    action_type=action_type,
                    resource_type=resource_type,
                    endpoint=request.endpoint,
                    http_method=request.method
                )
            
            return result
        
        return decorated_function
    
    return decorator


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def log_activity(tenant_id, user_id=None, action='', action_type='', 
                resource_type='', resource_id=None, resource_name=None,
                old_values=None, new_values=None, endpoint='', 
                http_method='', status_code=200, ip_address=None):
    """
    Log user activity for audit trail
    
    Args:
        tenant_id (int): Tenant ID
        user_id (int): User ID
        action (str): Action name
        action_type (str): CREATE, READ, UPDATE, DELETE, LOGIN
        resource_type (str): Type of resource
        resource_id (int): Resource ID
        resource_name (str): Resource name
        old_values (dict): Previous values
        new_values (dict): New values
        endpoint (str): Flask endpoint
        http_method (str): HTTP method
        status_code (int): Response status code
        ip_address (str): Client IP address
    """
    try:
        log_entry = ActivityLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            action_type=action_type,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            old_values=old_values,
            new_values=new_values,
            ip_address=ip_address or request.remote_addr,
            user_agent=request.user_agent.string,
            http_method=http_method or request.method,
            endpoint=endpoint or request.endpoint,
            status_code=status_code
        )
        db.session.add(log_entry)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(f'Failed to log activity: {str(e)}')


def send_verification_email(user, token):
    """Send email verification token"""
    # TODO: Implement email sending
    current_app.logger.info(f'Verification email would be sent to {user.email}')


def send_password_reset_email(user, token):
    """Send password reset email"""
    # TODO: Implement email sending
    current_app.logger.info(f'Password reset email would be sent to {user.email}')


def generate_qr_code_for_2fa(secret):
    """Generate QR code for 2FA setup"""
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(secret)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    return base64.b64encode(buffer.getvalue()).decode()


# ============================================================================
# AUTHENTICATION ROUTES
# ============================================================================

@bp.route('/register', methods=['GET', 'POST'])
def register():
    """
    User and tenant registration
    Creates new tenant organization and admin user
    """
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    form = RegistrationForm()
    
    if form.validate_on_submit():
        try:
            # Check if tenant slug already exists
            if Tenant.query.filter_by(slug=form.tenant_slug.data).first():
                flash('Organization slug already exists', 'danger')
                return render_template('auth/register.html', form=form)
            
            # Create tenant
            tenant = Tenant(
                name=form.tenant_name.data,
                slug=form.tenant_slug.data,
                email=form.tenant_email.data,
                phone=form.tenant_phone.data,
                address=form.tenant_address.data,
                city=form.tenant_city.data,
                state=form.tenant_state.data,
                country=form.tenant_country.data,
                postal_code=form.tenant_postal_code.data,
                business_type=form.business_type.data,
                currency=form.currency.data,
                timezone=form.timezone.data,
                is_trial=True,
                trial_ends_at=datetime.utcnow() + timedelta(days=30)
            )
            db.session.add(tenant)
            db.session.flush()
            
            # Create admin user
            user = User(
                tenant_id=tenant.id,
                email=form.email.data,
                username=form.username.data,
                first_name=form.first_name.data,
                last_name=form.last_name.data,
                is_active=True
            )
            user.set_password(form.password.data)
            user.set_role('admin')
            
            db.session.add(user)
            db.session.commit()
            
            # Generate email verification token
            token = user.generate_email_verification_token()
            send_verification_email(user, token)
            
            log_activity(
                tenant_id=tenant.id,
                user_id=user.id,
                action='user_registration',
                action_type='CREATE',
                resource_type='user',
                resource_id=user.id,
                resource_name=user.email,
                new_values={'email': user.email, 'username': user.username}
            )
            
            flash(
                'Registration successful! Please check your email to verify your account.',
                'success'
            )
            
            return redirect(url_for('auth.login'))
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Registration error: {str(e)}')
            flash('An error occurred during registration. Please try again.', 'danger')
    
    return render_template('auth/register.html', form=form)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    User login with multi-tenant support
    Handles email/username authentication and session management
    """
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    form = LoginForm()
    
    if form.validate_on_submit():
        # Find user by email or username
        user = User.query.filter(
            and_(
                User.email == form.email.data
            )
        ).first()
        
        if not user:
            user = User.query.filter(
                and_(
                    User.username == form.email.data
                )
            ).first()
        
        if user and user.check_password(form.password.data):
            # Check account status
            if user.is_account_locked():
                flash(
                    'Your account is locked. Please try again later or contact support.',
                    'warning'
                )
                return render_template('auth/login.html', form=form)
            
            if not user.is_active:
                flash('Your account has been deactivated.', 'danger')
                return render_template('auth/login.html', form=form)
            
            # Check tenant status
            if not user.tenant.is_active:
                flash('Your organization account is not active.', 'danger')
                return render_template('auth/login.html', form=form)
            
            if user.tenant.is_suspended:
                flash(
                    f'Your organization account is suspended: {user.tenant.suspension_reason}',
                    'danger'
                )
                return render_template('auth/login.html', form=form)
            
            # Check if password change is required
            if user.require_password_change:
                session['requires_password_change'] = True
                session['user_id'] = user.id
                return redirect(url_for('auth.change_password'))
            
            # Check if 2FA is enabled
            if user.two_factor_enabled:
                session['pending_user_id'] = user.id
                session['user_email'] = user.email
                flash('Please complete two-factor authentication', 'info')
                return redirect(url_for('auth.verify_two_factor'))
            
            # Successful login
            login_user(user, remember=form.remember_me.data)
            user.record_successful_login(
                ip_address=request.remote_addr,
                user_agent=request.user_agent.string
            )
            
            log_activity(
                tenant_id=user.tenant_id,
                user_id=user.id,
                action='user_login',
                action_type='LOGIN',
                resource_type='user',
                resource_id=user.id,
                resource_name=user.email,
                ip_address=request.remote_addr
            )
            
            flash(f'Welcome back, {user.get_full_name()}!', 'success')
            
            next_page = request.args.get('next')
            if next_page and next_page.startswith('/'):
                return redirect(next_page)
            
            return redirect(url_for('dashboard.index'))
        
        else:
            # Failed login
            if user:
                user.record_failed_login()
            
            log_activity(
                action='failed_login_attempt',
                action_type='LOGIN',
                resource_type='user',
                resource_name=form.email.data,
                status_code=401,
                ip_address=request.remote_addr
            )
            
            flash('Invalid email/username or password.', 'danger')
    
    return render_template('auth/login.html', form=form)


@bp.route('/logout')
@login_required
def logout():
    """User logout"""
    user_id = current_user.id
    tenant_id = current_user.tenant_id
    
    logout_user()
    
    log_activity(
        tenant_id=tenant_id,
        user_id=user_id,
        action='user_logout',
        action_type='LOGIN',
        resource_type='user',
        resource_id=user_id
    )
    
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('auth.login'))


# ============================================================================
# EMAIL VERIFICATION ROUTES
# ============================================================================

@bp.route('/verify-email/<token>')
def verify_email(token):
    """Verify email from token"""
    user = User.query.filter_by(email_verification_token=token).first()
    
    if not user:
        flash('Invalid or expired verification token.', 'danger')
        return redirect(url_for('auth.login'))
    
    user.verify_email()
    db.session.commit()
    
    flash('Your email has been verified successfully!', 'success')
    return redirect(url_for('auth.login'))


@bp.route('/resend-verification-email', methods=['POST'])
def resend_verification_email():
    """Resend verification email"""
    if current_user.is_authenticated:
        if current_user.is_verified:
            flash('Your email is already verified.', 'info')
            return redirect(url_for('dashboard.index'))
        
        token = current_user.generate_email_verification_token()
        send_verification_email(current_user, token)
        
        flash('Verification email sent to your inbox.', 'success')
        return redirect(url_for('dashboard.index'))
    
    return redirect(url_for('auth.login'))


# ============================================================================
# PASSWORD MANAGEMENT ROUTES
# ============================================================================

@bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Change password"""
    form = PasswordChangeForm()
    
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash('Current password is incorrect.', 'danger')
            return render_template('auth/change_password.html', form=form)
        
        current_user.set_password(form.new_password.data)
        current_user.require_password_change = False
        db.session.commit()
        
        log_activity(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action='password_changed',
            action_type='UPDATE',
            resource_type='user',
            resource_id=current_user.id,
            resource_name=current_user.email
        )
        
        flash('Your password has been changed successfully.', 'success')
        return redirect(url_for('dashboard.index'))
    
    return render_template('auth/change_password.html', form=form)


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Request password reset"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    form = PasswordResetRequestForm()
    
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        
        if user:
            token = user.generate_password_reset_token()
            send_password_reset_email(user, token)
            
            log_activity(
                tenant_id=user.tenant_id,
                user_id=user.id,
                action='password_reset_requested',
                action_type='UPDATE',
                resource_type='user',
                resource_id=user.id,
                resource_name=user.email
            )
        
        flash(
            'If an account exists with that email, a password reset link has been sent.',
            'info'
        )
        return redirect(url_for('auth.login'))
    
    return render_template('auth/forgot_password.html', form=form)


@bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Reset password using token"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    user = User.query.filter_by(password_reset_token=token).first()
    
    if not user or (user.password_reset_expires and 
                    datetime.utcnow() > user.password_reset_expires):
        flash('The password reset link is invalid or has expired.', 'danger')
        return redirect(url_for('auth.login'))
    
    form = PasswordResetForm()
    
    if form.validate_on_submit():
        user.reset_password(form.password.data)
        db.session.commit()
        
        log_activity(
            tenant_id=user.tenant_id,
            user_id=user.id,
            action='password_reset',
            action_type='UPDATE',
            resource_type='user',
            resource_id=user.id,
            resource_name=user.email
        )
        
        flash('Your password has been reset successfully!', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/reset_password.html', form=form)


# ============================================================================
# TWO-FACTOR AUTHENTICATION ROUTES
# ============================================================================

@bp.route('/verify-2fa', methods=['GET', 'POST'])
def verify_two_factor():
    """Verify two-factor authentication code"""
    pending_user_id = session.get('pending_user_id')
    
    if not pending_user_id:
        return redirect(url_for('auth.login'))
    
    user = User.query.get(pending_user_id)
    if not user:
        return redirect(url_for('auth.login'))
    
    form = TwoFactorForm()
    
    if form.validate_on_submit():
        # TODO: Verify TOTP code
        login_user(user)
        session['two_factor_verified'] = True
        session.pop('pending_user_id', None)
        
        flash('Two-factor authentication successful!', 'success')
        return redirect(url_for('dashboard.index'))
    
    return render_template('auth/verify_2fa.html', form=form, email=user.email)


@bp.route('/setup-2fa', methods=['GET', 'POST'])
@login_required
def setup_two_factor():
    """Set up two-factor authentication"""
    if current_user.two_factor_enabled:
        flash('Two-factor authentication is already enabled.', 'info')
        return redirect(url_for('dashboard.profile'))
    
    # TODO: Generate TOTP secret and QR code
    secret = secrets.token_urlsafe(32)
    qr_code = generate_qr_code_for_2fa(secret)
    
    if request.method == 'POST':
        # Verify code and save
        current_user.two_factor_enabled = True
        current_user.two_factor_secret = secret
        db.session.commit()
        
        log_activity(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action='2fa_enabled',
            action_type='UPDATE',
            resource_type='user',
            resource_id=current_user.id,
            resource_name=current_user.email
        )
        
        flash('Two-factor authentication has been enabled.', 'success')
        return redirect(url_for('dashboard.profile'))
    
    return render_template('auth/setup_2fa.html', qr_code=qr_code)


@bp.route('/disable-2fa', methods=['POST'])
@login_required
def disable_two_factor():
    """Disable two-factor authentication"""
    current_user.two_factor_enabled = False
    current_user.two_factor_secret = None
    db.session.commit()
    
    log_activity(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action='2fa_disabled',
        action_type='UPDATE',
        resource_type='user',
        resource_id=current_user.id,
        resource_name=current_user.email
    )
    
    flash('Two-factor authentication has been disabled.', 'success')
    return redirect(url_for('dashboard.profile'))


# ============================================================================
# USER MANAGEMENT ROUTES
# ============================================================================

@bp.route('/users')
@login_required
@tenant_required
@role_required('admin', 'manager')
def list_users():
    """List all users in tenant"""
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config['ITEMS_PER_PAGE']
    
    users = current_user.tenant.users.filter_by(deleted_at=None).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    return render_template(
        'auth/users_list.html',
        users=users,
        title='User Management'
    )


@bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@tenant_required
@role_required('admin')
def create_user():
    """Create new user"""
    if request.method == 'POST':
        # Check if can add more users
        if not current_user.tenant.can_add_user():
            flash(
                f'You have reached the maximum number of users ({current_user.tenant.max_users}) for your plan.',
                'warning'
            )
            return redirect(url_for('auth.list_users'))
        
        try:
            email = request.form.get('email')
            username = request.form.get('username')
            first_name = request.form.get('first_name')
            last_name = request.form.get('last_name')
            role = request.form.get('role', 'staff')
            
            # Check if user exists
            if User.query.filter_by(email=email).first():
                flash('A user with this email already exists.', 'danger')
                return render_template('auth/create_user.html')
            
            # Create user
            user = User(
                tenant_id=current_user.tenant_id,
                email=email,
                username=username,
                first_name=first_name,
                last_name=last_name,
                is_active=True
            )
            user.set_role(role)
            
            # Generate temporary password
            temp_password = secrets.token_urlsafe(16)
            user.set_password(temp_password)
            user.require_password_change = True
            
            db.session.add(user)
            db.session.commit()
            
            # TODO: Send email with temporary password
            
            log_activity(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                action='user_created',
                action_type='CREATE',
                resource_type='user',
                resource_id=user.id,
                resource_name=email,
                new_values={'email': email, 'role': role}
            )
            
            flash(f'User {email} has been created successfully.', 'success')
            return redirect(url_for('auth.list_users'))
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Error creating user: {str(e)}')
            flash('An error occurred while creating the user.', 'danger')
    
    return render_template('auth/create_user.html')


@bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@tenant_required
@role_required('admin', 'manager')
def edit_user(user_id):
    """Edit user"""
    user = User.query.filter_by(
        id=user_id,
        tenant_id=current_user.tenant_id
    ).first_or_404()
    
    if request.method == 'POST':
        old_values = {
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'role': user.role
        }
        
        user.email = request.form.get('email', user.email)
        user.first_name = request.form.get('first_name')
        user.last_name = request.form.get('last_name')
        new_role = request.form.get('role', user.role)
        
        if new_role != user.role:
            user.set_role(new_role)
        
        db.session.commit()
        
        log_activity(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action='user_updated',
            action_type='UPDATE',
            resource_type='user',
            resource_id=user.id,
            resource_name=user.email,
            old_values=old_values,
            new_values={
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role
            }
        )
        
        flash('User has been updated successfully.', 'success')
        return redirect(url_for('auth.list_users'))
    
    return render_template('auth/edit_user.html', user=user)


@bp.route('/users/<int:user_id>/deactivate', methods=['POST'])
@login_required
@tenant_required
@role_required('admin')
def deactivate_user(user_id):
    """Deactivate user"""
    user = User.query.filter_by(
        id=user_id,
        tenant_id=current_user.tenant_id
    ).first_or_404()
    
    if user.id == current_user.id:
        flash('You cannot deactivate your own account.', 'warning')
        return redirect(url_for('auth.list_users'))
    
    user.deactivate()
    
    log_activity(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action='user_deactivated',
        action_type='UPDATE',
        resource_type='user',
        resource_id=user.id,
        resource_name=user.email
    )
    
    flash(f'User {user.email} has been deactivated.', 'success')
    return redirect(url_for('auth.list_users'))


@bp.route('/users/<int:user_id>/activate', methods=['POST'])
@login_required
@tenant_required
@role_required('admin')
def activate_user(user_id):
    """Activate user"""
    user = User.query.filter_by(
        id=user_id,
        tenant_id=current_user.tenant_id
    ).first_or_404()
    
    user.activate()
    
    log_activity(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action='user_activated',
        action_type='UPDATE',
        resource_type='user',
        resource_id=user.id,
        resource_name=user.email
    )
    
    flash(f'User {user.email} has been activated.', 'success')
    return redirect(url_for('auth.list_users'))


@bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@tenant_required
@role_required('admin')
def reset_user_password(user_id):
    """Admin reset of user password"""
    user = User.query.filter_by(
        id=user_id,
        tenant_id=current_user.tenant_id
    ).first_or_404()
    
    temp_password = secrets.token_urlsafe(16)
    user.set_password(temp_password)
    user.require_password_change = True
    db.session.commit()
    
    # TODO: Send email with new password
    
    log_activity(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action='user_password_reset',
        action_type='UPDATE',
        resource_type='user',
        resource_id=user.id,
        resource_name=user.email
    )
    
    flash(f'Password reset email has been sent to {user.email}.', 'success')
    return redirect(url_for('auth.list_users'))


# ============================================================================
# PERMISSION MANAGEMENT ROUTES
# ============================================================================

@bp.route('/users/<int:user_id>/permissions', methods=['GET', 'POST'])
@login_required
@tenant_required
@role_required('admin')
def manage_permissions(user_id):
    """Manage user permissions"""
    user = User.query.filter_by(
        id=user_id,
        tenant_id=current_user.tenant_id
    ).first_or_404()
    
    if request.method == 'POST':
        old_permissions = user.permissions.copy() if user.permissions else {}
        
        # Update permissions
        for permission in user.permissions.keys():
            user.permissions[permission] = request.form.get(
                f'permission_{permission}'
            ) == 'on'
        
        db.session.commit()
        
        log_activity(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action='user_permissions_updated',
            action_type='UPDATE',
            resource_type='user',
            resource_id=user.id,
            resource_name=user.email,
            old_values=old_permissions,
            new_values=user.permissions
        )
        
        flash('User permissions have been updated.', 'success')
        return redirect(url_for('auth.list_users'))
    
    return render_template('auth/manage_permissions.html', user=user)


# ============================================================================
# SESSION MANAGEMENT ROUTES
# ============================================================================

@bp.route('/sessions')
@login_required
@tenant_required
def list_sessions():
    """List active sessions"""
    # TODO: Implement session tracking and management
    return render_template('auth/sessions.html')


@bp.route('/sessions/<session_id>/revoke', methods=['POST'])
@login_required
@tenant_required
def revoke_session(session_id):
    """Revoke specific session"""
    # TODO: Implement session revocation
    flash('Session has been revoked.', 'success')
    return redirect(url_for('auth.list_sessions'))


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@bp.errorhandler(401)
def unauthorized(error):
    """Unauthorized access"""
    flash('You must be logged in to access this page.', 'danger')
    return redirect(url_for('auth.login'))


@bp.errorhandler(403)
def forbidden(error):
    """Forbidden access"""
    flash('You do not have permission to access this page.', 'danger')
    return redirect(url_for('dashboard.index'))
