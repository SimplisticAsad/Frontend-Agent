import { clearSession, getSession } from '../auth/session';

export type ApiErrorKind =
  | 'validation'
  | 'unauthorized'
  | 'forbidden'
  | 'not_found'
  | 'conflict'
  | 'rate_limited'
  | 'server'
  | 'network'
  | 'timeout'
  | 'unknown';

const DEFAULT_MESSAGES: Record<ApiErrorKind, string> = {
  validation: 'Some of the information provided is not valid. Please review the form and try again.',
  unauthorized: 'Your session has expired or your credentials are not valid. Please sign in again.',
  forbidden: 'You do not have permission to perform this action.',
  not_found: 'The requested item could not be found. It may have been removed.',
  conflict: 'This change conflicts with the current state of the data. Refresh and try again.',
  rate_limited: 'Too many requests. Please wait a moment and try again.',
  server: 'The server ran into a problem. Please try again in a moment.',
  network: 'Unable to reach the server. Check your connection and try again.',
  timeout: 'The request took too long. Please try again.',
  unknown: 'Something unexpected happened. Please try again.',
};

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  readonly fieldErrors: Record<string, string>;

  constructor(kind: ApiErrorKind, status?: number, serverMessage?: string, fieldErrors: Record<string, string> = {}) {
    super(DEFAULT_MESSAGES[kind]);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
    this.fieldErrors = fieldErrors;
    // Only short, single-line server messages are shown; anything else (stack traces, HTML) is replaced by a default.
    if (serverMessage && serverMessage.length <= 200 && !/\n|<|\bat\s.+\(/.test(serverMessage)) {
      this.message = serverMessage;
    }
  }
}

export function kindForStatus(status: number): ApiErrorKind {
  if (status === 400 || status === 422) return 'validation';
  if (status === 401) return 'unauthorized';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not_found';
  if (status === 409) return 'conflict';
  if (status === 429) return 'rate_limited';
  if (status >= 500) return 'server';
  return 'unknown';
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return DEFAULT_MESSAGES.unknown;
}

const BASE_URL: string = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api';
const TIMEOUT_MS = 15_000;

export interface RequestOptions {
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  path: string;
  query?: object;
  body?: unknown;
  signal?: AbortSignal;
  auth?: boolean;
}

function toFieldErrors(raw: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (raw && typeof raw === 'object') {
    for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
      const first = Array.isArray(v) ? v[0] : v;
      if (typeof first === 'string') out[k] = first;
    }
  }
  return out;
}

export async function request<T>(opts: RequestOptions): Promise<T> {
  const url = new URL(`${BASE_URL}${opts.path}`, window.location.origin);
  for (const [k, v] of Object.entries(opts.query ?? {}) as Array<[string, unknown]>) {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
  }
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  if (opts.auth !== false) {
    const token = getSession()?.token;
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  const controller = new AbortController();
  let timedOut = false;
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, TIMEOUT_MS);
  const onAbort = () => controller.abort();
  opts.signal?.addEventListener('abort', onAbort);

  let response: Response;
  try {
    response = await fetch(url.toString(), {
      method: opts.method,
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: controller.signal,
    });
  } catch (e) {
    if (opts.signal?.aborted) throw e; // cancelled by the caller (e.g. react-query)
    throw new ApiError(timedOut ? 'timeout' : 'network');
  } finally {
    window.clearTimeout(timer);
    opts.signal?.removeEventListener('abort', onAbort);
  }

  if (response.ok) {
    if (response.status === 204) return undefined as T;
    try {
      const text = await response.text();
      return (text ? JSON.parse(text) : undefined) as T;
    } catch {
      throw new ApiError('unknown', response.status);
    }
  }

  let body: { message?: unknown; errors?: unknown } = {};
  try {
    body = (await response.json()) as typeof body;
  } catch {
    /* non-JSON error body: use defaults */
  }
  const kind = kindForStatus(response.status);
  if (kind === 'unauthorized' && opts.auth !== false) {
    clearSession();
    window.dispatchEvent(new Event('auth:unauthorized'));
  }
  throw new ApiError(kind, response.status, typeof body.message === 'string' ? body.message : undefined, toFieldErrors(body.errors));
}

export function compact<T extends Record<string, unknown>>(obj: T): Partial<T> {
  return Object.fromEntries(Object.entries(obj).filter(([, v]) => v !== undefined && v !== '')) as Partial<T>;
}
