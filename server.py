"""Indodax MCP Server
This server exposes Indodax private REST API methods as MCP tools so that
agents can call them easily.

All methods listed in the official documentation for the `method` parameter are
implemented:
    - getInfo
    - transHistory
    - trade
    - tradeHistory
    - openOrders
    - orderHistory
    - getOrder
    - getOrderByClientOrderId
    - cancelOrder
    - cancelByClientOrderId
    - withdrawFee
    - withdrawCoin
    - listDownline
    - checkDownline
    - createVoucher

Environment Variables (see .env):
    INDODAX_API_KEY       Your Indodax API key
    INDODAX_API_SECRET    Your Indodax API secret (HMAC-SHA512 signing key)
    MCP_AUTH_USER         HTTP Basic Auth username (required for HTTP transport)
    MCP_AUTH_PASSWORD     HTTP Basic Auth password (required for HTTP transport)

Note:  The Indodax private API is available ONLY via HTTPS POST to the single
endpoint https://indodax.com/tapi.  Authentication is performed by sending
headers:
    Key  -> API key
    Sign -> HMAC-SHA512 signature of the request body using the secret key.

The FastMCP server makes each private request asynchronously using httpx.

HTTP Basic Auth (for SSE / streamable-HTTP transport only):
    Set MCP_AUTH_USER and MCP_AUTH_PASSWORD in .env.  Every HTTP request must
    carry an Authorization: Basic <base64(user:pass)> header.  stdio transport
    skips auth entirely (local process, no network exposure).
"""
from __future__ import annotations

import base64
import hmac
import hashlib
import os
import secrets
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

# ---------------------------------------------------------------------------
# Environment & global initialisation
# ---------------------------------------------------------------------------
load_dotenv()

API_KEY: str | None = os.getenv("INDODAX_API_KEY")
# Allow legacy variable name INDODAX_SECRET_KEY as fallback
API_SECRET: str | None = os.getenv("INDODAX_API_SECRET") or os.getenv("INDODAX_SECRET_KEY")

if not API_KEY or not API_SECRET:
    raise RuntimeError(
        "Please set INDODAX_API_KEY and INDODAX_API_SECRET (or INDODAX_SECRET_KEY) in environment or .env file"
    )

INDODAX_API_URL = "https://indodax.com/tapi"

MCP_AUTH_USER: str | None = os.getenv("MCP_AUTH_USER")
MCP_AUTH_PASSWORD: str | None = os.getenv("MCP_AUTH_PASSWORD")

# ---------------------------------------------------------------------------
# Basic Auth ASGI middleware
# ---------------------------------------------------------------------------

class BasicAuthMiddleware:
    """ASGI middleware enforcing HTTP Basic Authentication.

    Skipped automatically when MCP_AUTH_USER / MCP_AUTH_PASSWORD are not set
    (e.g. stdio transport where no env vars are provided).
    """

    def __init__(self, app: ASGIApp, username: str, password: str) -> None:
        self.app = app
        # Pre-encode expected header value once at startup
        creds = f"{username}:{password}".encode()
        self._expected = b"Basic " + base64.b64encode(creds)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            # Pass lifespan and other non-HTTP scopes through unchanged
            await self.app(scope, receive, send)
            return

        # Extract Authorization header (case-insensitive scan)
        headers = dict(scope.get("headers", []))
        auth_header: bytes = headers.get(b"authorization", b"")

        if secrets.compare_digest(auth_header, self._expected):
            await self.app(scope, receive, send)
            return

        # Reject with 401
        body = b'{"error": "Unauthorized", "message": "Valid Basic Auth credentials required"}'
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b'Basic realm="MCP Indodax"'),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _wrap_with_basic_auth(app: Starlette) -> ASGIApp:
    """Wrap a Starlette app with BasicAuthMiddleware if credentials are set."""
    if MCP_AUTH_USER and MCP_AUTH_PASSWORD:
        return BasicAuthMiddleware(app, MCP_AUTH_USER, MCP_AUTH_PASSWORD)
    return app


mcp = FastMCP("indodax")

# ---------------------------------------------------------------------------
# HTTP utility
# ---------------------------------------------------------------------------

