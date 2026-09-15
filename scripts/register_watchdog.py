"""Manage Lyra's per-user after-logon watchdog registration."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_NAME = "LyraWatchdog.vbs"


def startup_directory(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    appdata = env.get("APPDATA", "").strip()
    if not appdata:
        raise ValueError("APPDATA is not available")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def launcher_path(environ: dict[str, str] | None = None) -> Path:
    return startup_directory(environ) / LAUNCHER_NAME


def launcher_content(root: Path = ROOT) -> str:
    pythonw = root / "venv" / "Scripts" / "pythonw.exe"
    watchdog = root / "scripts" / "watchdog.py"
    command = f'""{pythonw}"" ""{watchdog}"" --monitor'
    return (
        "Set shell = CreateObject(\"WScript.Shell\")\n"
        f"shell.Run \"{command}\", 0, False\n"
    )


def _hidden_popen_options() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": subprocess.CREATE_NO_WINDOW,
            "startupinfo": startupinfo, "close_fds": True}


def install(root: Path = ROOT, *, environ: dict[str, str] | None = None, start_now: bool = False) -> Path:
    pythonw = root / "venv" / "Scripts" / "pythonw.exe"
    if not pythonw.is_file():
        raise FileNotFoundError(f"Runtime executable not found: {pythonw}")
    target = launcher_path(environ)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(launcher_content(root), encoding="utf-8")
    temporary.replace(target)
    if start_now:
        subprocess.Popen(
            [str(pythonw), str(root / "scripts" / "watchdog.py"), "--monitor"],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_hidden_popen_options(),
        )
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall", "status"))
    parser.add_argument("--start-now", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        target = launcher_path()
        if args.dry_run:
            print(f"DRY-RUN: {args.action} {target}")
            if args.action == "install":
                print(f"DRY-RUN: launch {ROOT / 'scripts' / 'watchdog.py'} --monitor")
            return 0
        if args.action == "install":
            target = install(start_now=args.start_now)
        elif args.action == "uninstall":
            target.unlink(missing_ok=True)
        else:
            print(f"{LAUNCHER_NAME}: {'installed' if target.is_file() else 'not installed'}")
            return 0 if target.is_file() else 1
        print(f"{LAUNCHER_NAME}: {args.action} complete ({target})")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
