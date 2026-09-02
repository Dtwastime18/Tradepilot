from broker.robinhood_review_only import review_equity_order as _review_equity_order
import re
_EQUITY_SYMBOL = re.compile(r"^[A-Z]{1,5}(?:[.-][A-Z]{1,2})?\Z")
SAFE_ALERT_TYPES = frozenset({"info", "warning", "error"})
import re
from decimal import Decimal, InvalidOperation
_SENSITIVE_TEXT = re.compile(
    r"""(?ix)
    \b(?:account|acct)\b.{0,24}\b(?:id|number|ending|ends)\b
    |\b(?:id|number)\b.{0,24}\b(?:account|acct)\b
    |\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b
    |\b\d{8,}\b
    """
)

def _is_safe_review_text(value):
    return (
        value is None
        or (
            type(value) is str
            and not _SENSITIVE_TEXT.search(value)
        )
    )

ALLOWED_TOOLS = {
    "get_accounts",
    "review_equity_order",
}
def is_allowed_tool(tool_name):
    return tool_name in ALLOWED_TOOLS

def require_allowed_tool(tool_name):
    if not is_allowed_tool(tool_name):
        raise ValueError(f"Tool not allowed: {tool_name}")

    return True

def _is_positive_decimal(value):
    if isinstance(value, bool):
        return False

    if not isinstance(value, (int, float, Decimal, str)):
        return False

    if isinstance(value, str) and not value.strip():
        return False

    try:
        decimal_value = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return False

    return decimal_value.is_finite() and decimal_value > Decimal("0")   

def validate_order_details(order):
        if not isinstance(order, SanitizedOrderDetails):
            return False

        if (
            type(order.symbol) is not str
            or _EQUITY_SYMBOL.fullmatch(order.symbol) is None
        ):
            return False

        if order.side not in {"buy", "sell"}:
            return False

        if order.order_type not in {"market", "limit", "stop_market", "stop_limit"}:
            return False

        if order.quantity is None and order.dollar_amount is None:
            return False

        if order.quantity is not None and order.dollar_amount is not None:
            return False

        if (
        order.quantity is not None
        and not _is_positive_decimal(order.quantity)
        ):
            return False

        if (
        order.dollar_amount is not None
        and not _is_positive_decimal(order.dollar_amount)
        ):
            return False

        if order.dollar_amount is not None and order.order_type != "market":
            return False

        if order.order_type in {"limit", "stop_limit"}:
            if not _is_positive_decimal(order.limit_price):
                return False

        if order.order_type in {"stop_market", "stop_limit"}:
            if not _is_positive_decimal(order.stop_price):
                return False

        if order.time_in_force not in {"gfd", "gtc"}:
            return False

        if order.market_hours not in {"regular_hours"}:
            return False

        return True

class SanitizedOrderDetails:
    def __init__(
        self,
        symbol,
        side,
        order_type,
        quantity=None,
        dollar_amount=None,
        limit_price=None,
        stop_price=None,
        time_in_force="gfd",
        market_hours="regular_hours",
    ):
        self.symbol = symbol
        self.side = side
        self.order_type = order_type
        self.quantity = quantity
        self.dollar_amount = dollar_amount
        self.limit_price = limit_price
        self.stop_price = stop_price
        self.time_in_force = time_in_force
        self.market_hours = market_hours


class SanitizedReviewResult:
    
    def __init__(
        self,
        success=False,
        status="NOT REVIEWED",
        symbol=None,
        side=None,
        order_type=None,
        quantity=None,
        message=None,
        alert_type=None,
        alert_message=None,
        guide_message=None,
    ):
        self.success = success
        self.status = status
        self.symbol = symbol
        self.side = side
        self.order_type = order_type
        self.quantity = quantity
        self.message = message
        self.alert_type = alert_type
        self.alert_message = alert_message
        self.guide_message = guide_message

def build_sanitized_order(preview):
    return SanitizedOrderDetails(
        symbol=preview["symbol"],
        side=preview.get("side", "buy"),
        order_type=preview.get("order_type", "market"),
        quantity=preview.get("quantity"),
        dollar_amount=preview.get("dollar_amount"),
        limit_price=preview.get("limit_price"),
        stop_price=preview.get("stop_price"),
        time_in_force=preview.get("time_in_force", "gfd"),
        market_hours=preview.get("market_hours", "regular_hours"),
    )

def serialize_review_order(order):
    if not validate_order_details(order):
        raise ValueError("Invalid sanitized order details")

    payload = {
        "symbol": order.symbol,
        "side": order.side,
        "type": order.order_type,
        "quantity": str(order.quantity) if order.quantity is not None else None,
        "dollar_amount": str(order.dollar_amount) if order.dollar_amount is not None else None,
        "limit_price": str(order.limit_price) if order.limit_price is not None else None,
        "stop_price": str(order.stop_price) if order.stop_price is not None else None,
        "time_in_force": order.time_in_force,
        "market_hours": order.market_hours,
    }

    return {
        key: value
        for key, value in payload.items()
        if value is not None
    }  

def sanitize_review_response(response, order):
    def invalid_response():
        return SanitizedReviewResult(
            success=False,
            status="REVIEW ERROR",
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            quantity=order.quantity,
            message="Invalid review response",
        )
    if not isinstance(response, dict):
        return invalid_response()
    data = response.get("data")

    if not isinstance(data, dict):
        return invalid_response()
    if "order_checks" not in data:
        return invalid_response()

    order_checks = data["order_checks"]

    if not isinstance(order_checks, dict):
        return invalid_response()

    alert_type = order_checks.get("alert_type")

    if (
        alert_type is not None
        and (
            type(alert_type) is not str
            or alert_type not in SAFE_ALERT_TYPES
        )
    ):
        return invalid_response()
    
    return SanitizedReviewResult(
        success=True,
        status="REVIEW COMPLETE",
        symbol=order.symbol,
        side=order.side,
        order_type=order.order_type,
        quantity=order.quantity,
        message="Robinhood review completed",
        alert_message=None,
        guide_message=None,
        alert_type=alert_type
    )

class ReviewEquityOrderCapability:
    __slots__ = ()

    async def review_equity_order(self, session, payload):
        return await session.review_equity_order(payload)

async def request_broker_review(order, review_capability, session):
    if type(review_capability) is not ReviewEquityOrderCapability:
        return SanitizedReviewResult(
            success=False,
            status="REVIEW ERROR",
            message="Review unavailable",
        )
    from broker.robinhood_mcp_session import RestrictedMcpSession
    if type(session) is not RestrictedMcpSession:
        return SanitizedReviewResult(
            success=False,
            status="REVIEW ERROR",
            message="Review unavailable",
        )

    if not isinstance(order, SanitizedOrderDetails):
        return SanitizedReviewResult(
            success=False,
            status="REVIEW ERROR",
            message="Invalid order",
        )
    try:
        if not validate_order_details(order):
            return SanitizedReviewResult(
                success=False,
                status="REVIEW ERROR",
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                quantity=order.quantity,
                message="Invalid order",
            )

        
        require_allowed_tool("review_equity_order")
        payload = serialize_review_order(order)
        response = await review_capability.review_equity_order(session, payload)
        return sanitize_review_response(response, order)
            

    except Exception:
        return SanitizedReviewResult(
            success=False,
            status="REVIEW ERROR",
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            quantity=order.quantity,
            message="Review unavailable",
        )