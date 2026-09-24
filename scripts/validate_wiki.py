from __future__ import annotations

from pathlib import Path
import sys

from lyra.wiki import WikiService, validate_wiki_catalog


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = validate_wiki_catalog(root)
    if errors:
        print("INVALID: wiki catalog")
        for error in errors:
            print(f"- {error}")
        return 1
    service = WikiService(root)
    print(f"VALID: Lyra wiki ({len(service.page_ids)} pages; lexical; read-only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
