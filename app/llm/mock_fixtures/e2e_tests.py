"""Playwright fixtures (functional, states, permissions, accessibility, visual) for the MockLLMProvider."""
from __future__ import annotations

import json
import re

from app.domain.models.naming import label_of, page_testid, row_testid, slug, tail, workflow_testid, form_testid
from app.generation.symbols import collection_of, field_label, machine_for_entity, seed_data, state_label
from app.llm.mock_fixtures.unit_tests import UnitTestFixtures, sample_value, too_short
from app.llm.mock_fixtures.tsgen import q
from app.validation.permission_validation import role_permissions

HEADER = "import { expect, loginAs, test } from './support/fixtures';\nimport { installMockApi } from './support/mockApi';\n"


class E2EFixtures(UnitTestFixtures):
    # ---- graph helpers -------------------------------------------------------------------
    def rp(self) -> dict[str, set[str]]:
        return role_permissions(self.g)

    def roles_with(self, perms: list[str]) -> list[str]:
        rp = self.rp()
        return [r["key"] for r in self.g.roles if set(perms) <= rp[r["key"]]]

    def roles_without(self, perm: str) -> list[str]:
        return [r["key"] for r in self.g.roles if perm not in self.rp()[r["key"]]]

    def concrete_route(self, screen: dict) -> str:
        r = screen["route"]
        if ":id" in r and screen.get("entity"):
            rows = seed_data(self.g).collections.get(collection_of(screen["entity"]), [])
            r = r.replace(":id", rows[0]["id"] if rows else "missing")
        return r

    def url_pattern(self, route: str) -> str:
        return f"new RegExp({q('^https?://[^/]+' + re.escape(route) + '(?:[?#].*)?$')})"

    def e2e(self, spec: dict) -> str:
        kind = spec["kind"]
        if kind == "workflow":
            wf = self.g.require(spec["workflow_ref"])
            return getattr(self, f"_e_{wf['kind']}")(wf)
        return getattr(self, f"_e_{kind}")()

    # ---- navigation ----------------------------------------------------------------------
    def _e_navigation(self) -> str:
        screens = []
        for s in self.g.screens:
            roles = self.roles_with(s.get("permissions", [])) if s["layout"] == "authenticated" else []
            screens.append({"id": s["id"], "route": self.concrete_route(s), "layout": s["layout"], "testid": page_testid(s["id"]), "roles": roles})
        login = next((s for s in self.g.screens if s["layout"] == "public"), None)
        nav = [{"label": s["name"], "route": s["route"], "permissions": s.get("permissions", [])} for s in self.g.screens if s.get("nav")]
        nav_expect = {r["key"]: [n["label"] for n in nav if set(n["permissions"]) <= self.rp()[r["key"]]] for r in self.g.roles}
        nav_hidden = {r["key"]: [n["label"] for n in nav if not set(n["permissions"]) <= self.rp()[r["key"]]] for r in self.g.roles}
        login_route = login["route"] if login else "/login"
        first_auth = next(s for s in self.g.screens if s["layout"] == "authenticated")
        return HEADER + f"""
const SCREENS = {json.dumps(screens, indent=2)};
const NAV_VISIBLE: Record<string, string[]> = {json.dumps(nav_expect)};
const NAV_HIDDEN: Record<string, string[]> = {json.dumps(nav_hidden)};

for (const screen of SCREENS) {{
  if (screen.layout === 'public') {{
    test(`${{screen.id}} loads without a session`, async ({{ page }}) => {{
      await installMockApi(page);
      await page.goto(screen.route);
      await expect(page.getByTestId(screen.testid)).toBeVisible();
      await expect(page.getByRole('heading', {{ level: 1 }})).toHaveCount(1);
    }});
    continue;
  }}
  for (const role of screen.roles) {{
    test(`${{screen.id}} loads for ${{role}}`, async ({{ page }}) => {{
      await installMockApi(page);
      await loginAs(page, role);
      await page.goto(screen.route);
      await expect(page.getByTestId(screen.testid)).toBeVisible();
      await expect(page.getByRole('heading', {{ level: 1 }}).first()).toBeVisible();
    }});
  }}
}}

test('unauthenticated visitors are sent to the sign in screen', async ({{ page }}) => {{
  await installMockApi(page);
  await page.goto({q(self.concrete_route(first_auth))});
  await expect(page).toHaveURL({self.url_pattern(login_route)});
}});

for (const [role, visible] of Object.entries(NAV_VISIBLE)) {{
  test(`navigation shows only permitted items for ${{role}}`, async ({{ page }}) => {{
    await installMockApi(page);
    await loginAs(page, role);
    await page.goto({q(self.concrete_route(first_auth))});
    const nav = page.getByRole('navigation', {{ name: 'Primary', exact: true }});
    for (const label of visible) await expect(nav.getByRole('link', {{ name: label, exact: true }})).toBeVisible();
    for (const label of NAV_HIDDEN[role]) await expect(nav.getByRole('link', {{ name: label, exact: true }})).toHaveCount(0);
  }});
}}

test('unknown routes show a helpful not-found page', async ({{ page }}) => {{
  await installMockApi(page);
  await loginAs(page, {q(self.g.roles[0]['key'])});
  await page.goto('/this-route-does-not-exist');
  await expect(page.getByTestId('page-not-found')).toBeVisible();
}});
"""

    # ---- login ---------------------------------------------------------------------------
    def _e_login(self, wf: dict) -> str:
        from app.generation.symbols import collection_of as _c

        acs = [a for a in self.g.nodes("acceptance_criteria") if a["workflow"] == wf["id"]]
        screen = self.g.require(wf["screen"])
        ent = wf["entity"]
        fields = wf["form_fields"]
        dest = self.g.require(wf["success"]["navigate"])
        creds = seed_data(self.g).credentials
        out = [HEADER.replace("expect, loginAs, test", "expect, test"), ""]
        for ac in acs:
            role = (ac.get("role") or "role.manager").split(".", 1)[1]
            cred = next(c for c in creds if c["role"] == role)
            out.append(f"test({q(ac['id'] + ': ' + ac['title'])}, async ({{ page }}) => {{")
            out.append("  await installMockApi(page);")
            out.append(f"  await page.goto({q(screen['route'])});")
            for f in fields:
                val = cred["email"] if f == "email" else cred["password"] if f == "password" else sample_value(self.g, ent, f)
                out.append(f"  await page.getByLabel({q(field_label(self.g, ent, f))}).fill({q(val)});")
            out.append(f"  await page.getByRole('button', {{ name: {q(wf['submit_label'])} }}).click();")
            out.append(f"  await expect(page).toHaveURL({self.url_pattern(dest['route'])});")
            out.append(f"  await expect(page.getByTestId({q(page_testid(dest['id']))})).toBeVisible();")
            out.append("  await expect(page.getByTestId('current-user')).not.toBeEmpty();")
            out.append("});\n")
        fnames = [(f, field_label(self.g, ent, f)) for f in fields]
        out.append(f"test('{wf['id']}: wrong credentials are rejected with a clear message', async ({{ page }}) => {{")
        out.append("  await installMockApi(page);")
        out.append(f"  await page.goto({q(screen['route'])});")
        for f, lab in fnames:
            val = "nobody@example.com" if f == "email" else "WrongPassword1!" if f == "password" else sample_value(self.g, ent, f)
            out.append(f"  await page.getByLabel({q(lab)}).fill({q(val)});")
        out.append(f"  await page.getByRole('button', {{ name: {q(wf['submit_label'])} }}).click();")
        out.append("  await expect(page.getByTestId('form-error')).toContainText('Invalid email or password');")
        out.append(f"  await expect(page).toHaveURL({self.url_pattern(screen['route'])});")
        out.append("});\n")
        first_req = next((f for f in fields if self.is_required(ent, f)), None)
        if first_req:
            custom = next((v.get("message") for v in self.g.validations_for(ent, first_req) if v.get("message")), None)
            out.append(f"test('{wf['id']}: empty submission shows validation errors without calling the API', async ({{ page }}) => {{")
            out.append("  const api = await installMockApi(page);")
            out.append(f"  await page.goto({q(screen['route'])});")
            out.append(f"  await page.getByRole('button', {{ name: {q(wf['submit_label'])} }}).click();")
            out.append(f"  await expect(page.getByText({q(custom or field_label(self.g, ent, first_req) + ' is required')})).toBeVisible();")
            out.append(f"  expect(api.calls.filter((c) => c.api === {q(wf['api'])})).toHaveLength(0);")
            out.append("});\n")
        out.append(f"test('{wf['id']}: network failure is reported without technical detail', async ({{ page }}) => {{")
        out.append(f"  await installMockApi(page, {{ failures: {{ {q(wf['api'])}: 0 }} }});")
        out.append(f"  await page.goto({q(screen['route'])});")
        for f, lab in fnames:
            val = creds[0]["email"] if f == "email" else creds[0]["password"] if f == "password" else sample_value(self.g, ent, f)
            out.append(f"  await page.getByLabel({q(lab)}).fill({q(val)});")
        out.append(f"  await page.getByRole('button', {{ name: {q(wf['submit_label'])} }}).click();")
        out.append("  await expect(page.getByTestId('form-error')).toContainText('Unable to reach the server');")
        out.append("});\n")
        out.append("test('signing out returns to the sign in screen and protects the app again', async ({ page }) => {")
        out.append("  await installMockApi(page);")
        out.append(f"  await page.goto({q(screen['route'])});")
        for f in fields:
            val = creds[0]["email"] if f == "email" else creds[0]["password"] if f == "password" else sample_value(self.g, ent, f)
            out.append(f"  await page.getByLabel({q(field_label(self.g, ent, f))}).fill({q(val)});")
        out.append(f"  await page.getByRole('button', {{ name: {q(wf['submit_label'])} }}).click();")
        out.append(f"  await expect(page).toHaveURL({self.url_pattern(dest['route'])});")
        out.append("  await page.getByRole('button', { name: 'Sign out' }).click();")
        out.append(f"  await expect(page).toHaveURL({self.url_pattern(screen['route'])});")
        out.append(f"  await page.goto({q(dest['route'])});")
        out.append(f"  await expect(page).toHaveURL({self.url_pattern(screen['route'])});")
        out.append("});")
        return "\n".join(out) + "\n"

    # ---- create ---------------------------------------------------------------------------
    def _fill_form(self, wf: dict, values: dict[str, str], indent: str = "  ") -> list[str]:
        ent = wf["entity"]
        lines = []
        for f in wf["form_fields"]:
            fd = self.g.entity_field(ent, f)
            lab = field_label(self.g, ent, f)
            if fd["type"] == "ref" and self.is_required(ent, f):
                lines.append(f"{indent}await form.getByLabel({q(lab)}).selectOption({{ index: 1 }});")
            elif f in values:
                lines.append(f"{indent}await form.getByLabel({q(lab)}).fill({q(values[f])});")
        return lines

    def _e_create(self, wf: dict) -> str:
        ent = wf["entity"]
        acs = [a for a in self.g.nodes("acceptance_criteria") if a["workflow"] == wf["id"]]
        trig_screen = self.g.require(wf["trigger"]["screen"])
        form_screen = self.g.require(wf["screen"])
        disp = self.display_field(ent)
        tid, fid = workflow_testid(wf["id"]), form_testid(wf["id"])
        target = self.g.require((wf.get("success") or {}).get("navigate") or trig_screen["id"])
        notice = (wf.get("success") or {}).get("notification")
        title_val = sample_value(self.g, ent, disp) + " E2E"
        title_val = title_val[: 60]
        values = {f: sample_value(self.g, ent, f) for f in wf["form_fields"] if self.is_required(ent, f) or f == disp}
        values[disp] = title_val
        role_ok = (self.roles_with([wf["permission"]]) or [self.g.roles[0]["key"]])[0]
        out = [HEADER, ""]
        done_types = set()
        for ac in acs:
            role = (ac.get("role") or f"role.{role_ok}").split(".", 1)[1]
            t = ac["type"]
            done_types.add(t)
            out.append(f"test({q(ac['id'] + ': ' + ac['title'])}, async ({{ page }}) => {{")
            if t == "workflow_success":
                out.append("  const api = await installMockApi(page);")
                out.append(f"  await loginAs(page, {q(role)});")
                out.append(f"  await page.goto({q(self.concrete_route(trig_screen))});")
                out.append(f"  await page.getByTestId({q(tid)}).click();")
                out.append(f"  await expect(page).toHaveURL({self.url_pattern(form_screen['route'])});")
                out.append(f"  const form = page.getByTestId({q(fid)});")
                out.extend(self._fill_form(wf, values))
                out.append(f"  await form.getByRole('button', {{ name: {q(wf['submit_label'])} }}).click();")
                out.append(f"  await expect(page).toHaveURL({self.url_pattern(target['route'])});")
                if notice:
                    out.append(f"  await expect(page.getByRole('status').filter({{ hasText: {q(notice)} }})).toBeVisible();")
                out.append(f"  await expect(page.getByText({q(title_val)})).toBeVisible();")
                out.append(f"  const created = api.calls.find((c) => c.api === {q(wf['api'])});")
                out.append(f"  expect(created?.body).toMatchObject({{ {q(disp)}: {q(title_val)} }});")
                bind = self.binding(wf["api"])
                for sf in bind.session_fields:
                    out.append(f"  expect(created?.body?.{sf['name']}).toBe('user-{role}');")
            elif t == "validation_failure":
                fld = ac.get("field") or next((f for f in wf["form_fields"] if too_short(self.g, ent, f)), None)
                ts = too_short(self.g, ent, fld) if fld else None
                out.append("  const api = await installMockApi(page);")
                out.append(f"  await loginAs(page, {q(role)});")
                out.append(f"  await page.goto({q(form_screen['route'])});")
                out.append(f"  const form = page.getByTestId({q(fid)});")
                if ts:
                    out.append(f"  await form.getByLabel({q(field_label(self.g, ent, fld))}).fill({q(ts[0])});")
                out.append(f"  await form.getByRole('button', {{ name: {q(wf['submit_label'])} }}).click();")
                out.append(f"  await expect(form.getByText(/{'at least ' + str(ts[1]) + ' characters' if ts else 'required'}/)).toBeVisible();")
                out.append(f"  expect(api.calls.filter((c) => c.api === {q(wf['api'])})).toHaveLength(0);")
                out.append(f"  await expect(page).toHaveURL({self.url_pattern(form_screen['route'])});")
            elif t == "workflow_denied":
                out.append("  await installMockApi(page);")
                out.append(f"  await loginAs(page, {q(role)});")
                out.append(f"  await page.goto({q(self.concrete_route(trig_screen))});")
                out.append(f"  await expect(page.getByTestId({q(page_testid(trig_screen['id']))})).toBeVisible();")
                out.append(f"  await expect(page.getByTestId({q(tid)})).toHaveCount(0);")
                out.append(f"  await page.goto({q(form_screen['route'])});")
                out.append("  await expect(page.getByTestId('access-denied')).toBeVisible();")
            else:
                out.append("  test.skip(true, 'acceptance type not applicable to create workflows');")
            out.append("});\n")
        # generic resilience tests derived from api.json error codes
        out.append(f"test('{wf['id']}: server errors are shown to the user and keep the entered data', async ({{ page }}) => {{")
        out.append(f"  await installMockApi(page, {{ failures: {{ {q(wf['api'])}: 500 }} }});")
        out.append(f"  await loginAs(page, {q(role_ok)});")
        out.append(f"  await page.goto({q(form_screen['route'])});")
        out.append(f"  const form = page.getByTestId({q(fid)});")
        out.extend(self._fill_form(wf, values))
        out.append(f"  await form.getByRole('button', {{ name: {q(wf['submit_label'])} }}).click();")
        out.append("  await expect(page.getByTestId('form-error')).toBeVisible();")
        out.append("  await expect(page.getByTestId('form-error')).not.toContainText(/stack|exception|undefined/i);")
        out.append(f"  await expect(form.getByLabel({q(field_label(self.g, ent, disp))})).toHaveValue({q(title_val)});")
        out.append("});\n")
        out.append(f"test('{wf['id']}: backend validation errors (422) are attached to the fields', async ({{ page }}) => {{")
        out.append(f"  await installMockApi(page, {{ failures: {{ {q(wf['api'])}: 422 }} }});")
        out.append(f"  await loginAs(page, {q(role_ok)});")
        out.append(f"  await page.goto({q(form_screen['route'])});")
        out.append(f"  const form = page.getByTestId({q(fid)});")
        out.extend(self._fill_form(wf, values))
        out.append(f"  await form.getByRole('button', {{ name: {q(wf['submit_label'])} }}).click();")
        out.append("  await expect(page.getByTestId('form-error')).toBeVisible();")
        out.append("});\n")
        out.append(f"test('{wf['id']}: cancel returns to the previous screen without saving', async ({{ page }}) => {{")
        out.append("  const api = await installMockApi(page);")
        out.append(f"  await loginAs(page, {q(role_ok)});")
        out.append(f"  await page.goto({q(form_screen['route'])});")
        out.append("  await page.getByRole('button', { name: 'Cancel' }).click();")
        out.append(f"  await expect(page).toHaveURL({self.url_pattern(trig_screen['route'])});")
        out.append(f"  expect(api.calls.filter((c) => c.api === {q(wf['api'])})).toHaveLength(0);")
        out.append("});")
        return "\n".join(out) + "\n"

    # ---- delete ---------------------------------------------------------------------------
    def _e_delete(self, wf: dict) -> str:
        ent = wf["entity"]
        acs = [a for a in self.g.nodes("acceptance_criteria") if a["workflow"] == wf["id"]]
        screen = self.g.require(wf["trigger"]["screen"])
        rows = seed_data(self.g).collections[collection_of(ent)]
        disp = self.display_field(ent)
        tid = workflow_testid(wf["id"])
        rid = row_testid(ent) + "-" + rows[0]["id"]
        notice = (wf.get("success") or {}).get("notification")
        role_ok = (self.roles_with([wf["permission"]]) or [self.g.roles[0]["key"]])[0]
        denied = self.roles_without(wf["permission"])
        out = [HEADER, ""]
        for ac in acs:
            role = (ac.get("role") or f"role.{role_ok}").split(".", 1)[1]
            out.append(f"test({q(ac['id'] + ': ' + ac['title'])}, async ({{ page }}) => {{")
            if ac["type"] == "workflow_denied":
                out.append("  await installMockApi(page);")
                out.append(f"  await loginAs(page, {q(role)});")
                out.append(f"  await page.goto({q(screen['route'])});")
                out.append(f"  await expect(page.getByTestId({q(rid)})).toBeVisible();")
                out.append(f"  await expect(page.getByTestId({q(tid)})).toHaveCount(0);")
            else:
                out.append("  const api = await installMockApi(page);")
                out.append(f"  await loginAs(page, {q(role)});")
                out.append(f"  await page.goto({q(screen['route'])});")
                out.append(f"  const row = page.getByTestId({q(rid)});")
                out.append("  await expect(row).toBeVisible();")
                out.append(f"  await row.getByTestId({q(tid)}).click();")
                out.append("  const dialog = page.getByRole('dialog');")
                out.append("  await expect(dialog).toBeVisible();")
                out.append(f"  await dialog.getByTestId({q('confirm-' + tid)}).click();")
                out.append("  await expect(dialog).toHaveCount(0);")
                out.append(f"  await expect(page.getByTestId({q(rid)})).toHaveCount(0);")
                if notice:
                    out.append(f"  await expect(page.getByRole('status').filter({{ hasText: {q(notice)} }})).toBeVisible();")
                out.append(f"  expect(api.calls.filter((c) => c.api === {q(wf['api'])})).toHaveLength(1);")
            out.append("});\n")
        out.append(f"test('{wf['id']}: the confirmation dialog traps focus, closes on Escape and keeps the item', async ({{ page }}) => {{")
        out.append("  const api = await installMockApi(page);")
        out.append(f"  await loginAs(page, {q(role_ok)});")
        out.append(f"  await page.goto({q(screen['route'])});")
        out.append(f"  const trigger = page.getByTestId({q(rid)}).getByTestId({q(tid)});")
        out.append("  await trigger.focus();")
        out.append("  await trigger.press('Enter');")
        out.append("  const dialog = page.getByRole('dialog');")
        out.append("  await expect(dialog).toBeVisible();")
        out.append("  await expect(dialog.getByRole('button').first()).toBeFocused();")
        out.append("  for (let i = 0; i < 4; i++) await page.keyboard.press('Tab');")
        out.append("  expect(await dialog.evaluate((d) => d.contains(document.activeElement))).toBe(true);")
        out.append("  await page.keyboard.press('Escape');")
        out.append("  await expect(dialog).toHaveCount(0);")
        out.append("  await expect(trigger).toBeFocused();")
        out.append(f"  await expect(page.getByTestId({q(rid)})).toBeVisible();")
        out.append(f"  expect(api.calls.filter((c) => c.api === {q(wf['api'])})).toHaveLength(0);")
        out.append("});\n")
        out.append(f"test('{wf['id']}: a failing delete is explained inside the dialog', async ({{ page }}) => {{")
        out.append(f"  await installMockApi(page, {{ failures: {{ {q(wf['api'])}: 409 }} }});")
        out.append(f"  await loginAs(page, {q(role_ok)});")
        out.append(f"  await page.goto({q(screen['route'])});")
        out.append(f"  await page.getByTestId({q(rid)}).getByTestId({q(tid)}).click();")
        out.append(f"  await page.getByRole('dialog').getByTestId({q('confirm-' + tid)}).click();")
        out.append("  await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible();")
        out.append(f"  await expect(page.getByTestId({q(rid)})).toBeVisible();")
        out.append("});")
        return "\n".join(out) + "\n"

    # ---- transition -----------------------------------------------------------------------
    def expected_transitions(self, sm: dict, row: dict, role: str) -> list[str]:
        rp = self.rp()[role]
        out = []
        for t in sm["transitions"]:
            if t["from"] != row[sm["field"]]:
                continue
            perm = t.get("permission")
            if perm and perm not in rp:
                continue
            cond = ((self.g.get(perm) or {}).get("conditions") or {}).get(f"role.{role}") if perm else None
            if cond and row.get(cond["field"]) != f"user-{role}":
                continue
            out.append(t["to"])
        return out

    def _e_transition(self, wf: dict) -> str:
        sm = self.g.require(wf["state_machine"])
        ent = wf["entity"]
        screen = self.g.require(wf["trigger"]["screen"])
        rows = seed_data(self.g).collections[collection_of(ent)]
        tid = workflow_testid(wf["id"])
        notice = (wf.get("success") or {}).get("notification")
        badge_state = lambda s: state_label(s)
        acs = [a for a in self.g.nodes("acceptance_criteria") if a["workflow"] == wf["id"]]
        out = [HEADER, ""]
        for ac in acs:
            role = (ac.get("role") or "role.manager").split(".", 1)[1]
            if ac["type"] == "transition_allowed":
                frm, to = ac["transition"]["from"], ac["transition"]["to"]
                row = next((r for r in rows if r[sm["field"]] == frm and to in self.expected_transitions(sm, r, role)), None)
                if not row:
                    continue
                out.append(f"test({q(ac['id'] + ': ' + ac['title'])}, async ({{ page }}) => {{")
                out.append("  const api = await installMockApi(page);")
                out.append(f"  await loginAs(page, {q(role)});")
                out.append(f"  await page.goto({q(screen['route'].replace(':id', row['id']))});")
                out.append(f"  await expect(page.getByTestId({q(page_testid(screen['id']))})).toBeVisible();")
                out.append(f"  await page.getByTestId({q(tid)}).selectOption({q(to)});")
                out.append(f"  await page.getByTestId({q(tid + '-submit')}).click();")
                if notice:
                    out.append(f"  await expect(page.getByRole('status').filter({{ hasText: {q(notice)} }})).toBeVisible();")
                out.append(f"  await expect(page.getByText({q(badge_state(to))}, {{ exact: true }}).first()).toBeVisible();")
                out.append(f"  expect(api.calls.find((c) => c.api === {q(wf['api'])})?.body).toEqual({{ {q(sm['field'])}: {q(to)} }});")
                out.append("});\n")
            elif ac["type"] == "transition_denied":
                row = next((r for r in rows if not self.expected_transitions(sm, r, role)), None)
                if not row:
                    continue
                out.append(f"test({q(ac['id'] + ': ' + ac['title'])}, async ({{ page }}) => {{")
                out.append("  await installMockApi(page);")
                out.append(f"  await loginAs(page, {q(role)});")
                out.append(f"  await page.goto({q(screen['route'].replace(':id', row['id']))});")
                out.append(f"  await expect(page.getByTestId({q(page_testid(screen['id']))})).toBeVisible();")
                out.append("  await expect(page.getByTestId('status-no-transitions')).toBeVisible();")
                out.append(f"  await expect(page.getByTestId({q(tid)})).toHaveCount(0);")
                out.append("});\n")
        # exhaustive matrix: every seeded row x every role must offer exactly the graph-permitted transitions
        matrix = []
        for r in rows:
            for role in [x["key"] for x in self.g.roles]:
                matrix.append({"id": r["id"], "role": role, "expected": self.expected_transitions(sm, r, role)})
        out.append(f"const MATRIX: Array<{{ id: string; role: string; expected: string[] }}> = {json.dumps(matrix)};")
        out.append("for (const c of MATRIX) {")
        out.append(f"  test(`{wf['id']} offers only graph-defined transitions: ${{c.id}} as ${{c.role}} -> [${{c.expected.join(', ')}}]`, async ({{ page }}) => {{")
        out.append("    await installMockApi(page);")
        out.append("    await loginAs(page, c.role);")
        out.append(f"    await page.goto(`{screen['route'].replace(':id', '${c.id}')}`);")
        out.append(f"    await expect(page.getByTestId({q(page_testid(screen['id']))})).toBeVisible();")
        out.append("    if (c.expected.length === 0) {")
        out.append("      await expect(page.getByTestId('status-no-transitions')).toBeVisible();")
        out.append("    } else {")
        out.append(f"      const values = await page.getByTestId({q(tid)}).locator('option').evaluateAll((os) => os.map((o) => (o as HTMLOptionElement).value));")
        out.append("      expect(values).toEqual(['', ...c.expected]);")
        out.append("    }")
        out.append("  });")
        out.append("}\n")
        role_ok = (self.roles_with([wf["permission"]]) or [self.g.roles[0]["key"]])[0]
        row0 = next((r for r in rows if self.expected_transitions(sm, r, role_ok)), rows[0])
        to0 = (self.expected_transitions(sm, row0, role_ok) or [sm["states"][0]])[0]
        out.append(f"test('{wf['id']}: a rejected transition (409) is explained and the status stays', async ({{ page }}) => {{")
        out.append(f"  await installMockApi(page, {{ failures: {{ {q(wf['api'])}: 409 }} }});")
        out.append(f"  await loginAs(page, {q(role_ok)});")
        out.append(f"  await page.goto({q(screen['route'].replace(':id', row0['id']))});")
        out.append(f"  await page.getByTestId({q(tid)}).selectOption({q(to0)});")
        out.append(f"  await page.getByTestId({q(tid + '-submit')}).click();")
        out.append("  await expect(page.getByRole('alert').filter({ hasText: /conflict|refresh|Injected/i })).toBeVisible();")
        out.append(f"  await expect(page.getByText({q(badge_state(row0[sm['field']]))}, {{ exact: true }}).first()).toBeVisible();")
        out.append("});")
        return "\n".join(out) + "\n"

    # ---- states ---------------------------------------------------------------------------
    def _e_states(self) -> str:
        cases = []
        for s in self.g.screens:
            if not s.get("data_sources"):
                continue
            role = (self.roles_with(s.get("permissions", [])) or [self.g.roles[0]["key"]])[0]
            lists = [self.binding(r) for r in s["data_sources"]]
            primary = next((b for b in lists if b.operation in ("list", "get") and b.entity_ref == s.get("entity")), lists[0])
            from app.generation.project_generator import find_user_entity

            ue = find_user_entity(self.g)
            cols = sorted({collection_of(b.entity_ref) for b in lists if b.operation == "list"} - ({collection_of(ue["id"])} if ue else set()))  # the signed-in user must keep existing
            cases.append({
                "id": s["id"], "route": self.concrete_route(s), "role": role, "testid": page_testid(s["id"]), "kind": s["kind"],
                "apis": s["data_sources"], "primary": primary.id, "collections": cols,
            })
        return HEADER + f"""
const CASES = {json.dumps(cases, indent=2)};

for (const c of CASES) {{
  test(`${{c.id}} shows a loading state while data is pending`, async ({{ page }}) => {{
    await installMockApi(page, {{ delays: Object.fromEntries(c.apis.map((a: string) => [a, 1500])) }});
    await loginAs(page, c.role);
    await page.goto(c.route);
    await expect(page.getByTestId('loading-state').first()).toBeVisible();
    await expect(page.getByTestId(c.testid)).toBeVisible();
  }});

  test(`${{c.id}} shows a recoverable error state and recovers on retry`, async ({{ page }}) => {{
    const failures: Record<string, number> = {{ [c.primary]: 500 }};
    await installMockApi(page, {{ failures }});
    await loginAs(page, c.role);
    await page.goto(c.route);
    await expect(page.getByTestId('error-state').first()).toBeVisible();
    await expect(page.getByTestId('error-state').first()).not.toContainText(/stack|exception|TypeError/i);
    delete failures[c.primary];
    await page.getByRole('button', {{ name: 'Retry' }}).first().click();
    await expect(page.getByTestId('error-state')).toHaveCount(0);
  }});

  if (c.kind === 'list' || c.kind === 'dashboard') {{
    test(`${{c.id}} shows an empty state when there is no data`, async ({{ page }}) => {{
      await installMockApi(page, {{ db: Object.fromEntries(c.collections.map((k: string) => [k, []])) }});
      await loginAs(page, c.role);
      await page.goto(c.route);
      await expect(page.getByTestId('empty-state')).toBeVisible();
    }});
  }}

  if (c.kind === 'details') {{
    test(`${{c.id}} explains a missing item (404)`, async ({{ page }}) => {{
      await installMockApi(page, {{ failures: {{ [c.primary]: 404 }} }});
      await loginAs(page, c.role);
      await page.goto(c.route);
      await expect(page.getByTestId('error-state')).toBeVisible();
    }});
  }}
}}
"""

    # ---- permissions ----------------------------------------------------------------------
    def _e_permissions(self) -> str:
        triggers, gated, matrix = [], [], []
        for w in self.g.workflows:
            if w["kind"] in ("create", "delete") and w.get("permission"):
                scr = self.g.require(w["trigger"]["screen"])
                for r in self.roles_without(w["permission"]):
                    triggers.append({"workflow": w["id"], "role": r, "route": self.concrete_route(scr), "testid": workflow_testid(w["id"]), "page": page_testid(scr["id"])})
        for s in self.g.screens:
            if s["layout"] == "authenticated" and s.get("permissions"):
                for r in self.g.roles:
                    if not set(s["permissions"]) <= self.rp()[r["key"]]:
                        gated.append({"screen": s["id"], "role": r["key"], "route": self.concrete_route(s)})
        target_screen = next(x for x in self.g.screens if x["layout"] == "authenticated" and any(self.binding(r).operation == "list" for r in x.get("data_sources", [])))
        target_api = next(r for r in target_screen["data_sources"] if self.binding(r).operation == "list")
        target_role = (self.roles_with(target_screen.get("permissions", [])) or [self.g.roles[0]["key"]])[0]
        return HEADER + f"""
const HIDDEN_TRIGGERS = {json.dumps(triggers, indent=2)};
const GATED_SCREENS = {json.dumps(gated, indent=2)};

for (const c of HIDDEN_TRIGGERS) {{
  test(`${{c.workflow}} is not offered to ${{c.role}}`, async ({{ page }}) => {{
    await installMockApi(page);
    await loginAs(page, c.role);
    await page.goto(c.route);
    await expect(page.getByTestId(c.page)).toBeVisible();
    await expect(page.getByTestId(c.testid)).toHaveCount(0);
  }});
}}

for (const c of GATED_SCREENS) {{
  test(`${{c.screen}} shows an access-denied message to ${{c.role}} (UI only; the backend enforces access)`, async ({{ page }}) => {{
    await installMockApi(page);
    await loginAs(page, c.role);
    await page.goto(c.route);
    await expect(page.getByTestId('access-denied')).toBeVisible();
  }});
}}

test('a 403 from the backend is reported as a permission problem', async ({{ page }}) => {{
  await installMockApi(page, {{ failures: {{ {q(target_api)}: 403 }} }});
  await loginAs(page, {q(target_role)});
  await page.goto({q(self.concrete_route(target_screen))});
  await expect(page.getByTestId('error-state').first()).toContainText(/permission/i);
}});
"""

    # ---- accessibility --------------------------------------------------------------------
    def _e_accessibility(self) -> str:
        cases = []
        for s in self.g.screens:
            role = (self.roles_with(s.get("permissions", [])) or [self.g.roles[0]["key"]])[0] if s["layout"] == "authenticated" else None
            cases.append({"id": s["id"], "route": self.concrete_route(s), "role": role, "testid": page_testid(s["id"])})
        return """import AxeBuilder from '@axe-core/playwright';
import { expect, loginAs, test } from './support/fixtures';
import { installMockApi } from './support/mockApi';

const CASES = %s;

for (const c of CASES) {
  test(`[a11y] ${c.id} has no serious or critical WCAG A/AA violations`, async ({ page }) => {
    await installMockApi(page);
    if (c.role) await loginAs(page, c.role);
    await page.goto(c.route);
    await expect(page.getByTestId(c.testid)).toBeVisible();
    await page.waitForLoadState('networkidle');
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
    const blocking = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
    expect(
      blocking.map((v) => `${v.id}: ${v.help} (${v.nodes.length} nodes, e.g. ${v.nodes[0]?.target.join(' ')})`),
      'ACCESSIBILITY_ERROR',
    ).toEqual([]);
  });
}

test('[a11y] interactive controls are reachable and visibly focused with the keyboard', async ({ page }) => {
  await installMockApi(page);
  await page.goto(CASES[0].route);
  await page.keyboard.press('Tab');
  const focused = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return null;
    const cs = getComputedStyle(el);
    return { tag: el.tagName, outline: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0 };
  });
  expect(focused, 'ACCESSIBILITY_ERROR: nothing received focus on Tab').not.toBeNull();
  expect(focused?.outline, 'ACCESSIBILITY_ERROR: focused element has no visible focus indicator').toBe(true);
});
""" % json.dumps(cases, indent=2)

    # ---- visual ---------------------------------------------------------------------------
    def visual(self, spec: dict) -> str:
        vps = spec.get("viewports") or {"desktop": {"width": 1280, "height": 800}, "tablet": {"width": 820, "height": 1180}, "mobile": {"width": 390, "height": 844}}
        screens = []
        for s in self.g.screens:
            role = (self.roles_with(s.get("permissions", [])) or [self.g.roles[0]["key"]])[0] if s["layout"] == "authenticated" else None
            screens.append({"id": s["id"], "route": self.concrete_route(s), "role": role, "testid": page_testid(s["id"])})
        dialogs = []
        for w in self.g.workflows:
            if w["kind"] == "delete" and w.get("trigger", {}).get("screen"):
                scr = self.g.require(w["trigger"]["screen"])
                rows = seed_data(self.g).collections[collection_of(w["entity"])]
                dialogs.append({"id": scr["id"] + ".dialog", "route": self.concrete_route(scr), "role": (self.roles_with([w["permission"]]) or [self.g.roles[0]["key"]])[0],
                                "row": row_testid(w["entity"]) + "-" + rows[0]["id"], "trigger": workflow_testid(w["id"])})
        return """import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { expect, loginAs, test } from '../e2e/support/fixtures';
import { installMockApi } from '../e2e/support/mockApi';

const OUT = process.env.SCREENSHOT_DIR ?? path.resolve(process.cwd(), '../frontend-artifacts/screenshots');
const VIEWPORTS = %(vps)s;
const SCREENS: Array<{ id: string; route: string; role: string | null; testid: string }> = %(screens)s;
const DIALOGS: Array<{ id: string; route: string; role: string; row: string; trigger: string }> = %(dialogs)s;

/* Runs in the browser: collects objective layout defects for the vision model and the deterministic checks. */
function measureLayout() {
  const vw = window.innerWidth;
  const sel = (el: Element) => {
    const t = el.getAttribute('data-testid');
    return t ? `[data-testid="${t}"]` : el.tagName.toLowerCase() + (el.id ? `#${el.id}` : '') + (typeof el.className === 'string' && el.className ? '.' + el.className.split(' ').slice(0, 2).join('.') : '');
  };
  const visible = (el: Element) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && !(r.width <= 1 && r.height <= 1);
  };
  const scrollsHorizontally = (el: Element | null): boolean => {
    for (let n = el; n && n !== document.body; n = n.parentElement) {
      const o = getComputedStyle(n).overflowX;
      if (o === 'auto' || o === 'scroll' || o === 'hidden') return true;
    }
    return false;
  };
  const all = Array.from(document.body.querySelectorAll('*')).filter(visible);
  const overflowing = all
    .filter((el) => el.getBoundingClientRect().right > vw + 1 && !scrollsHorizontally(el.parentElement) && getComputedStyle(el).position !== 'fixed')
    .slice(0, 8)
    .map((el) => ({ selector: sel(el), right: Math.round(el.getBoundingClientRect().right), width: Math.round(el.getBoundingClientRect().width) }));
  const clipped = all
    .filter((el) => {
      const cs = getComputedStyle(el);
      return el.children.length === 0 && (el.textContent ?? '').trim().length > 0 && (cs.overflow === 'hidden' || cs.textOverflow === 'ellipsis') && el.scrollWidth > el.clientWidth + 1;
    })
    .slice(0, 8)
    .map((el) => ({ selector: sel(el), text: (el.textContent ?? '').trim().slice(0, 60) }));
  const interactive = all.filter((el) => el.matches('a[href], button, input:not([type=hidden]), select, textarea, [role=tab], [role=menuitem]'));
  const smallTargets = interactive
    .filter((el) => { const r = el.getBoundingClientRect(); return r.width < 24 || r.height < 24; })
    .slice(0, 8)
    .map((el) => ({ selector: sel(el), width: Math.round(el.getBoundingClientRect().width), height: Math.round(el.getBoundingClientRect().height) }));
  const overlaps: Array<{ a: string; b: string }> = [];
  const dialogEl = document.querySelector('[role=dialog]');
  const checkable = dialogEl ? interactive.filter((el) => dialogEl.contains(el)) : interactive; // content behind a modal is covered on purpose
  for (let i = 0; i < checkable.length && overlaps.length < 6; i++) {
    for (let j = i + 1; j < checkable.length && overlaps.length < 6; j++) {
      const a = checkable[i], b = checkable[j];
      if (a.contains(b) || b.contains(a)) continue;
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      const w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
      const h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
      if (w > 4 && h > 4) overlaps.push({ a: sel(a), b: sel(b) });
    }
  }
  const main = document.querySelector('main');
  const dialog = document.querySelector('[role=dialog]');
  const dr = dialog?.getBoundingClientRect();
  const tables = Array.from(document.querySelectorAll('table')).filter(visible).map((t) => ({ selector: sel(t), overflows: t.getBoundingClientRect().right > vw + 1 || t.scrollWidth > (t.parentElement?.clientWidth ?? vw) + 1 }));
  return {
    viewport: { width: vw, height: window.innerHeight },
    horizontalOverflow: document.documentElement.scrollWidth > vw + 1,
    documentWidth: document.documentElement.scrollWidth,
    overflowingElements: overflowing,
    clippedText: clipped,
    smallTargets,
    overlappingControls: overlaps,
    h1Count: document.querySelectorAll('h1').length,
    mainTextLength: (main?.textContent ?? '').trim().length,
    mainHeight: Math.round(main?.getBoundingClientRect().height ?? 0),
    dialog: dr ? { top: Math.round(dr.top), left: Math.round(dr.left), right: Math.round(dr.right), bottom: Math.round(dr.bottom), insideViewport: dr.left >= 0 && dr.right <= vw + 1 && dr.top >= 0 } : null,
    tables,
  };
}

async function capture(page: import('@playwright/test').Page, id: string, vp: string, extra: Record<string, unknown> = {}) {
  mkdirSync(OUT, { recursive: true });
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: path.join(OUT, `${id}__${vp}.png`), fullPage: true });
  const metrics = await page.evaluate(measureLayout);
  writeFileSync(path.join(OUT, `${id}__${vp}.json`), JSON.stringify({ screen: id, viewport: vp, route: page.url(), ...extra, metrics }, null, 2));
}

for (const [vp, size] of Object.entries(VIEWPORTS)) {
  test.describe(vp, () => {
    test.use({ viewport: size });
    for (const s of SCREENS) {
      test(`${s.id} @ ${vp}`, async ({ page }) => {
        await installMockApi(page);
        if (s.role) await loginAs(page, s.role);
        await page.goto(s.route);
        await expect(page.getByTestId(s.testid)).toBeVisible();
        await capture(page, s.id, vp);
      });
    }
    for (const d of DIALOGS) {
      test(`${d.id} @ ${vp}`, async ({ page }) => {
        await installMockApi(page);
        await loginAs(page, d.role);
        await page.goto(d.route);
        await page.getByTestId(d.row).getByTestId(d.trigger).click();
        await expect(page.getByRole('dialog')).toBeVisible();
        await capture(page, d.id, vp);
      });
    }
    if (size.width < 768) {
      test(`navigation.menu @ ${vp}`, async ({ page }) => {
        await installMockApi(page);
        const s = SCREENS.find((x) => x.role)!;
        await loginAs(page, s.role!);
        await page.goto(s.route);
        await page.getByRole('button', { name: 'Menu' }).click();
        await expect(page.getByRole('navigation', { name: 'Primary mobile' })).toBeVisible();
        await capture(page, 'navigation.menu', vp);
      });
    }
  });
}
""" % {"vps": json.dumps(vps), "screens": json.dumps(screens, indent=2), "dialogs": json.dumps(dialogs, indent=2)}
