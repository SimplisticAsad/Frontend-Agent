"""CLI: python -m app.main <generate|validate|test|browser-test> --project projects/<name> [--mock]"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from app.config.settings import Settings
from app.domain.models.errors import AgentError, GraphError
from app.llm.factory import create_provider
from app.llm.mock import FAULTS
from app.pipeline.orchestrator import FrontendAgent


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="frontend_agent", description="Generate, test and verify a React/TypeScript frontend from validated project graphs.")
    sub = p.add_subparsers(dest="command", required=True)
    for name, helptext in (("generate", "run the full pipeline"), ("validate", "validate the graph package only"), ("test", "typecheck, lint, build and unit-test an existing frontend"),
                           ("browser-test", "run Playwright functional + visual tests against an existing frontend")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--project", required=True, help="project directory, e.g. projects/task_manager (contains graphs/)")
        s.add_argument("--mock", action="store_true", help="use the deterministic offline MockLLMProvider")
        s.add_argument("--mock-faults", default="", help=f"comma separated faults for the mock to inject ({', '.join(sorted(FAULTS))}) to exercise the correction loops")
        s.add_argument("--verbose", "-v", action="store_true")
        if name == "generate":
            s.add_argument("--incremental", action="store_true", help="reuse unchanged code-generation units from the previous run")
            s.add_argument("--skip-install", action="store_true", help="do not run npm install")
        if name == "browser-test":
            s.add_argument("--no-visual", action="store_true", help="skip the visual capture/analysis")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s")
    settings = Settings()
    faults = {f for f in args.mock_faults.split(",") if f}
    try:
        needs_llm = args.command != "validate"  # graph validation is fully deterministic
        llm = create_provider(settings.llm, mock=args.mock or not needs_llm, faults=faults) if (args.mock or not needs_llm or settings.llm.provider == "mock") else create_provider(settings.llm)
        agent = FrontendAgent(args.project, llm, settings=settings, incremental=getattr(args, "incremental", False), skip_install=getattr(args, "skip_install", False))
        if args.command == "validate":
            warnings = agent.validate()
            print(json.dumps({"status": "valid", "project": agent.ctx.g.project_id, "graph_version": agent.ctx.g.graph_version, "warnings": [w.message for w in warnings]}, indent=2))
            return 0
        if args.command == "generate":
            report = agent.generate()
            print(json.dumps({k: report[k] for k in ("project", "status", "build_result", "browser_test_result", "correction_attempts", "errors")}, indent=2))
            print(f"\nFrontend: {Path(args.project) / 'frontend'}\nReport:   {Path(args.project) / 'frontend-artifacts' / 'frontend_report.json'}")
            return 0 if report["status"] == "passed" else 1
        if args.command == "test":
            out = agent.test()
        else:
            out = agent.browser_test(visual=not args.no_visual)
        print(json.dumps(out, indent=2))
        return 0 if out["passed"] else 1
    except GraphError as e:
        print(json.dumps({"status": "GRAPH_ERROR", "message": str(e), "issues": [i.to_dict() for i in e.issues]}, indent=2), file=sys.stderr)
        return 2
    except AgentError as e:
        print(json.dumps({"status": e.kind.value, "message": str(e), "issues": [i.to_dict() for i in e.issues]}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
