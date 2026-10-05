/* In-browser stand-in for the backend, driven entirely by the graph's api.json (see data.ts). */
import type { Page } from '@playwright/test';
import { API_TABLE, CREDENTIALS, MACHINES, ROLE_PERMISSIONS, SEED, USER_COLLECTION } from './data';

export type Row = Record<string, unknown>;
export type Db = Record<string, Row[]>;

export interface MockOptions {
  db?: Partial<Db>;
  /** api id -> HTTP status to answer with (0 = network failure). */
  failures?: Record<string, number>;
  /** api id -> artificial latency in ms. */
  delays?: Record<string, number>;
}
export interface MockCall {
  api: string;
  method: string;
  path: string;
  body?: Record<string, unknown>;
}
export interface MockHandle {
  db: Db;
  calls: MockCall[];
}

const unmatched = new WeakMap<Page, string[]>();
export function unmatchedCalls(page: Page): string[] {
  return unmatched.get(page) ?? [];
}

export function cloneSeed(): Db {
  return JSON.parse(JSON.stringify(SEED)) as Db;
}

function compile(path: string): RegExp {
  return new RegExp('^' + path.replace(/\{(\w+)\}/g, '(?<$1>[^/]+)') + '$');
}
const COMPILED = API_TABLE.map((a) => ({ ...a, regex: compile(a.path) }));

export async function installMockApi(page: Page, opts: MockOptions = {}): Promise<MockHandle> {
  const db: Db = cloneSeed();
  for (const [k, v] of Object.entries(opts.db ?? {})) if (v) db[k] = v;
  const calls: MockCall[] = [];
  unmatched.set(page, []);

  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname.replace(/^\/api/, '');
    const method = req.method();
    const json = (status: number, body?: unknown) =>
      route.fulfill({ status, contentType: 'application/json', body: body === undefined ? '' : JSON.stringify(body) });

    let hit: (typeof COMPILED)[number] | undefined;
    let params: Record<string, string> = {};
    for (const a of COMPILED) {
      const m = a.method === method ? a.regex.exec(path) : null;
      if (m) {
        hit = a;
        params = (m.groups ?? {}) as Record<string, string>;
        break;
      }
    }
    if (!hit) {
      unmatched.get(page)?.push(`${method} ${path}`);
      return json(501, { message: `API_CONTRACT_ERROR: no graph-defined endpoint matches ${method} ${path}` });
    }

    let body: Record<string, unknown> | undefined;
    try {
      body = req.postData() ? (JSON.parse(req.postData() as string) as Record<string, unknown>) : undefined;
    } catch {
      return json(400, { message: 'Malformed JSON' });
    }
    calls.push({ api: hit.id, method, path, body });

    const delay = opts.delays?.[hit.id];
    if (delay) await new Promise((r) => setTimeout(r, delay));
    const failure = opts.failures?.[hit.id];
    if (failure === 0) return route.abort('failed');
    if (failure) return json(failure, {}); // no message: the UI must fall back to its own wording

    let actor: Row | undefined;
    if (hit.auth) {
      const token = (req.headers()['authorization'] ?? '').replace(/^Bearer\s+/i, '');
      actor = (db[USER_COLLECTION] ?? []).find((u) => `token-${u.id}` === token);
      if (!actor) return json(401, { message: 'Not authenticated' });
      if (hit.permission && !(ROLE_PERMISSIONS[String(actor.role)] ?? []).includes(hit.permission)) {
        return json(403, { message: 'You do not have permission to perform this action' });
      }
    }
    const rows = hit.collection ? (db[hit.collection] ??= []) : [];

    switch (hit.operation) {
      case 'login': {
        const cred = CREDENTIALS.find((c) => c.email === body?.email && c.password === body?.password);
        if (!cred) return json(401, { message: 'Invalid email or password' });
        const user = (db[USER_COLLECTION] ?? []).find((u) => u.id === cred.user_id);
        return json(200, { token: `token-${cred.user_id}`, user });
      }
      case 'list': {
        let out = rows;
        for (const [k, v] of url.searchParams) out = out.filter((r) => String(r[k]) === v);
        return json(200, out);
      }
      case 'get': {
        const row = rows.find((r) => r.id === params.id);
        return row ? json(200, row) : json(404, { message: 'Not found' });
      }
      case 'create': {
        const errors: Record<string, string> = {};
        for (const f of hit.requestFields) {
          if (f.required && (f.source === 'form' || f.source === 'input') && (body?.[f.name] === undefined || body?.[f.name] === '')) errors[f.name] = `${f.name} is required`;
        }
        if (Object.keys(errors).length) return json(422, { message: 'Validation failed', errors });
        const row: Row = { id: `${hit.idPrefix}-${rows.length + 1}`, created_at: new Date().toISOString(), ...body };
        for (const f of hit.requestFields) if (f.source.startsWith('session.')) row[f.name] = actor?.id;
        for (const m of Object.values(MACHINES)) if (m.collection === hit.collection && row[m.field] === undefined) row[m.field] = m.initial;
        rows.push(row);
        return json(201, row);
      }
      case 'delete': {
        const i = rows.findIndex((r) => r.id === params.id);
        if (i < 0) return json(404, { message: 'Not found' });
        rows.splice(i, 1);
        return json(204);
      }
      case 'transition': {
        const row = rows.find((r) => r.id === params.id);
        if (!row) return json(404, { message: 'Not found' });
        const machine = MACHINES[hit.machine ?? ''];
        const to = body?.[machine.field];
        const t = machine.transitions.find((x) => x.from === row[machine.field] && x.to === to);
        if (!t) return json(409, { message: `Transition ${String(row[machine.field])} -> ${String(to)} is not allowed` });
        if (t.permission && !(ROLE_PERMISSIONS[String(actor?.role)] ?? []).includes(t.permission)) return json(403, { message: 'You do not have permission to perform this action' });
        row[machine.field] = to;
        return json(200, row);
      }
      default:
        return json(501, { message: 'API_CONTRACT_ERROR: unsupported operation' });
    }
  });
  return { db, calls };
}
