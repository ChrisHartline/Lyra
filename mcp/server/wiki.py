from __future__ import annotations

from lyra.knowledge_routing import ROUTES, route_knowledge
from lyra.wiki import WikiService, WikiToolRouter


def build_router() -> WikiToolRouter:
    return WikiToolRouter(WikiService())


def run_stdio_server() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover - runtime path only
        raise RuntimeError(
            "FastMCP runtime is unavailable. Install the 'mcp' package to run the stdio server."
        ) from exc

    router = build_router()
    app = FastMCP("lyra-wiki")

    @app.tool()
    def wiki_search(query: str, limit: int = 5, bucket: str | None = None):
        return router.call_tool(
            "wiki_search", {"query": query, "limit": limit, "bucket": bucket}
        )

    @app.tool()
    def wiki_read(page_id: str):
        return router.call_tool("wiki_read", {"page_id": page_id})

    @app.tool()
    def knowledge_route(information_type: str):
        return route_knowledge(information_type)

    app.run()


if __name__ == "__main__":  # pragma: no cover - runtime entrypoint
    run_stdio_server()
