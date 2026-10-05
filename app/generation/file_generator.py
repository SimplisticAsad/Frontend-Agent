"""Sandboxed workspace for the generated frontend project (spec 53).

All writes go through `FileWorkspace`. Paths proposed by the LLM must pass `check_llm_path`.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath

from app.domain.models.errors import SafetyError

LLM_WRITABLE_ROOTS = ("src", "tests")
LLM_WRITABLE_EXT = {".ts", ".tsx", ".css", ".json", ".md", ".svg"}
MAX_FILE_BYTES = 400_000
_BAD_SEGMENT = re.compile(r"^(\.|node_modules$)")


class FileWorkspace:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, rel: str) -> Path:
        pp = PurePosixPath(rel)
        if pp.is_absolute() or ".." in pp.parts or not pp.parts or "\\" in rel or "\x00" in rel:
            raise SafetyError(f"Unsafe path rejected: {rel!r}")
        if any(_BAD_SEGMENT.match(part) for part in pp.parts):
            raise SafetyError(f"Hidden or dependency path rejected: {rel!r}")
        target = (self.root / rel).resolve()
        if self.root != target and self.root not in target.parents:
            raise SafetyError(f"Path escapes the workspace: {rel!r}")
        return target

    def check_llm_path(self, rel: str) -> None:
        self._resolve(rel)
        pp = PurePosixPath(rel)
        if pp.parts[0] not in LLM_WRITABLE_ROOTS:
            raise SafetyError(f"Generated code may only be written under {LLM_WRITABLE_ROOTS}: {rel!r}")
        if pp.suffix not in LLM_WRITABLE_EXT:
            raise SafetyError(f"File type {pp.suffix!r} not allowed: {rel!r}")

    def write(self, rel: str, content: str, *, from_llm: bool = False) -> Path:
        if from_llm:
            self.check_llm_path(rel)
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise SafetyError(f"File too large: {rel!r}")
        target = self._resolve(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
        return target

    def read(self, rel: str) -> str:
        return self._resolve(rel).read_text(encoding="utf-8")

    def exists(self, rel: str) -> bool:
        return self._resolve(rel).exists()

    def delete(self, rel: str) -> None:
        t = self._resolve(rel)
        if t.is_file():
            t.unlink()

    def list_files(self, subdir: str = ".") -> list[str]:
        base = self._resolve(subdir) if subdir != "." else self.root
        out = []
        for p in sorted(base.rglob("*")):
            if p.is_file() and "node_modules" not in p.parts and "dist" not in p.parts and "test-results" not in p.parts:
                out.append(p.relative_to(self.root).as_posix())
        return out

    @staticmethod
    def digest(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
