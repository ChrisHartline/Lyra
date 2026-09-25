"""Provider-neutral events emitted by Lyra's standalone runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class EventKind(str, Enum):
    TEXT = "text"
    TOOL = "tool"
    SUBAGENT = "subagent"
    EMOTION = "emotion"
    MEDIA = "media"
    COMPLETION = "completion"
    ERROR = "error"


@dataclass(frozen=True)
class RuntimeEvent:
    kind: EventKind
    text: str | None = None
    name: str | None = None
    call_id: str | None = None
    arguments: Mapping[str, Any] | None = None
    data: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def text_delta(cls, text: str) -> "RuntimeEvent":
        return cls(EventKind.TEXT, text=text)

    @classmethod
    def tool_call(
        cls,
        *,
        name: str,
        call_id: str,
        arguments: Mapping[str, Any],
    ) -> "RuntimeEvent":
        return cls(
            EventKind.TOOL,
            name=name,
            call_id=call_id,
            arguments=arguments,
        )

    @classmethod
    def subagent(cls, name: str, **data: Any) -> "RuntimeEvent":
        return cls(EventKind.SUBAGENT, name=name, data=data)

    @classmethod
    def emotion(cls, name: str, **data: Any) -> "RuntimeEvent":
        return cls(EventKind.EMOTION, name=name, data=data)

    @classmethod
    def media(cls, name: str, **data: Any) -> "RuntimeEvent":
        return cls(EventKind.MEDIA, name=name, data=data)

    @classmethod
    def completion(cls, reason: str | None, **data: Any) -> "RuntimeEvent":
        return cls(EventKind.COMPLETION, data={"reason": reason, **data})

    @classmethod
    def error(cls, code: str, message: str) -> "RuntimeEvent":
        return cls(EventKind.ERROR, text=message, data={"code": code})
