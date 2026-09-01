import { test, expect, API } from './fixtures';

test.describe('stack preflight', () => {
  test('the API is reachable and healthy', async ({ request }) => {
    expect((await request.get(`${API}/healthz`)).ok()).toBeTruthy();
  });

  test('dev token minting works', async ({ adminToken }) => {
    expect(adminToken.length).toBeGreaterThan(20);
  });

  test('the app shell renders for an authenticated persona', async ({ authedPage }) => {
    await expect(authedPage).toHaveURL(/\/documents/);
    await expect(authedPage.getByRole('table')).toBeVisible();
  });
});
