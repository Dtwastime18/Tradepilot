from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from turtle import position
import json
from pathlib import Path

POSITIONS_FILE = Path("Data/positions.json")


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

def save_positions(positions):
    POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)

    data = []

    for position in positions:
        data.append(
            {
                "symbol": position.symbol,
                "quantity": str(position.quantity),
                "entry_price": str(position.entry_price),
                "target_price": str(position.target_price),
                "fill_time": position.fill_time.isoformat(),
                "status": position.status,
                "exit_price": (
                    str(position.exit_price)
                    if position.exit_price is not None
                    else None
                ),
                "exit_time": (
                    position.exit_time.isoformat()
                    if position.exit_time is not None
                    else None
                ),
            }
        )

    POSITIONS_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )

def load_positions():
    if not POSITIONS_FILE.exists():
        return []

    text = POSITIONS_FILE.read_text(encoding="utf-8").strip()

    if not text:
        return []

    data = json.loads(text)
    positions = []

    for item in data:
        positions.append(
            Position(
                symbol=item["symbol"],
                quantity=Decimal(item["quantity"]),
                entry_price=Decimal(item["entry_price"]),
                target_price=Decimal(item["target_price"]),
                fill_time=datetime.fromisoformat(item["fill_time"]),
                status=item["status"],
                exit_price=(
                    Decimal(item["exit_price"])
                    if item["exit_price"] is not None
                    else None
                ),
                exit_time=(
                    datetime.fromisoformat(item["exit_time"])
                    if item["exit_time"] is not None
                    else None
                ),
            )
        )

    return positions   

def get_active_positions(positions):
    return [
        position
        for position in positions
        if position.status in {"OPEN", "TARGET REACHED"}
    ]

def record_confirmed_fill(
    *,
    symbol,
    quantity,
    fill_price,
    target_price,
    fill_time,
    fill_confirmed=False,
):
    position = create_position_from_fill(
        symbol=symbol,
        quantity=quantity,
        fill_price=fill_price,
        target_price=target_price,
        fill_time=fill_time,
        fill_confirmed=fill_confirmed,
    )

    positions = load_positions()
    positions.append(position)
    save_positions(positions)

    return position