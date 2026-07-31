"""Stdio MCP server: gated lyra-memory surface (D4.1)."""

from __future__ import annotations

from lyra.kg_gatekeeper import build_gatekeeper_router


def run_stdio_server() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover - runtime path only
        raise RuntimeError(
            "FastMCP runtime is unavailable. Install the 'mcp' package to run the gatekeeper."
        ) from exc

    router = build_gatekeeper_router()
    app = FastMCP("lyra-memory")

    @app.tool()
    def search_nodes(query: str):
        return router.call_tool("search_nodes", {"query": query})

    @app.tool()
    def read_graph():
        return router.call_tool("read_graph", {})

    @app.tool()
    def open_nodes(names: list[str]):
        return router.call_tool("open_nodes", {"names": names})

    @app.tool()
    def propose_observation(
        text: str,
        entity_name: str = "Christopher",
        entity_type: str = "person",
        source_type: str = "session",
    ):
        return router.call_tool(
            "propose_observation",
            {
                "text": text,
                "entity_name": entity_name,
                "entity_type": entity_type,
                "source_type": source_type,
            },
        )

    @app.tool()
    def list_pending_observations(limit: int = 20):
        return router.call_tool("list_pending_observations", {"limit": limit})

    app.run()


if __name__ == "__main__":  # pragma: no cover
    run_stdio_server()
