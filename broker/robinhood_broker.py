import subprocess
import uuid

class RobinhoodBroker:

    def __init__(self):
        self.connected = False
        self._handled_order_ids = set()

    def connect(self):
        """
        Verifies read-only Robinhood MCP access through Codex.
        Does not place, preview, modify, cancel, or submit orders.
        """

        prompt = (
            "Use only the Robinhood get_accounts tool. "
            "Do not place, preview, modify, cancel, or submit any orders. "
            "Return only whether Robinhood account access is working. "
            "Do not include account numbers or sensitive identifiers."
        )

        result = subprocess.run(
           ["codex", "exec", "--skip-git-repo-check", "--json", prompt],
            capture_output=True,
            text=True
        )

        output = result.stdout.lower()


        self.connected = (
            result.returncode == 0
            and "access is working" in output
        )

        return {
            "connected": self.connected,
            "mode": "ROBINHOOD MCP READ-ONLY",
        }

    def mark_mcp_connected(self, verified=False):
        """
        Records whether Robinhood MCP access has been
        independently verified. Does not authenticate
        or submit any orders.
        """

        self.connected = bool(verified)

        return {
            "connected": self.connected,
            "mode": "ROBINHOOD MCP",
        }   

    def get_account_status(self):
        """
        Read-only account status placeholder.
        """
        return {
            "connected": self.connected
        }
    def preview_order(
        self,
        symbol,
        quantity,
        order_type="market"
    ):
        """
        Creates an order preview only.
        Does NOT submit an order.
        """

        return {
            "order_id": uuid.uuid4().hex,
            "symbol": symbol,
            "quantity": quantity,
            "order_type": order_type,
            "status": "PREVIEW ONLY",
            "submitted": False
        }        
    def approve_preview(
        self,
        preview,
        approved=False
    ):
        """
        Manual approval gate.
        Still does NOT submit a real order.
        """

        if not approved:
            return {
                **preview,
                "status": "AWAITING APPROVAL",
                "approved": False,
                "submitted": False
            }

        return {
            **preview,
            "status": "APPROVED - NOT SUBMITTED",
            "approved": True,
            "submitted": False
        } 
    def can_submit_order(
        self,
        preview,
        test_mode=True
    ):
        """
        Hard submission guardrail.
        Returns True only when every required condition is satisfied.
        """
        return self.get_submission_block_reason(
            preview,
            test_mode=test_mode,
        ) == "READY FOR MANUAL SUBMISSION"

    def build_execution_handoff(self, preview, test_mode=True):
        block_reason = self.get_submission_block_reason(
        preview,
        test_mode=test_mode,
    )

        return {
        "symbol": preview.get("symbol"),
        "quantity": preview.get("quantity"),
        "order_type": preview.get("order_type"),
        "approved": preview.get("approved", False),
        "submitted": preview.get("submitted", False),
        "status": block_reason,
    }
        

    def get_submission_block_reason(
        self,
        preview,
        test_mode=True
    ):
        if test_mode:
            return "BLOCKED: TEST MODE ENABLED"

        if not self.connected:
            return "BLOCKED: BROKER NOT CONNECTED"

        if not preview.get("approved", False):
            return "BLOCKED: ORDER NOT APPROVED"

        order_id = preview.get("order_id")

        if order_id and order_id in self._handled_order_ids:
            return "BLOCKED: ORDER ALREADY HANDLED"

        if preview.get("submitted", False):
            return "BLOCKED: ORDER ALREADY SUBMITTED"

        return "READY FOR MANUAL SUBMISSION"