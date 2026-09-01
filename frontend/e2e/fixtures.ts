import { test as base, expect, type Page } from '@playwright/test';
import { API, mintToken } from './helpers/api';

// Every artifact a run creates carries this prefix, so assertions can filter to
// this run's rows and teardown can target them precisely. The dev database is
// shared: asserting on totals, or deleting by anything broader than this
// prefix, would break other runs and any human using the stack.
export const RUN_ID = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
export const prefix = (name: string): string => `E2E-${RUN_ID}-${name}`;

type Fixtures = {
  adminToken: string;
  authedPage: Page;
};

export const test = base.extend<Fixtures>({
  adminToken: async ({ request }, use) => {
    await use(await mintToken(request, 'admin'));
  },
  // Seeds the session the app expects, so tests do not depend on driving the
  // persona dropdown. That widget gets its own dedicated test instead of being
  // an implicit dependency of all thirty.
  authedPage: async ({ page, request }, use) => {
    const token = await mintToken(request, 'admin');
    await page.addInitScript((t) => {
      window.localStorage.setItem('dms_auth_token', t);
    }, token);
    await page.goto('/documents');
    await use(page);
  },
});

export { expect, API };
