from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TextEvent:
    text: str


@dataclass(slots=True)
class ToolEvent:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ErrorEvent:
    message: str


Event = TextEvent | ToolEvent | ErrorEvent
