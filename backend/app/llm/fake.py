"""In-memory provider for tests. Returns a predefined script of responses."""
from __future__ import annotations

from app.llm.base import LLMProvider, LLMResponse, Message, ToolSpec


class FakeProvider(LLMProvider):
    def __init__(self, script: list[LLMResponse | Exception]) -> None:
        self._script = list(script)
        self._i = 0
        # every (messages, tools) pair passed to chat(), for assertions
        self.calls: list[tuple[list[Message], list[ToolSpec]]] = []

    @property
    def recorded_messages(self) -> list[Message]:
        """Messages from the most recent chat() call."""
        return self.calls[-1][0] if self.calls else []

    async def chat(
        self, messages: list[Message], tools: list[ToolSpec]
    ) -> LLMResponse:
        self.calls.append(([m.model_copy(deep=True) for m in messages], tools))
        if self._i >= len(self._script):
            raise AssertionError("FakeProvider script exhausted")
        item = self._script[self._i]
        self._i += 1
        if isinstance(item, Exception):
            raise item
        return item
