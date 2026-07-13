from __future__ import annotations

from lyra.corpus_mcp import CorpusService, MCPToolRouter
from lyra.embeddings import EmbeddingService
from lyra.ingest import IngestPipeline


def build_router() -> MCPToolRouter:
    embedder = EmbeddingService()
    ingest = IngestPipeline(embedding_service=embedder)
    service = CorpusService(embedding_service=embedder, ingest_pipeline=ingest)
    return MCPToolRouter(service)


def run_stdio_server() -> None:
    """
    Optional FastMCP runtime adapter.
    Tests use MCPToolRouter directly as a client/server contract shim.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover - runtime path only
        raise RuntimeError(
            "FastMCP runtime is unavailable. Install the 'mcp' package to run the stdio server."
        ) from exc

    router = build_router()
    app = FastMCP("lyra-corpus")

    @app.tool()
    def search_corpus(query: str, limit: int = 5):
        return router.call_tool("search_corpus", {"query": query, "limit": limit})

    @app.tool()
    def add_source(source: str, source_type: str = "url", title: str | None = None):
        return router.call_tool(
            "add_source",
            {"source": source, "source_type": source_type, "title": title},
        )

    @app.tool()
    def search_memories(query: str, limit: int = 5, approved_only: bool = True):
        return router.call_tool(
            "search_memories",
            {"query": query, "limit": limit, "approved_only": approved_only},
        )

    @app.tool()
    def propose_memory(
        content: str,
        memory_type: str = "fact",
        salience: int = 5,
        metadata: dict | None = None,
    ):
        return router.call_tool(
            "propose_memory",
            {
                "content": content,
                "memory_type": memory_type,
                "salience": salience,
                "metadata": metadata or {},
            },
        )

    app.run()


if __name__ == "__main__":  # pragma: no cover - runtime entrypoint
    run_stdio_server()
