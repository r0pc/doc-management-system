import { test, expect, API } from './fixtures';

const SORTS = ['created_at', 'filename', 'status', 'level', 'doc_type'] as const;

test.describe('list filtering', () => {
  test('selecting a status filter narrows the table to that status', async ({ authedPage }) => {
    await authedPage.goto('/documents');
    await authedPage.getByLabel(/status/i).selectOption('ready');
    await expect(authedPage.getByTestId('documents-table')).toBeVisible();
    const rows = authedPage.locator('[data-testid="document-row"]');
    const count = await rows.count();
    for (let i = 0; i < count; i++) {
      expect(await rows.nth(i).getAttribute('data-status')).toBe('ready');
    }
  });

  test('the filter reaches the server, not just the client', async ({ authedPage }) => {
    await authedPage.goto('/documents');
    const [request] = await Promise.all([
      authedPage.waitForRequest((r) => r.url().includes('status=failed')),
      authedPage.getByLabel(/status/i).selectOption('failed'),
    ]);
    expect(request.url()).toContain('status=failed');
  });
});

test.describe('list sorting', () => {
  for (const field of SORTS) {
    for (const direction of ['asc', 'desc'] as const) {
      test(`paging ${field}/${direction} returns every row exactly once`, async ({
        request,
        adminToken,
      }) => {
        const auth = { Authorization: `Bearer ${adminToken}` };
        const all = await (
          await request.get(`${API}/v1/documents?limit=200`, { headers: auth })
        ).json();
        const expected = new Set(all.items.map((i: { id: string }) => i.id));

        const seen: string[] = [];
        let cursor: string | null = null;
        for (let page = 0; page < 200; page++) {
          const url =
            `${API}/v1/documents?sort=${field}&direction=${direction}&limit=2` +
            (cursor ? `&cursor=${encodeURIComponent(cursor)}` : '');
          const body = await (await request.get(url, { headers: auth })).json();
          seen.push(...body.items.map((i: { id: string }) => i.id));
          cursor = body.next_cursor;
          if (!cursor) break;
        }

        expect(new Set(seen).size, `${field}/${direction} returned duplicates`).toBe(seen.length);
        expect(new Set(seen), `${field}/${direction} dropped or invented rows`).toEqual(expected);
      });
    }
  }

  test('a cursor cannot be replayed under a different sort', async ({ request, adminToken }) => {
    const auth = { Authorization: `Bearer ${adminToken}` };
    const first = await (
      await request.get(`${API}/v1/documents?sort=filename&direction=asc&limit=2`, {
        headers: auth,
      })
    ).json();
    if (!first.next_cursor) test.skip(true, 'not enough rows to page');
    const res = await request.get(
      `${API}/v1/documents?sort=status&direction=asc&limit=2&cursor=${encodeURIComponent(first.next_cursor)}`,
      { headers: auth }
    );
    expect(res.status()).toBe(400);
  });

  test('clicking a column header sorts the table', async ({ authedPage }) => {
    await authedPage.goto('/documents');
    const [req] = await Promise.all([
      authedPage.waitForRequest((r) => r.url().includes('sort=filename')),
      authedPage.getByRole('button', { name: /title|filename/i }).first().click(),
    ]);
    expect(req.url()).toContain('sort=filename');
  });
});
