"""Page fixtures (login, dashboard, list, form, details) for the MockLLMProvider."""
from __future__ import annotations

from app.domain.models.naming import camel, page_testid, plural, workflow_testid
from app.generation.symbols import (
    ApiBinding, entity_name, entity_plural, enum_type_name, field_label, list_binding_for_entity, get_binding_for_entity,
    machine_for_entity, workflow_schema_file, workflow_schema_names,
)
from app.llm.mock_fixtures.frontend_code import FrontendFixtures
from app.llm.mock_fixtures.tsgen import Imports, lower_first, q


class PageFixtures(FrontendFixtures):
    def page(self, spec: dict) -> str:
        screen = self.g.require(spec["screen_ref"])
        return getattr(self, f"_p_{screen['kind']}")(screen, spec)

    # -- shared pieces ------------------------------------------------------------------------
    def _qvar(self, b: ApiBinding) -> str:
        return f"{camel(plural(b.entity.lower()) if b.operation == 'list' else b.entity.lower())}Query"

    def _comp(self, screen: dict, kind: str, entity: str | None = None) -> dict | None:
        for cref in screen.get("components", []):
            c = self.g.require(cref)
            if c["kind"] == kind and (entity is None or c.get("entity") == entity):
                return c
        return None

    def _header_imports(self, imp: Imports, screen: dict) -> dict | None:
        hdr = self._comp(screen, "page_header")
        if hdr:
            from app.generation.symbols import component_path

            imp.add(component_path(hdr), hdr["name"])
        return hdr

    def _lookup_queries(self, screen: dict, primary_entities: set[str]) -> list[tuple[ApiBinding, str]]:
        out = []
        for ref in screen.get("data_sources", []):
            b = self.binding(ref)
            if b.operation == "list" and b.entity_ref not in primary_entities:
                out.append((b, self._qvar(b)))
        return out

    def _lookups_expr(self, entity_ref: str, queries: list[tuple[ApiBinding, str]], imp: Imports) -> tuple[str, str]:
        """Returns (useMemo declaration, 'lookups' prop usage) mapping ref-field names to id->label."""
        parts, deps = [], []
        for f in self.g.require(entity_ref)["fields"]:
            if f["type"] != "ref":
                continue
            for b, var in queries:
                if b.entity_ref == f["ref"]:
                    disp = self.display_field(b.entity_ref)
                    imp.add("src/lib/lookups.ts", "buildLookup")
                    parts.append(f"{q(f['name'])}: buildLookup({var}.data, (x) => x.{disp})")
                    deps.append(f"{var}.data")
        if not parts:
            return "", ""
        imp.add("react", "useMemo")
        decl = f"  const lookups = useMemo(\n    () => ({{ {', '.join(parts)} }}),\n    [{', '.join(dict.fromkeys(deps))}],\n  );\n"
        return decl, " lookups={lookups}"

    def _state_chain(self, primary_var: str, table_jsx: str, empty_title: str, empty_desc: str, empty_action: str, imp: Imports) -> str:
        imp.add("src/components/ui/States.tsx", "EmptyState", "ErrorState", "LoadingState")
        imp.add("src/lib/api/client.ts", "errorMessage")
        action = f"\n        action={{{empty_action}}}" if empty_action else ""
        return f"""  let content;
  if ({primary_var}.isPending) {{
    content = <LoadingState />;
  }} else if ({primary_var}.isError) {{
    content = <ErrorState message={{errorMessage({primary_var}.error)}} onRetry={{() => void {primary_var}.refetch()}} />;
  }} else if ({primary_var}.data.length === 0) {{
    content = (
      <EmptyState
        title={q(empty_title)}
        description={q(empty_desc)}{action}
      />
    );
  }} else {{
    content = {table_jsx};
  }}
"""

    def _page_name(self, spec: dict) -> str:
        return spec["page_component"]

    # -- login -------------------------------------------------------------------------------
    def _p_login(self, screen: dict, spec: dict) -> str:
        from app.generation.symbols import component_path

        wf = self.g.require(screen["actions"][0])
        form = self._comp(screen, "form")
        b = self.binding(wf["api"])
        values = workflow_schema_names(wf)[1]
        imp = Imports(spec["page_path"])
        imp.add("react-router-dom", "Navigate", "useLocation")
        imp.add("src/components/ui/Card.tsx", "Card")
        imp.add(component_path(form), form["name"])
        imp.add("src/features/auth/AuthContext.tsx", "useAuth")
        imp.add(self.hooks_file(b), b.hook)
        imp.add("src/lib/api/client.ts", "ApiError", "errorMessage")
        imp.add(workflow_schema_file(wf), values, type=True)
        imp.add("src/app/routes.ts", "routeTo")
        home = wf["success"]["navigate"]
        name = spec["page_component"]
        return f"""{imp.render()}

const EMPTY_ERRORS: Record<string, string> = {{}};

export function {name}() {{
  const {{ user, signIn }} = useAuth();
  const location = useLocation();
  const login = {b.hook}();
  const from = (location.state as {{ from?: string }} | null)?.from;

  if (user) return <Navigate to={{from ?? routeTo({q(home)})}} replace />;

  const onSubmit = (values: {values}) => login.mutate(values, {{ onSuccess: (session) => signIn(session) }});

  return (
    <div data-testid="{page_testid(screen['id'])}">
      <h1 className="mb-4 text-center text-2xl font-semibold text-text">{screen['name']}</h1>
      <Card>
        <{form['name']}
          onSubmit={{onSubmit}}
          isSubmitting={{login.isPending}}
          serverError={{login.error ? errorMessage(login.error) : null}}
          fieldErrors={{login.error instanceof ApiError ? login.error.fieldErrors : EMPTY_ERRORS}}
        />
      </Card>
    </div>
  );
}}
"""

    # -- dashboard ---------------------------------------------------------------------------
    def _p_dashboard(self, screen: dict, spec: dict) -> str:
        from app.generation.component_contracts import stats_prop
        from app.generation.symbols import component_path

        stats = self._comp(screen, "stats")
        imp = Imports(spec["page_path"])
        hdr = self._header_imports(imp, screen)
        imp.add(component_path(stats), stats["name"])
        imp.add("src/components/ui/States.tsx", "EmptyState", "ErrorState", "LoadingState")
        imp.add("src/lib/api/client.ts", "errorMessage")
        qs = []
        for e in stats.get("entities", []):
            b = list_binding_for_entity(self.bindings, e)
            imp.add(self.hooks_file(b), b.hook)
            qs.append((e, b, f"{stats_prop(e)}Query"))
        decl = "\n".join(f"  const {v} = {b.hook}();" for _, b, v in qs)
        queries = [v for _, _, v in qs]
        pending = " || ".join(f"{v}.isPending" for v in queries)
        err_cond = " || ".join(f"{v}.isError" for v in queries)
        err_src = " ?? ".join(f"{v}.error" for v in queries)
        retry = "; ".join(f"void {v}.refetch()" for v in queries)
        props = " ".join(f"{stats_prop(e)}={{{v}.data ?? []}}" for e, _, v in qs)
        all_empty = " && ".join(f"{v}.data?.length === 0" for v in queries)
        hdr_jsx = f"<{hdr['name']} title={q(screen['name'])} description={q('Overview of your work')} />" if hdr else ""
        return f"""{imp.render()}

export function {spec['page_component']}() {{
{decl}

  let content;
  if ({pending}) {{
    content = <LoadingState />;
  }} else if ({err_cond}) {{
    content = <ErrorState message={{errorMessage({err_src})}} onRetry={{() => {{ {retry}; }}}} />;
  }} else if ({all_empty}) {{
    content = <EmptyState title="Nothing here yet" description="Data will appear on this dashboard as soon as it is created." />;
  }} else {{
    content = <{stats['name']} {props} />;
  }}

  return (
    <div data-testid="{page_testid(screen['id'])}">
      {hdr_jsx}
      {{content}}
    </div>
  );
}}
"""

    # -- list --------------------------------------------------------------------------------
    def _p_list(self, screen: dict, spec: dict) -> str:
        from app.generation.symbols import component_path

        ent = screen["entity"]
        E = entity_name(ent)
        table = self._comp(screen, "table", ent)
        lb = list_binding_for_entity(self.bindings, ent)
        create_wf = next((w for w in self.g.many(screen["actions"]) if w["kind"] == "create" and (w.get("trigger") or {}).get("screen") == screen["id"]), None)
        delete_wf = next((w for w in self.g.many(screen["actions"]) if w["kind"] == "delete" and (w.get("trigger") or {}).get("screen") == screen["id"]), None)
        use_delete = bool(delete_wf and table and table.get("row_actions"))
        imp = Imports(spec["page_path"])
        hdr = self._header_imports(imp, screen)
        imp.add(component_path(table), table["name"])
        imp.add(self.hooks_file(lb), lb.hook)
        imp.add("src/hooks/usePermissions.ts", "usePermissions")
        primary = self._qvar(lb)
        lookups_q = self._lookup_queries(screen, {ent})
        for b, _ in lookups_q:
            imp.add(self.hooks_file(b), b.hook)
        lk_decl, lk_prop = self._lookups_expr(ent, lookups_q, imp)
        decls = [f"  const {primary} = {lb.hook}();"] + [f"  const {v} = {b.hook}();" for b, v in lookups_q]
        pre = "  const { can } = usePermissions();\n"
        action_jsx = "undefined"
        empty_action = ""
        modal = ""
        row_props = ""
        if create_wf:
            imp.add("src/components/ui/ButtonLink.tsx", "ButtonLink")
            imp.add("src/app/routes.ts", "routeTo")
            perm = create_wf["permission"]
            pre += f"  const canCreate = can({q(perm)});\n"
            label = (create_wf.get("trigger") or {}).get("label", create_wf["name"])
            action_jsx = f"canCreate ? (\n    <ButtonLink to={{routeTo({q(create_wf['screen'])})}} data-testid=\"{workflow_testid(create_wf['id'])}\">\n      {label}\n    </ButtonLink>\n  ) : undefined"
            empty_action = f"canCreate ? <ButtonLink to={{routeTo({q(create_wf['screen'])})}}>{label}</ButtonLink> : undefined"
        if use_delete:
            dbind = self.binding(delete_wf["api"])
            imp.add(self.hooks_file(dbind), dbind.hook)
            imp.add("react", "useState")
            imp.add("src/components/ui/Modal.tsx", "Modal")
            imp.add("src/components/ui/Button.tsx", "Button")
            imp.add("src/components/ui/Alert.tsx", "Alert")
            imp.add("src/components/Notifications.tsx", "useNotify")
            imp.add("src/lib/api/client.ts", "errorMessage")
            imp.add(self.type_file(ent), E, type=True)
            disp = self.display_field(ent)
            decls.append(f"  const remove = {dbind.hook}();")
            pre += (f"  const notify = useNotify();\n  const canDelete = can({q(delete_wf['permission'])});\n  const [pending, setPending] = useState<{E} | null>(null);\n"
                    f"  const [removeError, setRemoveError] = useState<string | null>(null);\n")
            notice = (delete_wf.get("success") or {}).get("notification", f"{E} deleted")
            row_props = " onDelete={canDelete ? (item) => { setRemoveError(null); setPending(item); } : undefined} deletingId={remove.isPending ? pending?.id : null}"
            modal = f"""      <Modal
        open={{pending !== null}}
        title="{delete_wf['name']}"
        onClose={{() => setPending(null)}}
        footer={{
          <>
            <Button variant="secondary" onClick={{() => setPending(null)}}>
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={{remove.isPending}}
              data-testid="confirm-{workflow_testid(delete_wf['id'])}"
              onClick={{() =>
                pending &&
                remove.mutate(pending.id, {{
                  onSuccess: () => {{
                    notify({q(notice)});
                    setPending(null);
                  }},
                  onError: (e) => setRemoveError(errorMessage(e)),
                }})
              }}
            >
              {(delete_wf.get('trigger') or {}).get('label', 'Delete')}
            </Button>
          </>
        }}
      >
        {{removeError && <Alert variant="danger">{{removeError}}</Alert>}}
        <p>
          Delete <strong>{{pending?.{disp}}}</strong>? This cannot be undone.
        </p>
      </Modal>
"""
        table_jsx = f"<{table['name']} items={{{primary}.data}}{lk_prop}{row_props} />"
        plural_label = entity_plural(ent)
        chain = self._state_chain(primary, table_jsx, f"No {plural_label.lower()} yet", f"{plural_label} will show up here once they are created.", empty_action, imp)
        hdr_jsx = f"<{hdr['name']} title={q(screen['name'])} description={q(plural_label + ' in your workspace')} actions={{actions}} />" if hdr else ""
        return f"""{imp.render()}

export function {spec['page_component']}() {{
{pre}{chr(10).join(decls)}
{lk_decl}
  const actions = {action_jsx};

{chain}
  return (
    <div data-testid="{page_testid(screen['id'])}">
      {hdr_jsx}
      {{content}}
{modal}    </div>
  );
}}
"""

    # -- form --------------------------------------------------------------------------------
    def _p_form(self, screen: dict, spec: dict) -> str:
        from app.generation.symbols import component_path

        wf = self.g.require(screen["actions"][0])
        form = self._comp(screen, "form")
        b = self.binding(wf["api"])
        values = workflow_schema_names(wf)[1]
        imp = Imports(spec["page_path"])
        hdr = self._header_imports(imp, screen)
        imp.add(component_path(form), form["name"])
        imp.add("react-router-dom", "useNavigate")
        imp.add("src/components/ui/Card.tsx", "Card")
        imp.add("src/components/Notifications.tsx", "useNotify")
        imp.add(self.hooks_file(b), b.hook)
        imp.add("src/lib/api/client.ts", "ApiError", "errorMessage")
        imp.add("src/app/routes.ts", "routeTo")
        imp.add(workflow_schema_file(wf), values, type=True)
        ref_fields = [f for f in wf["form_fields"] if (self.g.entity_field(wf["entity"], f) or {}).get("type") == "ref"]
        qvars, opts = [], []
        for fname in ref_fields:
            fld = self.g.entity_field(wf["entity"], fname)
            lb = list_binding_for_entity(self.bindings, fld["ref"])
            var = self._qvar(lb)
            if var not in [v for v, _ in qvars]:
                qvars.append((var, lb))
                imp.add(self.hooks_file(lb), lb.hook)
            disp = self.display_field(fld["ref"])
            imp.add("src/lib/lookups.ts", "toOptions")
            opts.append(f"{q(fname)}: toOptions({var}.data, (x) => x.{disp})")
        notice = (wf.get("success") or {}).get("notification", "Saved")
        nav = (wf.get("success") or {}).get("navigate")
        back = (wf.get("trigger") or {}).get("screen") or nav
        decl = "\n".join(f"  const {v} = {lb.hook}();" for v, lb in qvars)
        gate = ""
        if qvars:
            imp.add("src/components/ui/States.tsx", "ErrorState", "LoadingState")
            pend = " || ".join(f"{v}.isPending" for v, _ in qvars)
            errc = " || ".join(f"{v}.isError" for v, _ in qvars)
            errs = " ?? ".join(f"{v}.error" for v, _ in qvars)
            retry = "; ".join(f"void {v}.refetch()" for v, _ in qvars)
            gate = f"""  if ({pend}) {{
    return (
      <div data-testid="{page_testid(screen['id'])}">
        {self._hdr(hdr, screen)}
        <LoadingState />
      </div>
    );
  }}
  if ({errc}) {{
    return (
      <div data-testid="{page_testid(screen['id'])}">
        {self._hdr(hdr, screen)}
        <ErrorState message={{errorMessage({errs})}} onRetry={{() => {{ {retry}; }}}} />
      </div>
    );
  }}
"""
        ref_prop = f"\n          refOptions={{{{ {', '.join(opts)} }}}}" if opts else ""
        return f"""{imp.render()}

const EMPTY_ERRORS: Record<string, string> = {{}};

export function {spec['page_component']}() {{
  const navigate = useNavigate();
  const notify = useNotify();
  const mutation = {b.hook}();
{decl}

  const onSubmit = (values: {values}) =>
    mutation.mutate(values, {{
      onSuccess: () => {{
        notify({q(notice)});
        navigate(routeTo({q(nav or back)}));
      }},
    }});

{gate}
  return (
    <div data-testid="{page_testid(screen['id'])}">
      {self._hdr(hdr, screen)}
      <Card>
        <{form['name']}
          onSubmit={{onSubmit}}
          onCancel={{() => navigate(routeTo({q(back)}))}}
          isSubmitting={{mutation.isPending}}
          serverError={{mutation.error ? errorMessage(mutation.error) : null}}
          fieldErrors={{mutation.error instanceof ApiError ? mutation.error.fieldErrors : EMPTY_ERRORS}}{ref_prop}
        />
      </Card>
    </div>
  );
}}
"""

    def _hdr(self, hdr: dict | None, screen: dict) -> str:
        return f"<{hdr['name']} title={q(screen['name'])} />" if hdr else ""

    # -- details -----------------------------------------------------------------------------
    def _p_details(self, screen: dict, spec: dict) -> str:
        from app.generation.symbols import component_path

        ent = screen["entity"]
        E = entity_name(ent)
        e = lower_first(E)
        gb = get_binding_for_entity(self.bindings, ent)
        param = "id"
        imp = Imports(spec["page_path"])
        hdr = self._header_imports(imp, screen)
        imp.add("react-router-dom", "Link", "useParams")
        imp.add("src/components/ui/Card.tsx", "Card")
        imp.add("src/components/ui/States.tsx", "ErrorState", "LoadingState")
        imp.add("src/lib/api/client.ts", "errorMessage")
        imp.add("src/app/routes.ts", "routeTo")
        imp.add(self.hooks_file(gb), gb.hook)
        pvar = f"{e}Query"
        decls = [f"  const {{ {param} }} = useParams();", f"  const {pvar} = {gb.hook}({param});"]
        sm = machine_for_entity(self.g, ent)
        # related tables (components for other entities)
        sections = []
        used_entities: set[str] = set()
        for cref in screen["components"]:
            c = self.g.require(cref)
            if c["kind"] == "table" and c.get("entity") != ent:
                rent = c["entity"]
                used_entities.add(rent)
                lb = list_binding_for_entity(self.bindings, rent)
                fk = next((f["name"] for f in self.g.require(rent)["fields"] if f["type"] == "ref" and f["ref"] == ent), None)
                imp.add(self.hooks_file(lb), lb.hook)
                imp.add(component_path(c), c["name"])
                imp.add("src/components/ui/States.tsx", "EmptyState")
                var = self._qvar(lb)
                if lb.params_type and fk and any(q_["name"] == fk for q_ in lb.query_fields):
                    decls.append(f"  const {var} = {lb.hook}({{ {fk}: {param} }});")
                    items = f"{var}.data"
                else:
                    decls.append(f"  const {var} = {lb.hook}();")
                    items = f"{var}.data.filter((x) => x.{fk} === {param})" if fk else f"{var}.data"
                sections.append((c, lb, var, items))
        lookups_q = self._lookup_queries(screen, used_entities)
        # lookups for the related entity's refs also need queries already declared above (e.g. project -> not needed)
        for b, v in lookups_q:
            imp.add(self.hooks_file(b), b.hook)
            decls.append(f"  const {v} = {b.hook}();")
        # ref lookups for primary entity card + related tables
        lk_all: list[tuple[ApiBinding, str]] = list(lookups_q)
        card_dl = self._detail_fields(ent, e, lk_all, imp)
        ctrl = self._comp(screen, "status_control")
        ctrl_jsx = ""
        if ctrl:
            wf = self.g.require(ctrl["workflow"])
            ub = self.binding(wf["api"])
            imp.add(self.hooks_file(ub), ub.hook)
            imp.add(component_path(ctrl), ctrl["name"])
            imp.add("react", "useState")
            imp.add("src/components/Notifications.tsx", "useNotify")
            imp.add("src/hooks/usePermissions.ts", "usePermissions")
            imp.add("src/lib/stateMachines.ts", "allowedTransitions")
            ty = enum_type_name(ent, sm["field"])
            imp.add(self.type_file(ent), ty, type=True)
            decls.append(f"  const update = {ub.hook}();\n  const notify = useNotify();\n  const {{ can }} = usePermissions();\n  const [transitionError, setTransitionError] = useState<string | null>(null);")
            notice = (wf.get("success") or {}).get("notification", "Updated")
            ctrl_jsx = f"""
          <Card title="{wf['name']}" className="mt-6">
            <{ctrl['name']}
              {e}={{{e}}}
              allowed={{allowedTransitions({q(sm['id'])}, {e}.{sm['field']}, (p) => can(p, {e})) as {ty}[]}}
              isPending={{update.isPending}}
              error={{transitionError}}
              onTransition={{(to) => {{
                setTransitionError(null);
                update.mutate(
                  {{ id: {e}.id, input: {{ {sm['field']}: to }} }},
                  {{ onSuccess: () => notify({q(notice)}), onError: (err) => setTransitionError(errorMessage(err)) }},
                );
              }}}}
            />
          </Card>"""
        tables_jsx = ""
        lookups_for_tables = ""
        for c, lb, var, items in sections:
            rl = [(b, v) for b, v in lk_all]
            lk_t, lk_p = self._lookups_expr(c["entity"], rl, imp)
            if lk_t:
                lookups_for_tables = lk_t
            plural_l = entity_plural(c["entity"])
            tables_jsx += f"""
          <Card title="{plural_l}" className="mt-6">
            {{{var}.isPending ? (
              <LoadingState />
            ) : {var}.isError ? (
              <ErrorState message={{errorMessage({var}.error)}} onRetry={{() => void {var}.refetch()}} />
            ) : {items}.length === 0 ? (
              <EmptyState title="No {plural_l.lower()} yet" description="Nothing is linked to this {E.lower()}." />
            ) : (
              <{c['name']} items={{{items}}}{lk_p} />
            )}}
          </Card>"""
        disp = self.display_field(ent)
        back = next((s for s in self.g.screens if s["kind"] == "list" and s.get("entity") == ent), None)
        back_jsx = (f"\n          <Link to={{routeTo({q(back['id'])})}} className=\"mb-2 inline-flex min-h-[44px] items-center text-sm font-medium text-primary underline md:min-h-[24px]\">\n            Back to {entity_plural(ent).lower()}\n          </Link>" if back else "")
        hdr_jsx = f"<{hdr['name']} title={{{e}.{disp}}} description={q(screen['name'])} />" if hdr else ""
        return f"""{imp.render()}

export function {spec['page_component']}() {{
{chr(10).join(decls)}
{lookups_for_tables}
  if ({pvar}.isPending) {{
    return (
      <div data-testid="{page_testid(screen['id'])}">
        <LoadingState />
      </div>
    );
  }}
  if ({pvar}.isError) {{
    return (
      <div data-testid="{page_testid(screen['id'])}">{back_jsx}
        <ErrorState message={{errorMessage({pvar}.error)}} onRetry={{() => void {pvar}.refetch()}} />
      </div>
    );
  }}
  const {e} = {pvar}.data;

  return (
    <div data-testid="{page_testid(screen['id'])}">{back_jsx}
      {hdr_jsx}
      <Card title="Details">
{card_dl}
      </Card>{ctrl_jsx}{tables_jsx}
    </div>
  );
}}
"""

    def _detail_fields(self, ent: str, var: str, lookups: list[tuple[ApiBinding, str]], imp: Imports) -> str:
        sm = machine_for_entity(self.g, ent)
        badge = self.badge_component(ent)
        rows = []
        for f in self.g.require(ent)["fields"]:
            n, t = f["name"], f["type"]
            if n == "id" or n == self.display_field(ent):
                continue
            lab = field_label(self.g, ent, n)
            if t == "ref":
                b = next(((bb, v) for bb, v in lookups if bb.entity_ref == f["ref"]), None)
                if not b:
                    continue  # no list API available to resolve the reference: do not show raw ids
                disp = self.display_field(f["ref"])
                val = f"{{{b[1]}.data?.find((x) => x.id === {var}.{n})?.{disp} ?? '—'}}"
            elif sm and sm["field"] == n and badge:
                from app.generation.symbols import component_path

                imp.add(component_path(badge), badge["name"])
                val = f"<{badge['name']} status={{{var}.{n}}} />"
            elif t in ("date", "datetime"):
                imp.add("src/lib/format.ts", "formatDate")
                val = f"{{formatDate({var}.{n})}}"
            else:
                val = f"{{{var}.{n} || '—'}}"
            rows.append(f"        <div>\n          <dt className=\"text-sm text-textMuted\">{lab}</dt>\n          <dd className=\"mt-1 break-words text-text\">{val}</dd>\n        </div>")
        return "        <dl className=\"grid gap-4 sm:grid-cols-2\">\n" + "\n".join(rows) + "\n        </dl>"
