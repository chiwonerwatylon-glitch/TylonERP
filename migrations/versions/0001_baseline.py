"""baseline

Revision ID: 0001
Revises: 
Create Date: 2026-10-31 16:25:32.529049

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def _existing(table):
    insp = sa.inspect(op.get_bind())
    return insp.has_table(table), insp


def _create_table(name, *items):
    """Create the table, or on a database that already has it, add any missing nullable columns.

    Releases before migrations created tables with create_all and added columns by hand, so
    a live database can already have this table in an older shape.
    """
    exists, insp = _existing(name)
    if not exists:
        op.create_table(name, *items)
        return
    have = {c["name"] for c in insp.get_columns(name)}
    for item in items:
        if isinstance(item, sa.Column) and item.name not in have and item.nullable:
            op.add_column(name, item)


def _create_index(table, name, columns, unique=False):
    insp = sa.inspect(op.get_bind())
    if any(ix["name"] == name for ix in insp.get_indexes(table)):
        return
    op.create_index(name, table, columns, unique=unique)


def upgrade():
    """Create the schema, or bring a database created by an older release up to date."""
    _create_table('tenants',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('slug', sa.String(length=60), nullable=False),
    sa.Column('contact_email', sa.String(length=255), nullable=False),
    sa.Column('phone', sa.String(length=40), nullable=True),
    sa.Column('plan', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('trial_ends_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index('tenants', 'ix_tenants_slug', ['slug'], unique=True)

    _create_table('clients',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('phone', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index('clients', 'ix_clients_tenant_id', ['tenant_id'], unique=False)

    _create_table('products',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('sku', sa.String(length=60), nullable=True),
    sa.Column('price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('stock', sa.Integer(), nullable=False),
    sa.Column('reorder_level', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('method', sa.String(length=10), nullable=True),
    sa.Column('barcode', sa.String(length=64), nullable=True),
    sa.Column('scent', sa.String(length=120), nullable=True),
    sa.Column('photo', sa.LargeBinary(), nullable=True),
    sa.Column('photo_mime', sa.String(length=40), nullable=True),
    sa.Column('signature', sa.String(length=70), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index('products', 'ix_products_tenant_id', ['tenant_id'], unique=False)
    _create_index('products', 'uq_product_barcode', ['tenant_id', 'barcode'], unique=True)

    _create_table('tenant_branding',
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('headline', sa.String(length=120), nullable=True),
    sa.Column('tagline', sa.String(length=240), nullable=True),
    sa.Column('image', sa.LargeBinary(), nullable=True),
    sa.Column('image_mime', sa.String(length=40), nullable=True),
    sa.Column('logo', sa.LargeBinary(), nullable=True),
    sa.Column('logo_mime', sa.String(length=40), nullable=True),
    sa.Column('accent', sa.String(length=7), nullable=True),
    sa.Column('background', sa.String(length=7), nullable=True),
    sa.Column('panel', sa.String(length=7), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('tenant_id')
    )
    _create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('must_change_password', sa.Boolean(), nullable=False),
    sa.Column('failed_attempts', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(), nullable=True),
    sa.Column('last_login', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index('users', 'ix_users_email', ['email'], unique=True)
    _create_index('users', 'ix_users_tenant_id', ['tenant_id'], unique=False)

    _create_table('sales',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('client_id', sa.Integer(), nullable=True),
    sa.Column('product_id', sa.Integer(), nullable=True),
    sa.Column('product_name', sa.String(length=150), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('paid', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index('sales', 'ix_sales_created_at', ['created_at'], unique=False)
    _create_index('sales', 'ix_sales_tenant_id', ['tenant_id'], unique=False)


def downgrade():
    with op.batch_alter_table('sales', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sales_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_sales_created_at'))

    op.drop_table('sales')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
    op.drop_table('tenant_branding')
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_index('uq_product_barcode')
        batch_op.drop_index(batch_op.f('ix_products_tenant_id'))

    op.drop_table('products')
    with op.batch_alter_table('clients', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_clients_tenant_id'))

    op.drop_table('clients')
    with op.batch_alter_table('tenants', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tenants_slug'))

    op.drop_table('tenants')
