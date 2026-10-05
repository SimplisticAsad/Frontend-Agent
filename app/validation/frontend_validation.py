"""Static + structural checks on generated frontend source (no LLM, no build)."""
from __future__ import annotations

import re

from app.domain.models.conventions import UI_CONVENTIONS  # noqa: F401  (re-exported for convenience)
from app.domain.models.errors import ErrorKind, Issue
from app.domain.models.graph import GraphPackage
from app.domain.models.naming import form_testid, page_testid, workflow_testid
from app.domain.specifications.specs import ComponentSpec, ScreenSpec
from app.generation.file_generator import FileWorkspace

FORBIDDEN = [
    (re.compile(r"dangerouslySetInnerHTML"), "dangerouslySetInnerHTML is not allowed"),
    (re.compile(r"\beval\s*\("), "eval() is not allowed"),
    (re.compile(r"new\s+Function\s*\("), "new Function() is not allowed"),
    (re.compile(r"child_process|require\(['\"]fs['\"]\)"), "Node process/fs access is not allowed in app code"),
    (re.compile(r"console\.log\("), "remove debugging console.log"),
    (re.compile(r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*['\"][^'\"]{6,}['\"]"), "hard-coded credential-looking literal"),
]


def check_generated_source(path: str, content: str) -> list[str]:
    """Problems with one LLM-written file (fed back to the model for a retry)."""
    problems: list[str] = []
    if not content.strip():
        return ["file is empty"]
    if path.startswith("src/"):
        for rx, msg in FORBIDDEN:
            if rx.search(content):
                problems.append(f"{path}: {msg}")
        if not path.startswith("src/lib/api/") and re.search(r"\bfetch\s*\(", content):
            problems.append(f"{path}: HTTP calls belong in src/lib/api (use the generated API functions and hooks)")
    if path.endswith((".ts", ".tsx")) and "export" not in content and not path.startswith("tests/"):
        problems.append(f"{path}: must export its component/hook")
    if path.endswith((".ts", ".tsx")) and content.count("{") != content.count("}"):
        problems.append(f"{path}: unbalanced braces")
    if path.endswith((".ts", ".tsx")) and content.count("(") != content.count(")"):
        problems.append(f"{path}: unbalanced parentheses")
    return problems


def verify_structure(g: GraphPackage, ws: FileWorkspace, screens: list[ScreenSpec], comps: list[ComponentSpec], test_paths: list[str]) -> list[Issue]:
    """Invariants that must hold after generation *and* after every correction (corrections may not drop requirements)."""
    issues: list[Issue] = []

    def bad(code: str, msg: str, refs: list[str]) -> None:
        issues.append(Issue(ErrorKind.GRAPH_IMPLEMENTATION_CONFLICT, code, msg, refs))

    def read(path: str) -> str:
        return ws.read(path) if ws.exists(path) else ""

    routes_src = read("src/app/router.tsx")
    for s in screens:
        src = read(s.page_path)
        if not src:
            bad("missing_page", f"{s.page_path} is missing for {s.screen_ref}", [s.screen_ref])
            continue
        if f"path: '{s.route}'" not in routes_src:
            bad("missing_route", f"route {s.route} for {s.screen_ref} is not registered", [s.screen_ref])
        if page_testid(s.screen_ref) not in src:
            bad("missing_page_testid", f"{s.page_path} lacks its page test id", [s.screen_ref])
        for state, marker in (("loading", "LoadingState"), ("empty", "EmptyState"), ("error", "ErrorState")):
            if state in s.states and s.data_sources and marker not in src and not any(marker in read(c.path) for c in comps if c.component_ref in s.components):
                bad("missing_state", f"{s.page_path} does not implement the {state} state ({marker})", [s.screen_ref])
        for wref in s.actions:
            wf = g.require(wref)
            if wf["kind"] in ("create", "delete") and (wf.get("trigger") or {}).get("screen") == s.screen_ref:
                tid = workflow_testid(wref)
                if tid not in src and not any(tid in read(c.path) for c in comps if c.component_ref in s.components):
                    bad("missing_workflow_trigger", f"{s.screen_ref} does not render the trigger for {wref} ({tid})", [s.screen_ref, wref])
            if wf["kind"] in ("create", "delete") and wf.get("permission"):
                if (wf.get("trigger") or {}).get("screen") == s.screen_ref and "can(" not in src:
                    bad("permission_not_applied", f"{s.page_path} does not check permissions for {wref}", [s.screen_ref, wref])
                if wf.get("screen") == s.screen_ref and (wf["permission"] not in s.permissions or f"'{wf['permission']}'" not in routes_src):
                    bad("permission_not_applied", f"route {s.route} is not guarded by {wf['permission']} for {wref}", [s.screen_ref, wref])
    for c in comps:
        src = read(c.path)
        if not src:
            bad("missing_component", f"{c.path} is missing for {c.component_ref}", [c.component_ref or c.name])
            continue
        if c.kind == "form":
            wf = g.require(next(w for w in c.workflow_refs))
            if form_testid(wf["id"]) not in src:
                bad("missing_form_testid", f"{c.path} lacks {form_testid(wf['id'])}", [c.component_ref or c.name, wf["id"]])
            for f in wf.get("form_fields", []):
                if not re.search(rf"['\"`]{re.escape(f)}['\"`]", src):
                    bad("form_field_removed", f"{c.path} no longer renders required form field '{f}' of {wf['id']}", [wf["id"], c.component_ref or c.name])
        if c.kind == "status_control" and "onTransition" not in src:
            bad("state_machine_ignored", f"{c.path} does not drive transitions", [c.component_ref or c.name])
    for sm in g.nodes("state_machines"):
        pages = [read(s.page_path) for s in screens if any(w["state_machine"] == sm["id"] for w in g.many(s.actions) if w.get("state_machine"))]
        for p in pages:
            if "allowedTransitions" not in p:
                bad("transition_rule_missing", f"a page driving {sm['id']} must use allowedTransitions()", [sm["id"]])
    for b_api in g.apis:
        mod = None
        for cand in ws.list_files("src/lib/api"):
            if b_api["path"].split("{")[0] in read(cand):
                mod = cand
                break
        if mod is None:
            bad("api_not_integrated", f"no API client function for {b_api['id']} ({b_api['method']} {b_api['path']})", [b_api["id"]])
    for t in test_paths:
        if not ws.exists(t):
            bad("missing_test", f"test file {t} is missing", [t])
    return issues
