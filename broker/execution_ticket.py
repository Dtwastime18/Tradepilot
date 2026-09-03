from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

@dataclass(frozen=True)
class ExecutionTicket:
    symbol: str
    side: str
    quantity: Decimal
    order_type: str
    limit_price: Optional[Decimal] = None

def validate_execution_ticket(ticket: ExecutionTicket) -> bool:
    if not ticket.symbol or not ticket.symbol.strip():
        return False
    
    if not ticket.quantity.is_finite():
        return False

    if ticket.quantity <= 0:
        return False
    
    if ticket.side not in {"buy", "sell"}:
        return False

    if ticket.order_type not in {"market", "limit"}:
        return False

    if ticket.order_type == "limit":
        if ticket.limit_price is None:
            return False

    if not ticket.limit_price.is_finite():
        return False

    if ticket.limit_price <= 0:
        return False
    
    return True 