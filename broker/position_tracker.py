from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from turtle import position


@dataclass
class Position:
    symbol: str
    quantity: Decimal
    entry_price: Decimal
    target_price: Decimal
    fill_time: datetime
    status: str = "OPEN"
    exit_price: Decimal | None = None
    exit_time: datetime | None = None

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

def update_position_status(position, current_price):
    current_price = Decimal(str(current_price))

    if position.status != "OPEN":
        return position

    if current_price >= position.target_price:
        position.status = "TARGET REACHED"

    return position

def close_position(
    position,
    exit_price=None,
    exit_time=None,
    exit_confirmed=False,
):
    if position.status != "TARGET REACHED":
        raise ValueError("Position target has not been reached.")

    if exit_confirmed is not True:
        raise ValueError("Position requires a confirmed exit.")

    if exit_price is None or exit_time is None:
        raise ValueError("Confirmed exit requires exit price and exit time.")

    position.exit_price = Decimal(str(exit_price))
    position.exit_time = exit_time

    position.status = "CLOSED"
    return position

def calculate_realized_pnl(position):
    if position.status != "CLOSED":
        raise ValueError("Realized P/L requires a closed position.")

    if position.exit_price is None:
        raise ValueError("Closed position is missing exit price.")

    return (position.exit_price - position.entry_price) * position.quantity