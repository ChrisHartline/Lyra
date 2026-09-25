from __future__ import annotations

from pathlib import Path
import sys

from lyra.scene_media import SceneDirector, TRIGGERS
from lyra.visual_assets import load_catalog


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors: list[str] = []
    director = SceneDirector(root=root / "data" / "test_tmp" / "w94_validator")
    policy = director.get_policy()
    if policy.enabled or policy.automatic_enabled:
        errors.append("scene media must default disabled")
    if len(TRIGGERS) != 7 or "explicit" not in TRIGGERS:
        errors.append("scene trigger contract is incomplete")
    catalog = load_catalog()
    externally_eligible = [
        asset for asset in catalog.get("assets", [])
        if asset.get("approved_for_external_renderer") is True
    ]
    if externally_eligible:
        errors.append("W9.4 must not silently enable current assets for external rendering")
    app_js = (root / "lyra" / "web_static" / "app.js").read_text(encoding="utf-8")
    if "item.event === 'media'" not in app_js or "non-canonical" not in app_js:
        errors.append("web client lacks labeled media-event handling")
    if errors:
        print("INVALID: scene media")
        for error in errors:
            print(f"- {error}")
        return 1
    print("VALID: scene media (disabled by default; 7 triggers; 0 external assets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
