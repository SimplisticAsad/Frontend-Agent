"""Tiny helpers for emitting TypeScript source deterministically."""
from __future__ import annotations

from app.generation.symbols import import_path


class Imports:
    def __init__(self, from_path: str):
        self.from_path = from_path
        self._mods: dict[str, dict[str, bool]] = {}  # specifier -> {name: is_type}

    def add(self, module: str, *names: str, type: bool = False) -> None:
        spec = import_path(self.from_path, module) if module.startswith(("src/", "tests/")) else module
        bucket = self._mods.setdefault(spec, {})
        for n in names:
            bucket[n] = bucket.get(n, True) and type  # a value import wins over a type import

    def render(self) -> str:
        lines = []
        raw = sorted(m for m in self._mods if not m.startswith("."))
        rel = sorted(m for m in self._mods if m.startswith("."))
        for spec in raw + rel:
            names = self._mods[spec]
            if not names:
                continue
            if all(names.values()):
                lines.append(f"import type {{ {', '.join(sorted(names))} }} from '{spec}';")
            else:
                parts = sorted(names, key=lambda n: n.lower())
                parts = [f"type {n}" if names[n] else n for n in parts]
                lines.append(f"import {{ {', '.join(parts)} }} from '{spec}';")
        return "\n".join(lines)


def lower_first(s: str) -> str:
    return s[:1].lower() + s[1:]


def jsx_text(s: str) -> str:
    return s.replace("{", "&#123;").replace("}", "&#125;")


def q(s: str) -> str:
    """Single-quoted TS string literal."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"
