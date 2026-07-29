from __future__ import annotations

import argparse

from lyra.config import settings
from lyra.embeddings import EmbeddingService
from lyra.knowledge_graph import MCPKnowledgeGraphWriter, ObservationService


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Approve a pending observation and write it to Lyra's knowledge graph."
    )
    parser.add_argument("observation_id", type=int, help="Pending observation row id")
    args = parser.parse_args()

    writer = MCPKnowledgeGraphWriter(settings.kg_memory_file_path)
    service = ObservationService(
        embedding_service=EmbeddingService(),
        graph_writer=writer,
    )
    result = service.approve_observation(args.observation_id)
    print(
        f"Approved observation {result['observation_id']}: "
        f"approved={result['approved']} written={result['written']}"
    )


if __name__ == "__main__":
    main()
