import { expect, test as base, type Page } from '@playwright/test';
import { SESSION_KEY, SEED, USER_COLLECTION } from './data';
import { unmatchedCalls } from './mockApi';

export { expect };

export async function loginAs(page: Page, role: string): Promise<void> {
  const user = (SEED[USER_COLLECTION] ?? []).find((u) => u.id === `user-${role}`);
  if (!user) throw new Error(`No seeded user for role ${role}`);
  await page.addInitScript(
    ([key, session]) => window.localStorage.setItem(key as string, JSON.stringify(session)),
    [SESSION_KEY, { token: `token-${user.id}`, user }] as const,
  );
}

/* Every test fails when the app throws an uncaught error (RUNTIME_ERROR) or calls an endpoint the graph does not define (API_CONTRACT_ERROR). */
export const test = base.extend<{ diagnostics: void }>({
  diagnostics: [
    async ({ page }, use) => {
      const pageErrors: string[] = [];
      page.on('pageerror', (e) => pageErrors.push(e.message));
      await use();
      expect(pageErrors, 'RUNTIME_ERROR: uncaught errors in the page').toEqual([]);
      expect(unmatchedCalls(page), 'API_CONTRACT_ERROR: requests to endpoints missing from api.json').toEqual([]);
    },
    { auto: true },
  ],
});
