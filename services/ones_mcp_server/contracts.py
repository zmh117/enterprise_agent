from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SERVER_CODE = "ones-mcp"
SERVER_VERSION = "0.1.0"
SEARCH_SCOPE = "ones.work_items.search"


class OnesWorkItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    number: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=500)
    type: Literal["demand", "task", "defect"]


class OnesWorkItemSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: tuple[OnesWorkItem, ...] = Field(max_length=50)
    total: int = Field(ge=0)
    truncated: bool
    untrusted_data: bool = True
