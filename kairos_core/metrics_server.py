"""aiohttp /metrics endpoint for Prometheus scraping."""
from __future__ import annotations

import asyncio

from aiohttp import web

from .metrics import metrics_text


async def metrics_handler(request: web.Request) -> web.Response:
    """Return Prometheus metrics in text format."""
    return web.Response(body=metrics_text(), content_type="text/plain; version=0.0.4")


def create_metrics_app(port: int = 9100) -> web.Application:
    """Create a minimal aiohttp app serving /metrics at the given port."""
    app = web.Application()
    app.router.add_get("/metrics", metrics_handler)
    return app


async def run_metrics_server(port: int = 9100) -> None:
    """Run the metrics HTTP server in the background."""
    app = create_metrics_app(port)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    # Keep the server running indefinitely; parent service handles shutdown.
    await asyncio.Event().wait()
