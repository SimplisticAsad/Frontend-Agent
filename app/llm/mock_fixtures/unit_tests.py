"""Vitest + React Testing Library fixtures for the MockLLMProvider."""
from __future__ import annotations

import json

from app.domain.models.naming import label_of, page_testid, row_testid, workflow_testid
from app.generation.symbols import (
    component_path, entity_name, enum_type_name, field_label, list_binding_for_entity, machine_for_entity, seed_data, state_label, workflow_schema_names,
)
from app.llm.mock_fixtures.pages import PageFixtures
from app.llm.mock_fixtures.tsgen import q


def sample_value(g, ent: str, name: str) -> str:
    """A value that satisfies the graph validations for the field."""
    f = g.entity_field(ent, name) or {}
    rules: dict = {}
    for v in g.validations_for(ent, name):
        rules.update(v["rules"])
    t = f.get("type", "string")
    if t == "email":
        return "person@example.com"
    if t == "password":
        return "Password123!"
    if t == "date":
        return "2030-12-31"
    if t == "enum":
        return f["values"][0]
    base = f"Valid {field_label(g, ent, name).lower()} value"
    base = base.ljust(int(rules.get("min_length", 0)), "x")
    return base[: int(rules["max_length"])] if rules.get("max_length") else base


def too_short(g, ent: str, name: str) -> tuple[str, int] | None:
    for v in g.validations_for(ent, name):
        n = v["rules"].get("min_length")
        if n and n > 1:
            return "a" * (n - 1), n
    return None


