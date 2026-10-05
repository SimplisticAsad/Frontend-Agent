"""Shared mutable state of one pipeline run (explicit object, no globals)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.artifacts.repository import ArtifactRepository
from app.config.settings import Limits
from app.domain.models.graph import GraphPackage
from app.domain.models.state import PipelineStatus
from app.domain.specifications.specs import ComponentSpec, FileRecord, ScreenSpec, TestRecord
from app.execution.browser_runner import BrowserRunner
from app.execution.command_runner import CommandRunner
from app.generation.file_generator import FileWorkspace
from app.generation.project_generator import ProjectGenerator
from app.generation.symbols import ApiBinding
from app.graph.context_builder import ContextBuilder
from app.llm.base import LLMProvider
from app.observability import EventLog
from app.pipeline.stage import StageRunner


@dataclass
class RunContext:
    project_dir: Path
    workspace: FileWorkspace
    artifacts: ArtifactRepository
    events: EventLog
    llm: LLMProvider
    runner: StageRunner
    commands: CommandRunner
    browser: BrowserRunner
    limits: Limits
    status: PipelineStatus = field(default_factory=PipelineStatus)
    graph: GraphPackage | None = None
    contexts: ContextBuilder | None = None
    generator: ProjectGenerator | None = None
    analysis: dict | None = None
    architecture: dict | None = None
    design_system: dict | None = None
    api_plan: dict | None = None
    state_plan: dict | None = None
    screen_specs: list[ScreenSpec] = field(default_factory=list)
    component_specs: list[ComponentSpec] = field(default_factory=list)
    bindings: list[ApiBinding] = field(default_factory=list)
    files: dict[str, FileRecord] = field(default_factory=dict)
    tests: list[TestRecord] = field(default_factory=list)
    attempts: dict[str, int] = field(default_factory=lambda: {"build": 0, "functional": 0, "visual": 0})
    results: dict[str, Any] = field(default_factory=dict)  # typescript/lint/build/unit_tests/e2e_tests/visual_tests/accessibility_tests
    warnings: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    incremental: bool = False
    dirty: bool = False  # files changed since the last full validation
    final_failure: object | None = None
    skip_install: bool = False

    @property
    def g(self) -> GraphPackage:
        assert self.graph is not None, "graph not loaded"
        return self.graph

    def add_files(self, records: list[FileRecord]) -> None:
        for r in records:
            prev = self.files.get(r.path)
            r.version = (prev.version + 1) if prev else r.version
            self.files[r.path] = r

    def screen_spec(self, ref: str) -> ScreenSpec:
        return next(s for s in self.screen_specs if s.screen_ref == ref)

    def component_spec(self, ref: str) -> ComponentSpec:
        return next(c for c in self.component_specs if c.component_ref == ref)
