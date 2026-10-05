"""Deterministic offline LLM (spec 56). Returns fixtures derived from the request context + graph, so the whole
pipeline runs without a model.  Optional fault injection lets tests and demos exercise the correction loops."""
from __future__ import annotations

import json

from app.domain.models.errors import LLMError
from app.domain.models.graph import GraphPackage
from app.llm.base import LLMProvider, LLMRequest, LLMResponse
from app.llm.mock_fixtures.e2e_tests import E2EFixtures

FAULTS = {"build", "functional", "visual"}


class MockLLMProvider(LLMProvider):
    name = "mock"

    def __init__(self, graph: GraphPackage | None = None, faults: set[str] | None = None):
        self.graph = graph
        self.faults = set(faults or ())
        unknown = self.faults - FAULTS
        if unknown:
            raise ValueError(f"unknown mock faults {sorted(unknown)}; choose from {sorted(FAULTS)}")
        self._fx: E2EFixtures | None = E2EFixtures(graph) if graph else None
        self._clean: dict[str, str] = {}  # path -> fault-free content, used by correction stages
        self._injected: set[str] = set()
        self.calls: list[tuple[str, str | None]] = []

    def bind_graph(self, graph: GraphPackage) -> None:
        self.graph = graph
        self._fx = E2EFixtures(graph)

    # ------------------------------------------------------------------ dispatch
    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append((request.stage, request.unit))
        handler = getattr(self, f"_stage_{request.stage}", None)
        if handler is None:
            raise LLMError(f"MockLLMProvider has no fixture for stage '{request.stage}'")
        out = handler(request.context)
        return LLMResponse(text=json.dumps(out), model="mock")

    @property
    def fx(self) -> E2EFixtures:
        if self._fx is None:
            raise LLMError("MockLLMProvider needs the graph (bind_graph) before generating code")
        return self._fx

    # ------------------------------------------------------------------ planning stages (echo the deterministic baselines)
    def _stage_graph_analysis(self, c: dict) -> dict:
        ex = c["extracted"]
        return {
            "summary": f"{c['project']['name']}: {len(ex['screens'])} screens, {len(ex['workflow_refs'])} workflows, {len(ex['api_refs'])} API endpoints, {len(ex['role_refs'])} roles.",
            "risks": [f"Open question: {q}" for q in c.get("open_questions", [])],
            "implementation_notes": ["Permissions only shape the UI; the backend remains the authority.", "State transitions follow state_machines.json exactly."],
        }

    def _stage_frontend_architecture(self, c: dict) -> dict:
        return c["baseline"]

    def _stage_design_system(self, c: dict) -> dict:
        return c["baseline"]

    def _stage_page_planning(self, c: dict) -> dict:
        b = c["baseline_spec"]
        return {"screen_ref": b["screen_ref"], "route": b["route"], "components": b["components"], "states": b["states"], "responsive": b["responsive"],
                "notes": f"{b['page_component']} composes {len(b['components'])} graph components; data via {len(b['data_sources'])} API hooks."}

    def _stage_component_planning(self, c: dict) -> dict:
        return {"components": [{"component_ref": b["component_ref"], "props": b["props"], "primitives": b["primitives"], "states": b["states"],
                                "accessibility": b["accessibility"], "notes": f"{b['name']} ({b['kind']})"} for b in c["baseline_components"]]}

    def _stage_api_integration(self, c: dict) -> dict:
        b = c["baseline"]
        return {"apis": [{"api_ref": a["api_ref"], "notes": f"{a['method']} {a['path']}"} for a in b["apis"]], "error_handling": b["error_handling"]}

    def _stage_state_management(self, c: dict) -> dict:
        b = c["baseline"]
        return {"queries": b["queries"], "mutations": b["mutations"], "local_state": b["local_state"]}

    # ------------------------------------------------------------------ code generation
    def _stage_code_generation(self, c: dict) -> dict:
        unit = c["unit"]
        kind, path = unit["type"], unit["allowed_output_paths"][0]
        fx = self.fx
        if kind == "hooks":
            content = fx.hooks(c["unit"]["id"].split(":", 1)[1])
        elif kind == "component":
            content = fx.component(c["component_spec"])
            content = self._maybe_fault_component(c["component_spec"], path, content)
        elif kind == "page":
            content = self._maybe_fault_page(c["screen_spec"], path, fx.page(c["screen_spec"]))
        elif kind == "unit_test":
            if "component_spec" in c:
                content = fx.unit_test({"component_ref": c["component_spec"]["component_ref"], "path": path})
            else:
                s = c["screen_spec"]
                content = fx.unit_test({"screen_ref": s["screen_ref"], "path": path, "page_path": s["page_path"], "page_component": s["page_component"]})
        elif kind == "integration_test":
            content = fx.integration({**c["spec"], "path": path})
        elif kind == "e2e":
            content = fx.e2e(c["spec"])
        elif kind == "visual":
            content = fx.visual(c["spec"])
        else:
            raise LLMError(f"unknown unit type {kind}")
        return {"files": [{"path": path, "purpose": unit["title"], "content": content}]}

    def _maybe_fault_component(self, spec: dict, path: str, content: str) -> str:
        kind = spec["kind"]
        faulty = None
        if "build" in self.faults and kind == "status_badge" and "build" not in self._injected:
            faulty = content + "\nexport const mockFault: number = 'this is not a number';\n"
            self._injected.add("build")
        elif "visual" in self.faults and kind == "table" and "visual" not in self._injected:
            faulty = content.replace("<Table aria-label=", "<Table style={{ minWidth: 1500 }} aria-label=", 1)
            self._injected.add("visual")
        if faulty and faulty != content:
            self._clean[path] = content
            return faulty
        return content

    def _maybe_fault_page(self, spec: dict, path: str, content: str) -> str:
        """functional fault: a create page that forgets the success notification the workflow requires."""
        if "functional" in self.faults and "functional" not in self._injected and spec["kind"] == "form":
            faulty = "\n".join(ln for ln in content.splitlines() if not ln.strip().startswith("notify(")) + "\n"
            if faulty != content:
                self._injected.add("functional")
                self._clean[path] = content
                return faulty.replace("const notify = useNotify();\n", "").replace("import { useNotify } from '../../../components/Notifications';\n", "")
        return content

    # ------------------------------------------------------------------ review / analysis / correction
    def _stage_code_review(self, c: dict) -> dict:
        return {"summary": f"Reviewed {len(c.get('files', []))} files: no blocking issues found.", "issues": []}

    def _fixed_files(self, c: dict) -> list[dict]:
        out = []
        for f in c.get("files", []):
            clean = self._clean.get(f["path"])
            if clean is not None and clean != f["content"]:
                out.append({"path": f["path"], "content": clean, "purpose": "restore the graph-conformant implementation"})
        return out

    def _stage_build_error_correction(self, c: dict) -> dict:
        files = self._fixed_files(c)
        return {"decision": "fix_implementation", "explanation": "Removed the invalid statement that broke compilation." if files else "No safe fix found.", "files": files}

    def _stage_browser_error_analysis(self, c: dict) -> dict:
        paths = [f["path"] for f in c.get("files", [])]
        return {
            "classification": c["failure"]["kind"], "decision": "fix_implementation", "root_cause": "A generated component deviates from the workflow/graph specification.",
            "files_to_change": paths, "plan": ["Restore the behaviour required by the workflow and acceptance criteria; keep every graph-defined field and permission."],
            "graph_conflict": None,
        }

    def _stage_visual_analysis(self, c: dict) -> dict:
        return {"issues": [], "summary": "Mock provider cannot inspect pixels; objective layout metrics are evaluated by the agent's own checks."}

    def _stage_correction(self, c: dict) -> dict:
        files = self._fixed_files(c)
        return {"decision": "fix_implementation", "explanation": "Restored the specified behaviour." if files else "No change proposed.", "files": files}

    def _stage_final_review(self, c: dict) -> dict:
        return {"verdict": "pass", "concerns": []}
