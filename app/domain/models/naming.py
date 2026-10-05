"""Deterministic naming + UI conventions shared by generators, prompts and tests.

Everything that must agree between generated source and generated tests
(test ids, file names, symbol names) is derived here from graph ids.
"""
from __future__ import annotations

import re


def tail(ref: str) -> str:
    """`screen.project.list` -> `project.list`."""
    return ref.split(".", 1)[1] if "." in ref else ref


def words(ref: str) -> list[str]:
    return [w for w in re.split(r"[._\-\s/]+", tail(ref)) if w]


def pascal(ref: str) -> str:
    return "".join(w[:1].upper() + w[1:] for w in words(ref))


def camel(ref: str) -> str:
    p = pascal(ref)
    return p[:1].lower() + p[1:]


def slug(ref: str) -> str:
    return "-".join(w.lower() for w in words(ref))


def title(ref_or_text: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in words(ref_or_text))


def label_of(field_name: str) -> str:
    parts = [w for w in re.split(r"[_\s]+", field_name) if w]
    return " ".join([parts[0][:1].upper() + parts[0][1:]] + [w.lower() for w in parts[1:]]) if parts else ""


def plural(word: str) -> str:
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith("s"):
        return word
    return word + "s"


# ---- test id conventions (documented to the code generator via prompt context) ----
def page_testid(screen_ref: str) -> str:
    return f"page-{slug(screen_ref)}"


def workflow_testid(workflow_ref: str) -> str:
    return f"workflow-{slug(workflow_ref)}"


def form_testid(workflow_ref: str) -> str:
    return f"form-{slug(workflow_ref)}"


def row_testid(entity_ref: str) -> str:
    return f"row-{slug(entity_ref)}"
