from __future__ import annotations

import subprocess
from pathlib import Path
from lyra.db import apply_schema


def main() -> None:
    compose_file = Path("docker-compose.yml")
    if not compose_file.exists():
        raise FileNotFoundError("docker-compose.yml not found")
    subprocess.run(["docker", "compose", "up", "-d"], check=True)
    apply_schema("db/schema.sql")
    print("Database initialized with pgvector schema.")


if __name__ == "__main__":
    main()
