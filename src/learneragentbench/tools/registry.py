"""Tool registry: typed parameter models, permission defaults, idempotency rules, JSON schemas."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..schema import LABModel, PermissionLevel

ToolFn = Callable[..., Any]  # fn(ctx: ToolContext, params: BaseModel) -> Any


class ToolSpec(LABModel):
    name: str
    description: str
    category: Literal["read", "write", "meta"]
    params_model: type[BaseModel]
    default_permission: PermissionLevel = PermissionLevel.ALLOWED
    mutates: bool = False
    idempotency_fields: list[str] = Field(default_factory=list)
    requires_contact_role_scope: bool = False

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    def json_schema(self) -> dict[str, Any]:
        """OpenAI-style function definition."""
        schema = self.params_model.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": schema},
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._fns: dict[str, ToolFn] = {}

    def register(self, spec: ToolSpec) -> Callable[[ToolFn], ToolFn]:
        def deco(fn: ToolFn) -> ToolFn:
            if spec.name in self._specs:
                raise ValueError(f"tool {spec.name} already registered")
            self._specs[spec.name] = spec
            self._fns[spec.name] = fn
            return fn
        return deco

    def spec(self, name: str) -> ToolSpec:
        if name not in self._specs:
            raise KeyError(name)
        return self._specs[name]

    def fn(self, name: str) -> ToolFn:
        return self._fns[name]

    def names(self) -> list[str]:
        return sorted(self._specs)

    def specs(self, names: list[str] | None = None) -> list[ToolSpec]:
        if names is None:
            return [self._specs[n] for n in self.names()]
        return [self._specs[n] for n in names if n in self._specs]

    def schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        return [s.json_schema() for s in self.specs(names)]

    def __contains__(self, name: str) -> bool:
        return name in self._specs
