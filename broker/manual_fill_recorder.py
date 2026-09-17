from datetime import datetime
from decimal import Decimal

from broker.position_tracker import record_confirmed_fill


def record_manual_confirmed_fill(
    *,
    symbol,
    quantity,
    fill_price,
    target_price,
    fill_time,
    fill_confirmed=False,
):
    if fill_confirmed is not True:
        raise ValueError(
            "Manual fill recording requires explicit fill confirmation."
        )

    if not symbol:
        raise ValueError("Symbol is required.")

    quantity = Decimal(str(quantity))
    fill_price = Decimal(str(fill_price))
    target_price = Decimal(str(target_price))

    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")

    if fill_price <= 0:
        raise ValueError("Fill price must be greater than zero.")

    if target_price <= 0:
        raise ValueError("Target price must be greater than zero.")

    if not isinstance(fill_time, datetime):
        raise ValueError("Fill time must be a datetime.")

    return record_confirmed_fill(
        symbol=str(symbol).upper(),
        quantity=quantity,
        fill_price=fill_price,
        target_price=target_price,
        fill_time=fill_time,
        fill_confirmed=True,
    )