"""Idempotent NSSM management for Lyra's loopback workstation service."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Sequence

from lyra.service import SERVICE_NAME, nssm_install_commands, resolve_nssm, run_commands


ROOT = Path(__file__).resolve().parents[1]


def _render(command: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(command))


def _installed(nssm: Path, service_name: str) -> bool:
    result = subprocess.run(
        [str(nssm), "status", service_name],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def command_plan(action: str, nssm: Path, service_name: str) -> list[list[str]]:
    if action == "install":
        commands = nssm_install_commands(nssm, ROOT, service_name=service_name)
        return commands + [[str(nssm), "start", service_name]]
    if action == "uninstall":
        return [
            [str(nssm), "stop", service_name],
            [str(nssm), "remove", service_name, "confirm"],
        ]
    return [[str(nssm), "status", service_name]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall", "status"))
    parser.add_argument("--nssm", help="Explicit path to nssm.exe")
    parser.add_argument("--name", default=SERVICE_NAME)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        nssm = resolve_nssm(
            args.nssm,
            require_exists=not (args.dry_run and bool(args.nssm)),
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 2

    installed = (
        False
        if args.dry_run and not nssm.is_file()
        else _installed(nssm, args.name)
    )
    if args.action == "status":
        print(f"{args.name}: {'installed' if installed else 'not installed'}")
        return 0 if installed else 1
    if args.action == "uninstall" and not installed:
        print(f"{args.name}: already absent")
        return 0

    commands = command_plan(args.action, nssm, args.name)
    if args.action == "install" and installed:
        commands = [command for command in commands if command[1] != "install"]
    if args.dry_run:
        for command in commands:
            print(f"DRY-RUN: {_render(command)}")
        return 0

    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    run_commands(commands)
    print(f"{args.name}: {args.action} complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
