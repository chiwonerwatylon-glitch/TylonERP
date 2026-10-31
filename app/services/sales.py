"""Sales totals computed in the database instead of loading every row into Python."""
from decimal import Decimal

from sqlalchemy import func

from ..models import Sale

LINE_TOTAL = Sale.quantity * Sale.unit_price


def _decimal(value):
    return Decimal(str(value)) if value is not None else Decimal(0)


def sale_totals(session, tenant_id, since=None, kind="all"):
    """Count, total, paid and owed for a tenant's sales, optionally filtered by date and kind.

    kind: 'all', 'cash' (paid in full) or 'credit' (anything not paid in full).
    """
    query = session.query(
        func.count(Sale.id),
        func.coalesce(func.sum(LINE_TOTAL), 0),
        func.coalesce(func.sum(Sale.paid), 0),
    ).filter(Sale.tenant_id == tenant_id)
    if since is not None:
        query = query.filter(Sale.created_at >= since)
    query = apply_kind(query, kind)
    count, total, paid = query.one()
    total, paid = _decimal(total), _decimal(paid)
    return {"count": count, "total": total, "paid": paid, "owed": total - paid}


def apply_kind(query, kind):
    if kind == "cash":
        return query.filter(Sale.paid >= LINE_TOTAL)
    if kind == "credit":
        return query.filter(Sale.paid < LINE_TOTAL)
    return query


def open_credit_sales(tenant_id):
    """Sales with a balance owing and a client to collect from, oldest first."""
    return (Sale.query.filter(Sale.tenant_id == tenant_id, Sale.client_id.isnot(None), Sale.paid < LINE_TOTAL)
            .order_by(Sale.created_at).all())
