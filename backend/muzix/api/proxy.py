"""Relaying remote audio through Muzix (same origin: the visualizer can read it,
and http:// streams work on an https:// page)."""

from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from .. import __version__

UA = f"Muzix/{__version__}"
PASS_HEADERS = ("content-type", "content-length", "content-range", "accept-ranges", "last-modified", "etag")


def check_url(url: str):
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise HTTPException(400, "Only http(s) addresses can be played")


async def relay(url: str, request: Request, extra_headers: dict | None = None):
    check_url(url)
    headers = {"User-Agent": UA, **(extra_headers or {})}
    if "range" in request.headers:
        headers["Range"] = request.headers["range"]
    client = httpx.AsyncClient(timeout=httpx.Timeout(30, read=None), follow_redirects=True)
    try:
        upstream = await client.send(client.build_request("GET", url, headers=headers), stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        raise HTTPException(502, f"Couldn't reach the stream: {e}")
    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(502, f"The server answered {upstream.status_code}")

    async def body():
        try:
            async for chunk in upstream.aiter_raw(64 * 1024):
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    out = {k: v for k, v in upstream.headers.items() if k.lower() in PASS_HEADERS}
    out["Cache-Control"] = "no-store"
    return StreamingResponse(body(), status_code=upstream.status_code, headers=out)
