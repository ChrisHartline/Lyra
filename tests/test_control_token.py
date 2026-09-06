from __future__ import annotations

from pathlib import Path

from scripts.configure_control_token import KEY, configure


def test_control_token_configuration_is_idempotent_and_never_empty():
    target = Path("data/test_tmp/control_token/.env")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("EXISTING=value\n", encoding="utf-8")

    assert configure(target) is True
    first = target.read_text(encoding="utf-8")
    assert "EXISTING=value" in first
    assert f"{KEY}=" in first
    assert first.split(f"{KEY}=", 1)[1].strip()

    assert configure(target) is False
    assert target.read_text(encoding="utf-8") == first

    assert configure(target, rotate=True) is True
    assert target.read_text(encoding="utf-8") != first
