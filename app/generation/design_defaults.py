"""Baseline design system. The design_system stage may adapt it; Python validates (incl. WCAG contrast)."""
from __future__ import annotations

import copy
import re

DEFAULT_DESIGN_SYSTEM: dict = {
    "name": "Default product design system",
    "typography": {
        "fontFamily": {"sans": ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"]},
        "scale": {"xs": "0.75rem", "sm": "0.875rem", "base": "1rem", "lg": "1.125rem", "xl": "1.25rem", "2xl": "1.5rem", "3xl": "1.875rem"},
        "weights": {"regular": 400, "medium": 500, "semibold": 600, "bold": 700},
    },
    "spacing": {"unit": "4px", "scale": {"1": "4px", "2": "8px", "3": "12px", "4": "16px", "6": "24px", "8": "32px"}},
    "colors": {
        "background": "#f8fafc", "surface": "#ffffff", "surfaceMuted": "#f1f5f9",
        "text": "#0f172a", "textMuted": "#475569",
        "border": "#cbd5e1", "borderStrong": "#64748b",
        "primary": "#1d4ed8", "primaryHover": "#1e40af", "onPrimary": "#ffffff",
        "danger": "#b91c1c", "dangerHover": "#991b1b", "onDanger": "#ffffff",
        "focusRing": "#1d4ed8", "overlay": "rgba(15, 23, 42, 0.55)",
        "status": {
            "neutral": {"bg": "#e2e8f0", "fg": "#1e293b", "border": "#94a3b8"},
            "info": {"bg": "#dbeafe", "fg": "#1e3a8a", "border": "#93c5fd"},
            "success": {"bg": "#dcfce7", "fg": "#14532d", "border": "#86efac"},
            "warning": {"bg": "#fef3c7", "fg": "#78350f", "border": "#fcd34d"},
            "danger": {"bg": "#fee2e2", "fg": "#7f1d1d", "border": "#fca5a5"},
        },
    },
    "borders": {"width": "1px", "style": "solid"},
    "radius": {"sm": "4px", "md": "6px", "lg": "8px", "xl": "12px", "full": "9999px"},
    "shadows": {"card": "0 1px 2px rgba(15, 23, 42, 0.06), 0 1px 3px rgba(15, 23, 42, 0.1)", "dialog": "0 10px 25px rgba(15, 23, 42, 0.2)"},
    "breakpoints": {"sm": 640, "md": 768, "lg": 1024, "xl": 1280},
    "primitives": ["Button", "Input", "Textarea", "Select", "Card", "Table", "Modal", "Badge", "Alert", "Pagination", "Tabs", "Dropdown", "LoadingState", "EmptyState", "ErrorState"],
    "components": {
        "buttons": {"variants": ["primary", "secondary", "danger", "ghost"], "minTouchTarget": "44px", "loading": "spinner + aria-busy"},
        "inputs": {"height": "40px desktop / 44px touch", "labels": "always visible, linked with for/id", "errors": "text below field with role=alert"},
        "forms": {"layout": "single column, max-w-xl", "actions": "primary submit + secondary cancel/reset"},
        "cards": {"padding": "16px mobile / 24px desktop", "radius": "lg"},
        "tables": {"desktop": "semantic table", "mobile": "rows become labelled stacked cards"},
        "dialogs": {"desktop": "centered, max-w-lg", "mobile": "bottom sheet", "behavior": "focus trap, Esc closes, focus restored"},
        "badges": {"variants": ["neutral", "info", "success", "warning", "danger"], "rule": "never colour-only: always has text"},
        "alerts": {"danger": "role=alert", "other": "role=status"},
        "navigation": {"desktop": "fixed sidebar", "tablet": "fixed sidebar", "mobile": "top bar + collapsible menu button"},
        "tabs": {"keyboard": "arrow keys move selection"},
        "dropdowns": {"keyboard": "arrow keys, Esc closes"},
        "loading": {"pattern": "skeleton rows with sr-only status text"},
        "empty_states": {"pattern": "title, explanation, primary action when permitted"},
        "error_states": {"pattern": "plain-language message, Retry button, never stack traces"},
    },
    "responsive": {
        "desktop": "min-width 1024px: sidebar navigation, multi-column grids, full tables, centered dialogs",
        "tablet": "768-1023px: sidebar retained, two-column grids, full tables with tighter padding",
        "mobile": "<768px: top bar + menu button, single column, tables become stacked cards, dialogs are bottom sheets, 44px touch targets",
    },
}


def default_design_system() -> dict:
    return copy.deepcopy(DEFAULT_DESIGN_SYSTEM)


# ---- WCAG contrast ----
def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    rgb = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

REQUIRED_SECTIONS = ("typography", "spacing", "colors", "borders", "radius", "shadows", "components", "responsive", "breakpoints")
REQUIRED_COMPONENTS = ("buttons", "inputs", "forms", "cards", "tables", "dialogs", "badges", "alerts", "navigation", "tabs", "dropdowns", "loading", "empty_states", "error_states")
REQUIRED_COLORS = ("background", "surface", "surfaceMuted", "text", "textMuted", "border", "borderStrong", "primary", "primaryHover", "onPrimary", "danger", "dangerHover", "onDanger", "focusRing", "overlay", "status")
STATUS_VARIANTS = ("neutral", "info", "success", "warning", "danger")


def validate_design_system(ds: dict) -> list[str]:
    problems: list[str] = []
    for s in REQUIRED_SECTIONS:
        if s not in ds:
            problems.append(f"missing section '{s}'")
    if problems:
        return problems
    for c in REQUIRED_COMPONENTS:
        if c not in ds["components"]:
            problems.append(f"components.{c} missing")
    for b in ("desktop", "tablet", "mobile"):
        if b not in ds["responsive"]:
            problems.append(f"responsive.{b} missing")
    colors = ds["colors"]
    for k in REQUIRED_COLORS:
        if k not in colors:
            problems.append(f"colors.{k} missing")
    if problems:
        return problems
    for k, v in colors.items():
        if k in ("status", "overlay"):
            continue
        if not isinstance(v, str) or not HEX.match(v):
            problems.append(f"colors.{k} must be a hex colour")
    for v in STATUS_VARIANTS:
        st = colors["status"].get(v)
        if not st or not all(HEX.match(str(st.get(x, ""))) for x in ("bg", "fg", "border")):
            problems.append(f"colors.status.{v} needs hex bg/fg/border")
    if problems:
        return problems
    pairs = [
        ("text", "background"), ("text", "surface"), ("text", "surfaceMuted"), ("textMuted", "background"), ("textMuted", "surface"),
        ("textMuted", "surfaceMuted"), ("onPrimary", "primary"), ("onPrimary", "primaryHover"), ("onDanger", "danger"),
        ("onDanger", "dangerHover"), ("primary", "surface"), ("primary", "background"), ("danger", "surface"), ("danger", "background"),
    ]
    for fg, bg in pairs:
        r = contrast_ratio(colors[fg], colors[bg])
        if r < 4.5:
            problems.append(f"contrast {fg} on {bg} is {r:.2f}:1 (< 4.5:1)")
    for v in STATUS_VARIANTS:
        st = colors["status"][v]
        r = contrast_ratio(st["fg"], st["bg"])
        if r < 4.5:
            problems.append(f"contrast status.{v}.fg on bg is {r:.2f}:1 (< 4.5:1)")
    if contrast_ratio(colors["borderStrong"], colors["surface"]) < 3:
        problems.append("borderStrong must have >= 3:1 contrast on surface (form control boundaries)")
    return problems
