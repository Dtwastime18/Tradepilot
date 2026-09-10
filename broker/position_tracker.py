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