class UnitTestFixtures(PageFixtures):
    def seed_rows(self, ent: str, n: int = 2) -> list[dict]:
        from app.generation.symbols import collection_of

        return seed_data(self.g).collections.get(collection_of(ent), [])[:n]

    def user_obj(self, role: str) -> dict:
        from app.generation.symbols import collection_of

        users = next(e for e in self.g.entities if {"email", "role"} <= {f["name"] for f in e["fields"]})
        return next(u for u in seed_data(self.g).collections[collection_of(users["id"])] if u["id"] == f"user-{role}")

    def unit_test(self, spec: dict) -> str:
        if spec.get("component_ref"):
            comp = self.g.require(spec["component_ref"])
            return getattr(self, f"_t_{comp['kind']}")(comp, spec)
        return self._t_page(self.g.require(spec["screen_ref"]), spec)

    # ------------------------------------------------------------------ components
    def _t_form(self, comp: dict, spec: dict) -> str:
        wf = self.g.require(comp["workflow"])
        ent = wf["entity"]
        name = comp["name"]
        login = wf["kind"] == "login"
        fields = wf["form_fields"]
        has_ref = any((self.g.entity_field(ent, f) or {}).get("type") == "ref" for f in fields)
        ref_opts = {}
        for f in fields:
            fd = self.g.entity_field(ent, f)
            if fd["type"] == "ref":
                rows = self.seed_rows(fd["ref"], 2)
                disp = self.display_field(fd["ref"])
                ref_opts[f] = [{"value": r["id"], "label": r[disp]} for r in rows]
        values = {f: (ref_opts[f][0]["value"] if f in ref_opts else sample_value(self.g, ent, f)) for f in fields if self.is_required(ent, f)}
        first_req = next((f for f in fields if self.is_required(ent, f)), None)
        req_msg = None
        if first_req:
            custom = next((v.get("message") for v in self.g.validations_for(ent, first_req) if v.get("message")), None)
            req_msg = custom or f"{field_label(self.g, ent, first_req)} is required"
        lines = [
            "import { screen } from '@testing-library/react';",
            "import userEvent from '@testing-library/user-event';",
            "import { describe, expect, it, vi } from 'vitest';",
            f"import {{ {name} }} from '{self._rel(spec['path'], component_path(comp))}';",
            "import { renderWithProviders } from './test-utils';",
            "",
        ]
        ref_const = f"const refOptions = {json.dumps(ref_opts)};\n" if has_ref else ""
        props_base = ["onSubmit: vi.fn()"] + ([] if login else ["onCancel: vi.fn()"]) + ["isSubmitting: false", "serverError: null", "fieldErrors: {}"] + (["refOptions"] if has_ref else [])
        lines.append(ref_const + f"const baseProps = {{ {', '.join(props_base)} }};\n")
        lines.append(f"describe({q(name)}, () => {{")
        labels = [(f, field_label(self.g, ent, f)) for f in fields]
        lines.append("  it('renders a labelled control for every graph-defined form field', () => {")
        lines.append(f"    renderWithProviders(<{name} {{...baseProps}} />);")
        for f, lab in labels:
            lines.append(f"    expect(screen.getByLabelText(/^{lab}/)).toBeInTheDocument();")
        lines.append(f"    expect(screen.getByRole('button', {{ name: {q(wf['submit_label'])} }})).toBeInTheDocument();")
        lines.append("  });\n")
        if first_req:
            lines.append("  it('blocks submission and explains what is missing', async () => {")
            lines.append("    const onSubmit = vi.fn();")
            lines.append(f"    renderWithProviders(<{name} {{...baseProps}} onSubmit={{onSubmit}} />);")
            lines.append(f"    await userEvent.click(screen.getByRole('button', {{ name: {q(wf['submit_label'])} }}));")
            lines.append(f"    expect(await screen.findByText({q(req_msg)})).toBeInTheDocument();")
            lines.append("    expect(onSubmit).not.toHaveBeenCalled();")
            lines.append("  });\n")
        short = next(((f, too_short(self.g, ent, f)) for f in fields if too_short(self.g, ent, f)), None)
        if short:
            f, (val, n) = short
            lines.append(f"  it('rejects a {field_label(self.g, ent, f).lower()} shorter than {n} characters', async () => {{")
            lines.append(f"    renderWithProviders(<{name} {{...baseProps}} />);")
            lines.append(f"    await userEvent.type(screen.getByLabelText(/^{field_label(self.g, ent, f)}/), {q(val)});")
            lines.append(f"    await userEvent.click(screen.getByRole('button', {{ name: {q(wf['submit_label'])} }}));")
            lines.append(f"    expect(await screen.findByText(/at least {n} characters/)).toBeInTheDocument();")
            lines.append("  });\n")
        lines.append("  it('submits the validated values', async () => {")
        lines.append("    const onSubmit = vi.fn();")
        lines.append(f"    renderWithProviders(<{name} {{...baseProps}} onSubmit={{onSubmit}} />);")
        for f, lab in labels:
            if f not in values:
                continue
            fd = self.g.entity_field(ent, f)
            if fd["type"] == "ref":
                lines.append(f"    await userEvent.selectOptions(screen.getByLabelText(/^{lab}/), {q(values[f])});")
            else:
                lines.append(f"    await userEvent.type(screen.getByLabelText(/^{lab}/), {q(values[f])});")
        lines.append(f"    await userEvent.click(screen.getByRole('button', {{ name: {q(wf['submit_label'])} }}));")
        lines.append(f"    await vi.waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));")
        lines.append(f"    expect(onSubmit.mock.calls[0][0]).toMatchObject({json.dumps(values)});")
        lines.append("  });\n")
        lines.append("  it('shows server-side errors without exposing technical detail', () => {")
        lines.append(f"    renderWithProviders(<{name} {{...baseProps}} serverError=\"The server rejected this request.\" />);")
        lines.append("    expect(screen.getByRole('alert')).toHaveTextContent('The server rejected this request.');")
        lines.append("  });")
        if not login:
            lines.append("\n  it('lets the user cancel', async () => {")
            lines.append("    const onCancel = vi.fn();")
            lines.append(f"    renderWithProviders(<{name} {{...baseProps}} onCancel={{onCancel}} />);")
            lines.append("    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));")
            lines.append("    expect(onCancel).toHaveBeenCalledTimes(1);")
            lines.append("  });")
        lines.append("});")
        return "\n".join(lines) + "\n"

    def _rel(self, from_path: str, to_path: str) -> str:
        from app.generation.symbols import import_path

        return import_path(from_path, to_path)

    def _t_table(self, comp: dict, spec: dict) -> str:
        ent = comp["entity"]
        name = comp["name"]
        rows = self.seed_rows(ent, 2)
        disp = self.display_field(ent)
        delete_wf = next((self.g.require(w) for w in comp.get("row_actions", []) if self.g.require(w)["kind"] == "delete"), None)
        lines = [
            "import { screen, within } from '@testing-library/react';",
            "import userEvent from '@testing-library/user-event';",
            f"import {{ describe, expect, it{', vi' if delete_wf else ''} }} from 'vitest';",
            f"import {{ {name} }} from '{self._rel(spec['path'], component_path(comp))}';",
            "import { renderWithProviders } from './test-utils';",
            f"import type {{ {entity_name(ent)} }} from '{self._rel(spec['path'], self.type_file(ent))}';",
            "",
            f"const items = {json.dumps(rows)} as unknown as {entity_name(ent)}[];",
            "",
            f"describe({q(name)}, () => {{",
            "  it('renders one row per item with the display field', () => {",
            f"    renderWithProviders(<{name} items={{items}} />);",
        ]
        for r in rows:
            lines.append(f"    expect(screen.getByTestId({q(row_testid(ent) + '-' + r['id'])})).toHaveTextContent({q(str(r[disp]))});")
        lines.append("  });\n")
        lines.append("  it('paginates long lists', async () => {")
        lines.append(f"    const many = Array.from({{ length: 12 }}, (_, i) => ({{ ...items[0], id: `extra-${{i}}`, {disp}: `Item ${{i}}` }}));")
        lines.append(f"    renderWithProviders(<{name} items={{many}} />);")
        lines.append("    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument();")
        lines.append("    await userEvent.click(screen.getByRole('button', { name: 'Next' }));")
        lines.append("    expect(screen.getByText('Page 2 of 2')).toBeInTheDocument();")
        lines.append("  });")
        if comp.get("link_to"):
            lines.append("\n  it('links each row to its details screen', () => {")
            lines.append(f"    renderWithProviders(<{name} items={{items}} />);")
            lines.append(f"    const row = screen.getByTestId({q(row_testid(ent) + '-' + rows[0]['id'])});")
            lines.append(f"    expect(within(row).getByRole('link')).toHaveAttribute('href', expect.stringContaining({q(rows[0]['id'])}));")
            lines.append("  });")
        if delete_wf:
            tid = workflow_testid(delete_wf["id"])
            lines.append("\n  it('only offers row actions when the caller allows them', async () => {")
            lines.append("    const onDelete = vi.fn();")
            lines.append(f"    const {{ unmount }} = renderWithProviders(<{name} items={{items}} />);")
            lines.append(f"    expect(screen.queryByTestId({q(tid)})).not.toBeInTheDocument();")
            lines.append("    unmount();")
            lines.append(f"    renderWithProviders(<{name} items={{items}} onDelete={{onDelete}} />);")
            lines.append(f"    const row = screen.getByTestId({q(row_testid(ent) + '-' + rows[0]['id'])});")
            lines.append(f"    await userEvent.click(within(row).getByTestId({q(tid)}));")
            lines.append("    expect(onDelete).toHaveBeenCalledWith(items[0]);")
            lines.append("  });")
        lines.append("});")
        return "\n".join(lines) + "\n"

    def _t_status_badge(self, comp: dict, spec: dict) -> str:
        sm = self.g.require(comp["state_machine"])
        name = comp["name"]
        lines = [
            "import { screen } from '@testing-library/react';",
            "import { describe, expect, it } from 'vitest';",
            f"import {{ {name} }} from '{self._rel(spec['path'], component_path(comp))}';",
            "import { renderWithProviders } from './test-utils';",
            "",
            f"describe({q(name)}, () => {{",
            "  it('shows a text label for every state defined by the state machine', () => {",
        ]
        for s in sm["states"]:
            lines.append(f"    const {{ unmount: u_{s.lower()} }} = renderWithProviders(<{name} status={q(s)} />);")
            lines.append(f"    expect(screen.getByText({q(state_label(s))})).toBeInTheDocument();")
            lines.append(f"    u_{s.lower()}();")
        lines += ["  });", "});"]
        return "\n".join(lines) + "\n"

    def _t_status_control(self, comp: dict, spec: dict) -> str:
        sm = self.g.require(comp["state_machine"])
        wf = self.g.require(comp["workflow"])
        ent = sm["entity"]
        name = comp["name"]
        prop = name and (entity_name(ent)[:1].lower() + entity_name(ent)[1:])
        row = self.seed_rows(ent, 1)[0]
        tid = workflow_testid(wf["id"])
        states = sm["states"]
        first_to = next(t["to"] for t in sm["transitions"] if t["from"] == row[sm["field"]])
        allowed = [t["to"] for t in sm["transitions"] if t["from"] == row[sm["field"]]]
        lines = [
            "import { screen } from '@testing-library/react';",
            "import userEvent from '@testing-library/user-event';",
            "import { describe, expect, it, vi } from 'vitest';",
            f"import {{ {name} }} from '{self._rel(spec['path'], component_path(comp))}';",
            "import { renderWithProviders } from './test-utils';",
            f"import type {{ {entity_name(ent)} }} from '{self._rel(spec['path'], self.type_file(ent))}';",
            "",
            f"const {prop} = {json.dumps(row)} as unknown as {entity_name(ent)};",
            f"const allowed = {json.dumps(allowed)};",
            "",
            f"describe({q(name)}, () => {{",
            "  it('offers exactly the transitions it is given', () => {",
            f"    renderWithProviders(<{name} {prop}={{{prop}}} allowed={{allowed as never}} onTransition={{vi.fn()}} isPending={{false}} error={{null}} />);",
            f"    const options = Array.from(screen.getByTestId({q(tid)}).querySelectorAll('option')).map((o) => o.getAttribute('value'));",
            "    expect(options).toEqual(['', ...allowed]);",
            "  });\n",
            "  it('reports the chosen transition', async () => {",
            "    const onTransition = vi.fn();",
            f"    renderWithProviders(<{name} {prop}={{{prop}}} allowed={{allowed as never}} onTransition={{onTransition}} isPending={{false}} error={{null}} />);",
            f"    await userEvent.selectOptions(screen.getByTestId({q(tid)}), {q(first_to)});",
            f"    await userEvent.click(screen.getByTestId({q(tid + '-submit')}));",
            f"    expect(onTransition).toHaveBeenCalledWith({q(first_to)});",
            "  });\n",
            "  it('explains when no transition is available', () => {",
            f"    renderWithProviders(<{name} {prop}={{{prop}}} allowed={{[]}} onTransition={{vi.fn()}} isPending={{false}} error={{null}} />);",
            "    expect(screen.getByTestId('status-no-transitions')).toBeInTheDocument();",
            f"    expect(screen.queryByTestId({q(tid)})).not.toBeInTheDocument();",
            "  });\n",
            "  it('shows errors from the server', () => {",
            f"    renderWithProviders(<{name} {prop}={{{prop}}} allowed={{allowed as never}} onTransition={{vi.fn()}} isPending={{false}} error=\"Transition rejected\" />);",
            "    expect(screen.getByRole('alert')).toHaveTextContent('Transition rejected');",
            "  });",
            "});",
        ]
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ list / dashboard pages
    def _t_page(self, screen: dict, spec: dict) -> str:
        name = spec["page_component"]
        ent = screen.get("entity")
        tid = page_testid(screen["id"])
        routes: dict[str, list] = {}
        for ref in screen["data_sources"]:
            b = self.binding(ref)
            if b.operation == "list":
                from app.generation.symbols import collection_of

                routes["/" + b.path.strip("/")] = seed_data(self.g).collections.get(collection_of(b.entity_ref), [])
        primary_paths = [p for p in routes][:1] if screen["kind"] == "list" else list(routes)
        lines = [
            "import { screen } from '@testing-library/react';",
            "import { afterEach, describe, expect, it, vi } from 'vitest';",
            f"import {{ {name} }} from '{self._rel(spec['path'], spec['page_path'])}';",
            "import { jsonResponse, renderWithProviders } from './test-utils';",
            f"import type {{ AuthUser }} from '{self._rel(spec['path'], 'src/types/api.ts')}';",
            "",
            f"const data: Record<string, unknown[]> = {json.dumps(routes)};",
            f"const manager = {json.dumps(self.user_obj(self.manager_role(screen)))} as AuthUser;",
            "",
            "function stubApi(overrides: Record<string, () => Promise<Response>> = {}) {",
            "  vi.stubGlobal(",
            "    'fetch',",
            "    vi.fn(async (input: RequestInfo | URL) => {",
            "      const path = new URL(String(input), 'http://localhost').pathname.replace(/^\\/api/, '');",
            "      if (overrides[path]) return overrides[path]();",
            "      return jsonResponse(data[path] ?? []);",
            "    }),",
            "  );",
            "}",
            "",
            "afterEach(() => vi.unstubAllGlobals());",
            "",
            f"describe({q(name)}, () => {{",
            "  it('shows a loading state while data is pending', async () => {",
            "    stubApi(Object.fromEntries(Object.keys(data).map((p) => [p, () => new Promise<Response>(() => undefined)])));",
            f"    renderWithProviders(<{name} />, {{ user: manager }});",
            "    expect(await screen.findByTestId('loading-state')).toBeInTheDocument();",
            "  });\n",
            "  it('shows a recoverable error state when the API fails', async () => {",
            "    stubApi(Object.fromEntries(Object.keys(data).map((p) => [p, async () => jsonResponse({ message: 'boom' }, 500)])));",
            f"    renderWithProviders(<{name} />, {{ user: manager }});",
            "    expect(await screen.findByTestId('error-state')).toBeInTheDocument();",
            "    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();",
            "  });\n",
            "  it('shows an empty state when there is no data', async () => {",
            "    stubApi(Object.fromEntries(Object.keys(data).map((p) => [p, async () => jsonResponse([])])));",
            f"    renderWithProviders(<{name} />, {{ user: manager }});",
            "    expect(await screen.findByTestId('empty-state')).toBeInTheDocument();",
            "  });\n",
            "  it('renders the page when data arrives', async () => {",
            "    stubApi();",
            f"    renderWithProviders(<{name} />, {{ user: manager }});",
            f"    expect(await screen.findByTestId({q(tid)})).toBeInTheDocument();",
        ]
        if screen["kind"] == "list":
            first = routes[primary_paths[0]][0]
            disp = self.display_field(ent)
            lines.append(f"    expect(await screen.findByText({q(str(first[disp]))})).toBeInTheDocument();")
        else:
            lines.append("    expect(await screen.findByTestId('dashboard-stats')).toBeInTheDocument();")
        lines.append("  });")
        for w in self.g.many(screen["actions"]):
            if w["kind"] == "create" and (w.get("trigger") or {}).get("screen") == screen["id"]:
                perm = w["permission"]
                denied = self.denied_role(perm)
                if denied:
                    lines += [
                        "",
                        f"  it('hides {w['name'].lower()} from roles without {perm}', async () => {{",
                        "    stubApi();",
                        f"    renderWithProviders(<{name} />, {{ user: {json.dumps(self.user_obj(denied))} as AuthUser }});",
                        f"    expect(await screen.findByTestId({q(tid)})).toBeInTheDocument();",
                        f"    expect(screen.queryByTestId({q(workflow_testid(w['id']))})).not.toBeInTheDocument();",
                        "  });",
                    ]
                lines += [
                    "",
                    f"  it('shows {w['name'].lower()} to roles that hold {perm}', async () => {{",
                    "    stubApi();",
                    f"    renderWithProviders(<{name} />, {{ user: manager }});",
                    f"    expect(await screen.findByTestId({q(workflow_testid(w['id']))})).toBeInTheDocument();",
                    "  });",
                ]
        lines.append("});")
        return "\n".join(lines) + "\n"

    def manager_role(self, screen: dict) -> str:
        """First role holding every permission the screen needs."""
        from app.validation.permission_validation import role_permissions

        rp = role_permissions(self.g)
        need = set(screen.get("permissions", []))
        for r in self.g.roles:
            if need <= rp[r["key"]]:
                return r["key"]
        return self.g.roles[0]["key"]

    def denied_role(self, perm: str) -> str | None:
        from app.validation.permission_validation import role_permissions

        rp = role_permissions(self.g)
        return next((r["key"] for r in self.g.roles if perm not in rp[r["key"]]), None)
