"""Machine-readable frontend specifications (what the planning stages produce)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ScreenSpec(BaseModel):
    screen_ref: str
    route: str
    layout: str  # public | authenticated
    kind: str
    feature: str
    page_component: str
    page_path: str
    components: list[str] = Field(default_factory=list)  # graph component refs
    data_sources: list[str] = Field(default_factory=list)  # graph api refs
    actions: list[str] = Field(default_factory=list)  # graph workflow refs
    permissions: list[str] = Field(default_factory=list)  # graph permission refs
    entity_refs: list[str] = Field(default_factory=list)
    states: list[str] = Field(default_factory=list)  # loading | empty | error | success
    responsive: dict[str, str] = Field(default_factory=dict)  # desktop/tablet/mobile behaviour
    notes: str = ""


class ComponentSpec(BaseModel):
    component_ref: str | None  # None for purely presentational helpers
    name: str
    kind: str
    scope: str  # shared | feature
    feature: str | None = None
    path: str
    props: dict[str, str] = Field(default_factory=dict)
    primitives: list[str] = Field(default_factory=list)
    entity_refs: list[str] = Field(default_factory=list)
    workflow_refs: list[str] = Field(default_factory=list)
    api_refs: list[str] = Field(default_factory=list)
    states: list[str] = Field(default_factory=list)
    accessibility: list[str] = Field(default_factory=list)
    notes: str = ""


class FileRecord(BaseModel):
    path: str
    purpose: str
    source_refs: list[str] = Field(default_factory=list)
    generator: str = "llm"  # llm | template | graph
    version: int = 1
    digest: str = ""


class TestRecord(BaseModel):
    id: str
    type: str  # unit | integration | e2e | visual
    path: str
    source_refs: list[str] = Field(default_factory=list)
    description: str = ""
