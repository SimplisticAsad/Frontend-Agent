"""Stage 9 - LLM code review of the generated code (advisory, plus one guarded fix for blocking findings)."""
from __future__ import annotations

from app.domain.models.errors import ErrorKind
from app.pipeline.context import RunContext
from app.pipeline.correction import CorrectionService
from app.pipeline.failures import Failure

SEV = {"blocking", "warning", "info"}
MAX_CHARS_PER_FILE = 3500


def run(ctx: RunContext) -> dict:
    llm_files = [p for p, r in ctx.files.items() if r.generator == "llm" and not p.startswith("tests/")]
    files = [{"path": p, "source_refs": ctx.files[p].source_refs, "content": ctx.workspace.read(p)[:MAX_CHARS_PER_FILE]} for p in llm_files]
    context = {**ctx.contexts.base(), "files": files, "screens": [s.model_dump() for s in ctx.screen_specs], "components": [c.model_dump() for c in ctx.component_specs]}
    allowed = set(llm_files)

    def validate(out: object) -> list[str]:
        if not isinstance(out, dict) or not isinstance(out.get("issues"), list):
            return ['output must be {"summary": str, "issues": [...]}']
        p = []
        for i in out["issues"]:
            if not isinstance(i, dict) or i.get("severity") not in SEV:
                p.append(f"issue severity must be one of {sorted(SEV)}")
            elif i.get("path") not in allowed:
                p.append(f"issue path {i.get('path')!r} is not one of the reviewed files")
        return p

    review = ctx.runner.call("code_review", context, validate)
    blocking = [i for i in review["issues"] if i["severity"] == "blocking"]
    for i in review["issues"]:
        if i["severity"] != "blocking":
            ctx.warnings.append(f"review[{i['severity']}] {i['path']}: {i['description']}")
    result = {"summary": review.get("summary", ""), "issues": review["issues"], "blocking_fix": None}
    if blocking:
        failure = Failure(ErrorKind.GRAPH_IMPLEMENTATION_CONFLICT, "review", f"{len(blocking)} blocking review finding(s)", "\n".join(f"{i['path']}: {i['description']}" for i in blocking),
                          sorted({i["path"] for i in blocking}), issues=blocking)
        ctx.attempts["build"] += 1
        res = CorrectionService(ctx).correct(failure)
        result["blocking_fix"] = {"applied": res.applied, "rejected": res.rejected, "decision": res.decision}
        if not res.changed:
            ctx.warnings.append("blocking review findings could not be fixed automatically: " + "; ".join(i["description"] for i in blocking))
    ctx.artifacts.save("code_review.json", result)
    return result