async def _private_post(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send a signed POST request to Indodax private endpoint and return JSON.

    The function automatically fills `timestamp` (epoch in ms) when `nonce` is
    not supplied by the caller.
    """
    if "timestamp" not in payload and "nonce" not in payload:
        # millisecond timestamp, compatible with docs default recv window
        from time import time
        payload["timestamp"] = int(time() * 1000)

    body = urlencode(payload)
    sign = hmac.new(API_SECRET.encode(), body.encode(), hashlib.sha512).hexdigest()

    headers = {
        "Key": API_KEY,
        "Sign": sign,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(INDODAX_API_URL, headers=headers, data=body)
        response.raise_for_status()
        return response.json()

# ---------------------------------------------------------------------------
# Public REST API tools (no auth required)
# ---------------------------------------------------------------------------

PUBLIC_API_BASE = "https://indodax.com/api"

async def _public_get(path: str) -> Dict[str, Any]:
    url = f"{PUBLIC_API_BASE}/{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()

@mcp.tool()
async def server_time() -> Dict[str, Any]:
    """Get server time (public endpoint)."""
    return await _public_get("server_time")

@mcp.tool()
async def pairs() -> list[Dict[str, Any]]:
    """Get list of available trading pairs."""
    return await _public_get("pairs")

@mcp.tool()
async def price_increments() -> Dict[str, Any]:
    """Get price increments per pair."""
    return await _public_get("price_increments")

@mcp.tool()
async def summaries() -> Dict[str, Any]:
    """Get summaries for all pairs."""
    return await _public_get("summaries")

@mcp.tool()
async def ticker(pair_id: str | None = None) -> Dict[str, Any]:
    """Get ticker for a pair (default btcidr)."""
    path = f"ticker/{pair_id}" if pair_id else "ticker"
    return await _public_get(path)

@mcp.tool()
async def ticker_all() -> Dict[str, Any]:
    """Get ticker for all pairs."""
    return await _public_get("ticker_all")

@mcp.tool()
async def trades(pair_id: str | None = None) -> list[Dict[str, Any]]:
    """Get recent trades for pair (default btcidr)."""
    path = f"trades/{pair_id}" if pair_id else "trades"
    return await _public_get(path)

# ---------------------------------------------------------------------------
# MCP tools – one per documented method parameter
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_info() -> Dict[str, Any]:
    """Get user balances, server time, addresses etc. Equivalent to `getInfo`."""
    return await _private_post({"method": "getInfo"})


@mcp.tool()
async def trans_history(start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Any]:
    """Fetch transaction history between two dates (YYYY-MM-DD).

    Defaults to the last 7 days when no dates specified (server behaviour).
    """
    payload: Dict[str, Any] = {"method": "transHistory"}
    if start:
        payload["start"] = start
    if end:
        payload["end"] = end
    return await _private_post(payload)


@mcp.tool()
async def trade(pair: str, type: str, price: float, idr: Optional[float] = None, crypto: Optional[float] = None) -> Dict[str, Any]:
    """Create a buy/sell order.

    Args:
        pair: Trading pair, e.g. "btc_idr".
        type: "buy" or "sell".
        price: Price per unit.
        idr: Amount in IDR (for buy orders).
        crypto: Amount in crypto (for sell orders).
    """
    payload: Dict[str, Any] = {
        "method": "trade",
        "pair": pair,
        "type": type,
        "price": price,
    }
    if idr is not None:
        payload["idr"] = idr
    if crypto is not None:
        payload["crypto"] = crypto
    return await _private_post(payload)


@mcp.tool()
async def trade_history(pair: Optional[str] = None, count: int = 100, from_id: Optional[int] = None, end_id: Optional[int] = None, order: str = "desc") -> Dict[str, Any]:
    """Get historical trades.

    Args:
        pair: Optional pair filter.
        count: Max records (default 100).
        from_id: Start ID.
        end_id: End ID.
        order: "asc" or "desc".
    """
    payload: Dict[str, Any] = {
        "method": "tradeHistory",
        "count": count,
        "order": order,
    }
    if pair:
        payload["pair"] = pair
    if from_id is not None:
        payload["from"] = from_id
    if end_id is not None:
        payload["end"] = end_id
    return await _private_post(payload)


@mcp.tool()
async def open_orders(pair: Optional[str] = None) -> Dict[str, Any]:
    """Get open orders. Optionally filter by pair."""
    payload: Dict[str, Any] = {"method": "openOrders"}
    if pair:
        payload["pair"] = pair
    return await _private_post(payload)


@mcp.tool()
async def order_history(pair: Optional[str] = None, count: int = 100, from_id: Optional[int] = None, end_id: Optional[int] = None, order: str = "desc") -> Dict[str, Any]:
    """Fetch order history."""
    payload: Dict[str, Any] = {
        "method": "orderHistory",
        "count": count,
        "order": order,
    }
    if pair:
        payload["pair"] = pair
    if from_id is not None:
        payload["from"] = from_id
    if end_id is not None:
        payload["end"] = end_id
    return await _private_post(payload)


@mcp.tool()
async def get_order(order_id: int) -> Dict[str, Any]:
    """Get order by its numeric ID."""
    return await _private_post({"method": "getOrder", "order_id": order_id})


@mcp.tool()
async def get_order_by_client_order_id(client_order_id: str) -> Dict[str, Any]:
    """Get order by client generated ID."""
    return await _private_post({"method": "getOrderByClientOrderId", "client_order_id": client_order_id})


@mcp.tool()
async def cancel_order(order_id: int) -> Dict[str, Any]:
    """Cancel order by numeric ID."""
    return await _private_post({"method": "cancelOrder", "order_id": order_id})


@mcp.tool()
async def cancel_by_client_order_id(client_order_id: str) -> Dict[str, Any]:
    """Cancel order by client order ID."""
    return await _private_post({"method": "cancelByClientOrderId", "client_order_id": client_order_id})


@mcp.tool()
async def withdraw_fee(currency: str, amount: float, address: str, network: Optional[str] = None) -> Dict[str, Any]:
    """Estimate withdrawal fee.

    Args:
        currency: e.g. "btc".
        amount: Amount of coin.
        address: Destination address.
        network: Optional network code (e.g. "erc20").
    """
    payload: Dict[str, Any] = {
        "method": "withdrawFee",
        "currency": currency,
        "amount": amount,
        "address": address,
    }
    if network:
        payload["network"] = network
    return await _private_post(payload)


@mcp.tool()
async def withdraw_coin(currency: str, amount: float, address: str, network: Optional[str] = None, memo: Optional[str] = None) -> Dict[str, Any]:
    """Perform a crypto withdrawal."""
    payload: Dict[str, Any] = {
        "method": "withdrawCoin",
        "currency": currency,
        "amount": amount,
        "address": address,
    }
    if network:
        payload["network"] = network
    if memo:
        payload["memo"] = memo
    return await _private_post(payload)


@mcp.tool()
async def list_downline() -> Dict[str, Any]:
    """List referral downlines (Partner only)."""
    return await _private_post({"method": "listDownline"})


@mcp.tool()
async def check_downline(username: str) -> Dict[str, Any]:
    """Check whether a username is your downline."""
    return await _private_post({"method": "checkDownline", "username": username})


@mcp.tool()
async def create_voucher(amount: float, description: str | None = None) -> Dict[str, Any]:
    """Create a voucher (Partner only)."""
    payload: Dict[str, Any] = {"method": "createVoucher", "amount": amount}
    if description:
        payload["description"] = description
    return await _private_post(payload)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# HTTP app (used when running with uvicorn)
# ---------------------------------------------------------------------------

# Expose a top-level `app` variable so uvicorn can find it:
#   uvicorn server:app --reload
#
# Basic Auth is applied when MCP_AUTH_USER + MCP_AUTH_PASSWORD are set.
# Example:
#   MCP_AUTH_USER=admin MCP_AUTH_PASSWORD=secret uvicorn server:app
app: ASGIApp = _wrap_with_basic_auth(mcp.streamable_http_app())

# SSE variant (legacy clients):
#   uvicorn server:sse_app
sse_app: ASGIApp = _wrap_with_basic_auth(mcp.sse_app())


if __name__ == "__main__":
    # stdio transport: no network exposure → Basic Auth not needed.
    mcp.run(transport="stdio")
