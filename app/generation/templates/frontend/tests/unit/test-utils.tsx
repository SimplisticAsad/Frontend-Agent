import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderResult } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { NotificationProvider } from '../../src/components/Notifications';
import { AuthProvider } from '../../src/features/auth/AuthContext';
import { SESSION_STORAGE_KEY } from '../../src/lib/auth/session';
import type { AuthUser } from '../../src/types/api';

export interface RenderOptions {
  route?: string;
  user?: AuthUser | null;
}

export function renderWithProviders(ui: ReactElement, { route = '/', user = null }: RenderOptions = {}): RenderResult {
  window.localStorage.clear();
  if (user) window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ token: `token-${user.id}`, user }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <NotificationProvider>
          <MemoryRouter initialEntries={[route]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>{ui}</MemoryRouter>
        </NotificationProvider>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}
