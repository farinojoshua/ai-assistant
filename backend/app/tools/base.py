"""Tool contract. One tool = one file = one purpose."""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel

from app.db.company_db import CompanyDbGateway
from app.db.models import User
from app.llm.base import ToolSpec


class ToolContext(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    user: User
    tenant_id: uuid.UUID
    db: CompanyDbGateway


class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    args_model: ClassVar[type[BaseModel]]

    @property
    def spec(self) -> ToolSpec:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=schema,
        )

    def parse_args(self, raw: dict[str, Any]) -> BaseModel:
        return self.args_model.model_validate(raw)

    @abstractmethod
    async def run(self, args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
        """Execute against the company DB. Return a compact JSON-able dict.

        Expected errors (bad args, nothing found) are returned as
        ``{"error": ..., "hint": ...}`` rather than raised, so the model can
        recover within the loop.
        """
