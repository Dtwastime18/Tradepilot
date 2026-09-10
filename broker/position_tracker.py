from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime


@dataclass
class Position:
    symbol: str
    quantity: Decimal
    entry_price: Decimal
    target_price: Decimal
    fill_time: datetime
    status: str = "OPEN"

def create_position_from_fill(
    *,
    symbol,
    quantity,
    fill_price,
    target_price,
    fill_time,
    fill_confirmed=False,
):
    if fill_confirmed is not True:
        raise ValueError("Position requires a confirmed fill.")

    return Position(
        symbol=symbol,
        quantity=Decimal(str(quantity)),
        entry_price=Decimal(str(fill_price)),
        target_price=Decimal(str(target_price)),
        fill_time=fill_time,
        status="OPEN",
    )