"""Idempotently create and select the safe web destination for daily rituals."""

from __future__ import annotations

from lyra.away import AwayModeService
from lyra.briefings import BriefingService
from lyra.rituals import RitualService
from lyra.sessions import SessionService


def main() -> None:
    sessions = SessionService()
    matches = [
        item for item in sessions.list_sessions()
        if item["name"].strip().casefold() == "command deck"
    ]
    if matches:
        session = matches[0]
        if session["context_scope"] != "general":
            raise SystemExit(
                "Existing Command Deck is not general; correct it locally before targeting."
            )
    else:
        session = sessions.create_session("Command Deck", context_scope="general")

    rituals = RitualService(BriefingService(""), AwayModeService())
    current = rituals.get_policy()
    if current.channel != "web" and (
        current.morning_enabled or current.evening_enabled
    ):
        raise SystemExit(
            "Rituals are enabled on another channel; disable them before switching."
        )
    policy = rituals.set_policy(
        channel="web", target_session_id=session["session_id"]
    )
    print(
        f"Command Deck ready: session={session['session_id']}, "
        f"scope={session['context_scope']}, channel={policy.channel}, "
        f"morning_enabled={policy.morning_enabled}, "
        f"evening_enabled={policy.evening_enabled}"
    )


if __name__ == "__main__":
    main()
