import asyncio
import keyring
import webbrowser
from urllib.parse import parse_qs, urlparse
import httpx2
from mcp.client.streamable_http import streamable_http_client
from contextlib import asynccontextmanager

MCP_SERVER_URL = "https://agent.robinhood.com/mcp/trading"
ALLOWED_TOOLS = frozenset({
    "get_accounts",
    "review_equity_order",
})

def require_allowed_tool(tool_name):
    if tool_name not in ALLOWED_TOOLS:
        raise PermissionError(f"Tool not allowed: {tool_name}")



from mcp import ClientSession
from mcp.client.auth import (
    AuthorizationCodeResult,
    OAuthClientProvider,
    OAuthFlowError,
    TokenStorage,
)

from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)

ROBINHOOD_MCP_URL = "https://agent.robinhood.com/mcp/trading"
KEYRING_SERVICE = "TradePilotAI-Robinhood-MCP"
TOKEN_KEY = "oauth_tokens"
CLIENT_INFO_KEY = "oauth_client_info"
REDIRECT_URI = "http://127.0.0.1:8765/callback"

class KeychainTokenStorage:
    async def get_tokens(self):
        value = keyring.get_password(KEYRING_SERVICE, TOKEN_KEY)
        if value is None:
            return None
        return OAuthToken.model_validate_json(value)

    async def set_tokens(self, tokens):
        keyring.set_password(
            KEYRING_SERVICE,
            TOKEN_KEY,
            tokens.model_dump_json(),
        )

    async def get_client_info(self):
        value = keyring.get_password(KEYRING_SERVICE, CLIENT_INFO_KEY)
        if value is None:
            return None
        return OAuthClientInformationFull.model_validate_json(value)

    async def set_client_info(self, client_info):
        keyring.set_password(
            KEYRING_SERVICE,
            CLIENT_INFO_KEY,
            client_info.model_dump_json(),
        )
async def handle_redirect(auth_url):
    loop = asyncio.get_running_loop()
    loop.call_later(0.5, webbrowser.open, auth_url)

async def handle_callback():
                    loop = asyncio.get_running_loop()
                    result_future = loop.create_future()

                    async def handle_client(reader, writer):
                        request_line = await reader.readline()
                        path = request_line.decode("utf-8").split(" ")[1]

                        query = parse_qs(urlparse(path).query)

                        code = query.get("code", [None])[0]
                        if not code:
                            if not result_future.done():
                                result_future.set_exception(
                                    RuntimeError("OAuth callback missing authorization code")
                                )
                            return
                        state = query.get("state", [None])[0]
                        iss = query.get("iss", [None])[0]

                        response = (
                            "HTTP/1.1 200 OK\r\n"
                            "Content-Type: text/plain\r\n"
                            "Connection: close\r\n"
                            "\r\n"
                            "Authorization received. You can close this window."
                        )
                        writer.write(response.encode("utf-8"))
                        await writer.drain()
                        writer.close()
                        await writer.wait_closed()

                        if not result_future.done():
                            result_future.set_result(
                                AuthorizationCodeResult(
                                    code=code,
                                    state=state,
                                    iss=iss,
                                )
                            )

                    server = await asyncio.start_server(
                        handle_client,
                        "127.0.0.1",
                        8765,
                    )

                    async with server:
                        return await result_future
def create_oauth_provider():
    metadata = OAuthClientMetadata(
        redirect_uris=[REDIRECT_URI]
    )

    return OAuthClientProvider(
        server_url=MCP_SERVER_URL,
        client_metadata=metadata,
        storage=KeychainTokenStorage(),
        redirect_handler=handle_redirect,
        callback_handler=handle_callback,
    )   
def _create_http_client():
    provider = create_oauth_provider()
    return httpx2.AsyncClient(auth=provider)     

async def call_allowed(session, tool_name, arguments=None):
    require_allowed_tool(tool_name)
    return await session.call_tool(tool_name, arguments or {})             

def sanitize_mcp_response(tool_name, response):
    if tool_name == "get_accounts":
        return {"status": "ACCOUNT ACCESS CONFIRMED"}

    if tool_name == "review_equity_order":
        structured = getattr(response, "structured_content", None)
    if not isinstance(structured, dict):
        return {"status": "REVIEW RESPONSE INVALID"}

    data = structured.get("data")
    if not isinstance(data, dict):
        return {"status": "REVIEW RESPONSE INVALID"}

    order_checks = data.get("order_checks")
    if not isinstance(order_checks, dict):
        return {"status": "REVIEW RESPONSE INVALID"}

    alert_type = order_checks.get("alert_type")
    if alert_type is not None and not isinstance(alert_type, str):
        return {"status": "REVIEW RESPONSE INVALID"}

    if alert_type not in {None, "info", "warning", "error"}:
        return {"status": "REVIEW RESPONSE INVALID"}

    return {
        "data": {
            "order_checks": {
                "alert_type": alert_type,
            }
        }
    }

    raise PermissionError(f"Tool not allowed: {tool_name}")

class RestrictedMcpSession:
    def __init__(self, get_accounts_caller, review_equity_order_caller):
        self.__get_accounts_caller = get_accounts_caller
        self.__review_equity_order_caller = review_equity_order_caller

    async def get_accounts(self):
        return await self.__get_accounts_caller()

    async def review_equity_order(self, payload):
        return await self.__review_equity_order_caller(payload)
        
def extract_agentic_account_number(response):
    structured = getattr(response, "structured_content", None)
    if not isinstance(structured, dict):
        return None

    data = structured.get("data")
    if not isinstance(data, dict):
        return None

    accounts = data.get("accounts")
    if not isinstance(accounts, list):
        return None

    matches = [
        account.get("account_number")
        for account in accounts
        if isinstance(account, dict)
        and account.get("agentic_allowed") is True
        and isinstance(account.get("account_number"), str)
        and account.get("account_number")
    ]

    if len(matches) != 1:
        return None

    return matches[0]

@asynccontextmanager      
async def open_mcp_session():
    http_client = _create_http_client()

    async with http_client:
        async with streamable_http_client(
            MCP_SERVER_URL,
            http_client=http_client,
            terminate_on_close=False,
        ) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                

                

                async def get_accounts_caller():
                    response = await call_allowed(session, "get_accounts", {})
                    account_number = extract_agentic_account_number(response)

                    if account_number is None:
                        return {"status": "ACCOUNT ACCESS INVALID"}

                    return {"status": "ACCOUNT ACCESS CONFIRMED"}

                async def review_equity_order_caller(payload):
                    account_response = await call_allowed(session, "get_accounts", {})
                    agentic_account_number = extract_agentic_account_number(account_response)

                    if agentic_account_number is None:
                        return {"status": "REVIEW RESPONSE INVALID"}

                    review_payload = dict(payload)
                    review_payload["account_number"] = agentic_account_number

                    response = await call_allowed(
                        session,
                        "review_equity_order",
                        review_payload,
                    )

                    return sanitize_mcp_response("review_equity_order", response)

                yield RestrictedMcpSession(
                    get_accounts_caller,
                    review_equity_order_caller,
                )

