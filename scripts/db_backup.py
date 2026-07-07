from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess
from lyra.config import settings


def main() -> None:
    backup_dir = Path("backups")
    backup_dir.mkdir(exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out = backup_dir / f"lyra_{ts}.sql"
    subprocess.run(
        [
            "pg_dump",
            "-h", settings.db_host,
            "-p", str(settings.db_port),
            "-U", settings.db_user,
            "-d", settings.db_name,
            "-f", str(out),
        ],
        check=True,
    )
    print(f"Backup written: {out}")


if __name__ == "__main__":
    main()
