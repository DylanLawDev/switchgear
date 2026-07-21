import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

from switchgear.tools.base import Tool

MAX_BODY = 500_000

BLOCKED_HOSTNAMES = {"metadata.google.internal", "metadata.goog"}
BLOCKED_HEADER_NAMES = {"metadata-flavor", "authorization"}


async def _is_blocked_host(host: str) -> bool:
    if not host:
        return False
    if host.lower() in BLOCKED_HOSTNAMES:
        return True
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except socket.gaierror:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr.split("%")[0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    return False


async def _http_fetch(url: str, method: str = "GET", body: dict | None = None,
                      headers: dict | None = None) -> dict:
    host = urlsplit(url).hostname or ""
    if await _is_blocked_host(host):
        return {"error": "blocked host"}
    if headers:
        headers = {k: v for k, v in headers.items()
                   if k.lower() not in BLOCKED_HEADER_NAMES}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.request(method, url, json=body, headers=headers)
    ctype = resp.headers.get("content-type", "")
    text = resp.text
    truncated = len(text) > MAX_BODY
    if "json" in ctype and not truncated:
        payload = resp.json()
    else:
        payload = text[:MAX_BODY]
    result = {"status": resp.status_code, "body": payload}
    if truncated:
        result["truncated"] = True
    return result


def make_http_fetch_tool() -> Tool:
    return Tool(
        name="http_fetch",
        description="Fetch a URL over HTTP. Returns status and body (JSON-decoded when possible).",
        parameters={"type": "object", "properties": {
            "url": {"type": "string"},
            "method": {"type": "string", "enum": ["GET", "POST"], "default": "GET"},
            "body": {"type": "object"},
            "headers": {"type": "object"}},
            "required": ["url"]},
        handler=_http_fetch,
    )
