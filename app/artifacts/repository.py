"""Artifact persistence: all JSON the pipeline emits lives under <project>/frontend-artifacts/."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.domain.specifications.specs import ComponentSpec, FileRecord, ScreenSpec, TestRecord


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    if isinstance(obj, list):
        return [_jsonable(o) for o in obj]
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    return obj


class ArtifactRepository:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, rel: str) -> Path:
        return self.root / rel

    def save(self, rel: str, data: Any) -> Path:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_jsonable(data), indent=2, sort_keys=False, default=str) + "\n", encoding="utf-8")
        return p

    def load(self, rel: str, default: Any = None) -> Any:
        p = self.path(rel)
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))

    def exists(self, rel: str) -> bool:
        return self.path(rel).exists()

    # ---- typed helpers ----
    def save_screen_specs(self, specs: list[ScreenSpec]) -> None:
        for s in specs:
            self.save(f"screen_specs/{s.screen_ref}.json", s)

    def load_screen_specs(self) -> list[ScreenSpec]:
        d = self.root / "screen_specs"
        return [ScreenSpec(**json.loads(p.read_text())) for p in sorted(d.glob("*.json"))] if d.exists() else []

    def save_component_specs(self, specs: list[ComponentSpec]) -> None:
        for s in specs:
            self.save(f"component_specs/{s.name}.json", s)

    def load_component_specs(self) -> list[ComponentSpec]:
        d = self.root / "component_specs"
        return [ComponentSpec(**json.loads(p.read_text())) for p in sorted(d.glob("*.json"))] if d.exists() else []

    def save_file_manifest(self, files: list[FileRecord]) -> None:
        self.save("file_manifest.json", {"files": sorted((f.model_dump() for f in files), key=lambda f: f["path"])})

    def load_file_manifest(self) -> list[FileRecord]:
        data = self.load("file_manifest.json", {"files": []})
        return [FileRecord(**f) for f in data["files"]]

    def save_test_manifest(self, tests: list[TestRecord]) -> None:
        self.save("test_manifest.json", {"tests": sorted((t.model_dump() for t in tests), key=lambda t: t["id"])})

    def load_test_manifest(self) -> list[TestRecord]:
        data = self.load("test_manifest.json", {"tests": []})
        return [TestRecord(**t) for t in data["tests"]]
