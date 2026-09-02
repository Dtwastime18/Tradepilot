import asyncio

from broker.robinhood_mcp_session import open_mcp_session


async def main():
    async with open_mcp_session() as session:
        print(type(session).__name__)
        print(hasattr(session, "review_equity_order"))


asyncio.run(main())