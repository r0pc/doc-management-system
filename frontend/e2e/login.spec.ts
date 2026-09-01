import { test, expect, API } from './fixtures';
import { ACCOUNTS } from './helpers/api';

/**
 * Sign-in, end to end against the live stack.
 *
 * The property worth the most here is the first one: an unauthenticated
 * visitor must not reach the application. Until this page existed, opening the
 * app in a browser signed you in as a clearance-4 Security Admin with no
 * action taken, and no test noticed because every test seeded its own token.
 */

const AUTH_KEY = 'dms_auth_token';

/** A page with no stored session, whatever a previous test left behind. */
async function anonymous(page: import('@playwright/test').Page) {
  await page.addInitScript((k) => window.localStorage.removeItem(k), AUTH_KEY);
  return page;
}

test.describe('the front door', () => {
  test('an unauthenticated visitor is sent to the login page', async ({ page }) => {
    await anonymous(page);
    await page.goto('/documents');

    await expect(page.getByTestId('login-page')).toBeVisible();
    await expect(page.getByTestId('documents-table')).toHaveCount(0);
  });

  test('no session appears on its own', async ({ page }) => {
    await anonymous(page);
    await page.goto('/documents');
    await expect(page.getByTestId('login-page')).toBeVisible();

    // The regression that matters: the app used to mint a token here.
    const stored = await page.evaluate((k) => window.localStorage.getItem(k), AUTH_KEY);
    expect(stored).toBeNull();
  });

  test('the deep link survives the detour through login', async ({ page }) => {
    await anonymous(page);
    await page.goto('/audit');
    await expect(page.getByTestId('login-page')).toBeVisible();

    await page.getByTestId('login-email').fill(ACCOUNTS.admin.email);
    await page.getByTestId('login-password').fill(ACCOUNTS.admin.password);
    await page.getByTestId('login-submit').click();

    await expect(page).toHaveURL(/\/audit$/);
  });
});

test.describe('signing in', () => {
  test('valid credentials open the app', async ({ page }) => {
    await anonymous(page);
    await page.goto('/login');

    await page.getByTestId('login-email').fill(ACCOUNTS.admin.email);
    await page.getByTestId('login-password').fill(ACCOUNTS.admin.password);
    await page.getByTestId('login-submit').click();

    await expect(page).toHaveURL(/\/documents$/);
    await expect(page.getByTestId('documents-table')).toBeVisible();
  });

  test('a wrong password is refused, with no session left behind', async ({ page }) => {
    await anonymous(page);
    await page.goto('/login');

    await page.getByTestId('login-email').fill(ACCOUNTS.admin.email);
    await page.getByTestId('login-password').fill('definitely-not-the-password');
    await page.getByTestId('login-submit').click();

    await expect(page.getByTestId('login-error')).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
    expect(await page.evaluate((k) => window.localStorage.getItem(k), AUTH_KEY)).toBeNull();
  });

  test('an unknown email is refused identically', async ({ page }) => {
    await anonymous(page);
    await page.goto('/login');

    await page.getByTestId('login-email').fill('nobody@example.test');
    await page.getByTestId('login-password').fill('definitely-not-the-password');
    await page.getByTestId('login-submit').click();

    await expect(page.getByTestId('login-error')).toBeVisible();
  });
});

test.describe('demo accounts', () => {
  test('one is offered per role, spanning every security level', async ({ page }) => {
    await anonymous(page);
    await page.goto('/login');

    const rows = page.getByTestId('demo-account');
    await expect(rows).toHaveCount(Object.keys(ACCOUNTS).length);

    const roles = await rows.evaluateAll((els) => els.map((e) => e.getAttribute('data-role')));
    expect(new Set(roles)).toEqual(
      new Set(Object.values(ACCOUNTS).map((a) => a.role))
    );
  });

  test('the published credentials are the ones that work', async ({ request }) => {
    // The login page prints these. A drift between the page and the verifier
    // is a demo that fails in front of an audience, so it fails here instead.
    const listed = await request.get(`${API}/v1/auth/demo-accounts`);
    expect(listed.ok()).toBeTruthy();

    for (const account of await listed.json()) {
      const signIn = await request.post(`${API}/v1/auth/login`, {
        data: { email: account.email, password: account.password },
      });
      expect(signIn.ok(), `published credential for ${account.email} does not work`).toBeTruthy();
    }
  });

  test('the bundled list agrees with the API', async ({ request }) => {
    const rows: Array<{ email: string; password: string; role: string; clearance_rank: number }> =
      await (await request.get(`${API}/v1/auth/demo-accounts`)).json();

    for (const [name, bundled] of Object.entries(ACCOUNTS)) {
      const served = rows.find((r) => r.email === bundled.email);
      expect(served, `the API serves no account for ${name}`).toBeTruthy();
      expect(served!.password).toBe(bundled.password);
      expect(served!.role).toBe(bundled.role);
      expect(served!.clearance_rank).toBe(bundled.clearance);
    }
  });

  test('clicking one signs in as that account', async ({ page }) => {
    await anonymous(page);
    await page.goto('/login');

    await page.getByTestId('demo-account').filter({ hasText: 'Erum Viewer' }).first().click();
    await expect(page).toHaveURL(/\/documents$/);

    // The signed-in identity is the one that was clicked, not the admin the app
    // used to default to.
    await expect(
      page.getByRole('button', { name: /Switch demo account\. Current: Erum Viewer, clearance 1/ })
    ).toBeVisible();

    // A viewer holds no DELETE grant, so the selection controls stay away.
    // Asserted separately from the table because a clearance-1 viewer in
    // Engineering can legitimately see NO documents — the empty state, not the
    // table, is the correct render, and demanding a table here would fail on a
    // system that is behaving exactly as designed.
    await expect(page.getByTestId('select-all')).toHaveCount(0);
  });
});

test.describe('signing out', () => {
  test('returns to the login page and clears the session', async ({ authedPage: page }) => {
    await expect(page.getByTestId('documents-table')).toBeVisible();

    await page.getByRole('button', { name: /Switch demo account/i }).click();
    await page.getByTestId('sign-out').click();

    await expect(page.getByTestId('login-page')).toBeVisible();
    expect(await page.evaluate((k) => window.localStorage.getItem(k), AUTH_KEY)).toBeNull();
  });
});

test.describe('the seeded identity', () => {
  test('signing in uses the seeded user rather than provisioning a new one', async ({
    request,
  }) => {
    // The token's subject must be the `oidc_sub` migration 0003 seeded. Anything
    // else upserts a duplicate `users` row and leaves the seeded one unused.
    const token = await (
      await request.post(`${API}/v1/auth/login`, {
        data: { email: ACCOUNTS.admin.email, password: ACCOUNTS.admin.password },
      })
    ).json();

    const claims = JSON.parse(
      Buffer.from(token.access_token.split('.')[1], 'base64').toString('utf8')
    );
    expect(claims.sub).toBe('dev-admin');
  });
});
