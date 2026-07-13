from __future__ import annotations

import argparse

from lyra.embeddings import EmbeddingService
from lyra.memory import MemoryService


def main() -> None:
    parser = argparse.ArgumentParser(description="Approve a pending memory candidate.")
    parser.add_argument("memory_id", type=int, help="Memory row id to approve")
    args = parser.parse_args()

    service = MemoryService(embedding_service=EmbeddingService())
    result = service.approve_memory(args.memory_id)
    print(f"Approved memory {result['memory_id']}: approved={result['approved']}")


if __name__ == "__main__":
    main()
