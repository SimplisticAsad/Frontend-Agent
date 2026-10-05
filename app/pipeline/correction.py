"""Correction service (spec 40-43): turns a classified failure into a bounded, guarded code change.

Guard rails
 * only LLM-generated files may be edited (graph-derived contracts and templates are read-only);
 * every change is re-checked against the graph structure; a change that drops a required field, trigger,
   state, route or test is reverted and reported (corrections must not rewrite requirements);
 * if the model says the *graph* is inconsistent it must say GRAPH_CONFLICT - nothing is edited.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain.models.errors import ErrorKind, Issue
from app.domain.models.naming import slug
from app.pipeline.context import RunContext
from app.pipeline.failures import Failure
from app.validation.frontend_validation import check_generated_source, verify_structure

MAX_FILES = 10
MAX_TOTAL_CHARS = 90_000
DECISIONS = {"fix_implementation", "graph_conflict"}


@dataclass
class CorrectionResult:
    decision: str = "fix_implementation"
    explanation: str = ""
    applied: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)  # reasons
    graph_conflict: dict | None = None

    @property
    def changed(self) -> bool:
        return bool(self.applied)


def _count(rx: str, text: str) -> int:
    return len(re.findall(rx, text))


class CorrectionService:
    def __init__(self, ctx: RunContext):
        self.ctx = ctx

    # ------------------------------------------------------------------ file selection
    def editable(self) -> set[str]:
        return {p for p, r in self.ctx.files.items() if r.generator == "llm" and self.ctx.workspace.exists(p)}

    def refs_for_failure(self, f: Failure) -> set[str]:
        refs = set(f.refs)
        for path in f.files:  # a failing test file implicates what it tests
            refs.update(next((t.source_refs for t in self.ctx.tests if t.path == path), []))
        for t in f.tests:
            for rec in self.ctx.tests:
                if rec.path.split("/")[-1] == str(t.get("file", "")).split("/")[-1] and t.get("file"):
                    refs.update(rec.source_refs)
        for i in f.issues:
            if i.get("screen"):
                refs.add(i["screen"])
        return refs

    def select_files(self, f: Failure) -> list[str]:
        edit = self.editable()
        chosen: list[str] = [p for p in f.files if p in edit]
        refs = self.refs_for_failure(f)
        for ref in refs:
            if ref.startswith("screen."):
                spec = next((s for s in self.ctx.screen_specs if s.screen_ref == ref), None)
                if spec:
                    for p in [spec.page_path] + [c.path for c in self.ctx.component_specs if c.component_ref in spec.components]:
                        if p in edit and p not in chosen:
                            chosen.append(p)
        for p, rec in self.ctx.files.items():
            if p in edit and p not in chosen and not p.startswith("tests/") and refs & set(rec.source_refs) and rec.source_refs and len(chosen) < MAX_FILES:
                chosen.append(p)
        out, total = [], 0
        for p in chosen:
            n = len(self.ctx.workspace.read(p))
            if out and (len(out) >= MAX_FILES or total + n > MAX_TOTAL_CHARS):
                continue
            out.append(p)
            total += n
        return out

    # ------------------------------------------------------------------ context
    def context(self, f: Failure, paths: list[str]) -> dict:
        ctx = self.ctx
        refs: set[str] = set(self.refs_for_failure(f))
        for p in paths:
            refs.update(ctx.files[p].source_refs)
        graph_refs = [r for r in refs if ctx.g.has(r)]
        c = {
            **ctx.contexts.base(),
            "failure": f.to_dict(),
            "files": [{"path": p, "source_refs": ctx.files[p].source_refs, "content": ctx.workspace.read(p)} for p in paths],
            "graph": ctx.contexts.for_refs(graph_refs[:40]),
            "attempt": ctx.attempts,
        }
        if f.kind in (ErrorKind.VISUAL_ERROR,):
            c["design_system_summary"] = ctx.contexts.design_system and {"colors": ctx.design_system["colors"], "responsive": ctx.design_system["responsive"], "breakpoints": ctx.design_system["breakpoints"]}
            c["screen_specs"] = [s.model_dump() for s in ctx.screen_specs if s.screen_ref in refs]
        return c

    # ------------------------------------------------------------------ main entry
    def correct(self, f: Failure) -> CorrectionResult:
        ctx = self.ctx
        paths = self.select_files(f)
        if not paths:
            return CorrectionResult(rejected=["no editable generated file is implicated by this failure"])
        base_ctx = self.context(f, paths)
        offered = set(paths)

        def validate_fix(out: object) -> list[str]:
            if not isinstance(out, dict):
                return ["output must be a JSON object"]
            p: list[str] = []
            if out.get("decision") not in DECISIONS:
                p.append(f"decision must be one of {sorted(DECISIONS)}")
            if out.get("decision") == "graph_conflict":
                gc = out.get("graph_conflict")
                if not isinstance(gc, dict) or not gc.get("description"):
                    p.append("graph_conflict needs {description, refs}")
                return p
            for fl in out.get("files", []):
                if not isinstance(fl, dict) or fl.get("path") not in offered:
                    p.append(f"file {fl.get('path') if isinstance(fl, dict) else fl!r} was not offered for editing (offered: {sorted(offered)})")
                elif not isinstance(fl.get("content"), str):
                    p.append(f"{fl['path']}: content must be a string")
                else:
                    p += check_generated_source(fl["path"], fl["content"])
            return p

        if f.kind in (ErrorKind.FUNCTIONAL_TEST_ERROR, ErrorKind.RUNTIME_ERROR, ErrorKind.NETWORK_ERROR, ErrorKind.API_CONTRACT_ERROR, ErrorKind.ACCESSIBILITY_ERROR) and f.step == "e2e":
            def validate_analysis(out: object) -> list[str]:
                if not isinstance(out, dict) or out.get("decision") not in DECISIONS:
                    return [f"decision must be one of {sorted(DECISIONS)}"]
                bad = set(out.get("files_to_change", [])) - offered
                return [f"files_to_change contains files that were not offered: {sorted(bad)}"] if bad else []

            analysis = ctx.runner.call("browser_error_analysis", base_ctx, validate_analysis, unit=f.step)
            if analysis["decision"] == "graph_conflict":
                return CorrectionResult("graph_conflict", analysis.get("root_cause", ""), graph_conflict=analysis.get("graph_conflict") or {"description": analysis.get("root_cause", ""), "refs": f.refs})
            fix_ctx = {**base_ctx, "analysis": analysis}
            out = ctx.runner.call("correction", fix_ctx, validate_fix, unit=f.step)
        elif f.kind == ErrorKind.VISUAL_ERROR:
            out = ctx.runner.call("correction", base_ctx, validate_fix, unit=f.step)
        else:
            out = ctx.runner.call("build_error_correction", base_ctx, validate_fix, unit=f.step)
        if out["decision"] == "graph_conflict":
            return CorrectionResult("graph_conflict", str(out.get("explanation", "")), graph_conflict=out["graph_conflict"])
        return self.apply(out.get("files", []), str(out.get("explanation", "")))

    # ------------------------------------------------------------------ guarded apply
    def apply(self, files: list[dict], explanation: str) -> CorrectionResult:
        ctx = self.ctx
        ws = ctx.workspace
        res = CorrectionResult(explanation=explanation)
        changes = [(fl["path"], fl["content"]) for fl in files if ws.read(fl["path"]).strip() != fl["content"].strip()]
        if not changes:
            res.rejected.append("the proposed files are identical to the current ones")
            return res
        before = {i.code + i.message for i in self._structure()}
        old = {p: ws.read(p) for p, _ in changes}
        for p, content in changes:
            ws.write(p, content, from_llm=True)
        problems = self._regressions(before, old)
        if problems:
            for p, content in old.items():
                ws.write(p, content, from_llm=True)
            res.rejected += problems
            ctx.events.emit("correction_rejected", problems=problems[:5])
            return res
        for p, _ in changes:
            rec = ctx.files[p]
            rec.version += 1
            rec.digest = ws.digest(ws.read(p))
            res.applied.append(p)
        ctx.artifacts.save_file_manifest(list(ctx.files.values()))
        ctx.dirty = True
        return res

    def _structure(self) -> list[Issue]:
        ctx = self.ctx
        return verify_structure(ctx.g, ctx.workspace, ctx.screen_specs, ctx.component_specs, [t.path for t in ctx.tests])

    def _regressions(self, before: set[str], old: dict[str, str]) -> list[str]:
        ctx = self.ctx
        problems = [f"correction would violate the graph: {i.message}" for i in self._structure() if (i.code + i.message) not in before]
        for p, previous in old.items():
            new = ctx.workspace.read(p)
            if p.startswith("tests/"):
                for label, rx in (("test cases", r"\b(?:test|it)\s*\("), ("assertions", r"\bexpect\s*\(")):
                    if _count(rx, new) < _count(rx, previous):
                        problems.append(f"{p}: correction removes {label} (tests may be fixed, not weakened)")
        return problems
