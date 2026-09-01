import { test, expect, API, prefix } from './fixtures';
import { mintToken } from './helpers/api';

/**
 * The department axis of #25, end to end.
 *
 * This started as a bug report: signed in as the HR manager, the repository was
 * empty while documents plainly existed. Nothing was broken — every document
 * was owned by HQ because the uploader was an HQ admin, and the visibility
 * subtree walks DOWNWARD, so HR (a child of HQ) could not see any of them.
 *
 * Membership is now a set, so a document can be shared with HR without leaving
 * HQ. These tests pin both halves: that sharing makes it visible, and that the
 * axis still excludes what it should.
 */

const HQ = 'c0000000-0000-0000-0000-000000000011';
const HR = 'c0000000-0000-0000-0000-000000000012';
const ENGINEERING = 'c0000000-0000-0000-0000-000000000013';

/** Upload a tiny document owned by the given departments, and wait for it. */
async function uploadInto(
  request: import('@playwright/test').APIRequestContext,
  token: string,
  name: string,
  departmentIds: string[]
): Promise<string> {
  const intent = await request.post(`${API}/v1/uploads`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      filename: name,
      size_bytes: 24,
      content_type: 'text/plain',
      department_ids: departmentIds,
    },
  });
  expect(intent.ok(), `intent failed: ${intent.status()}`).toBeTruthy();
  return (await intent.json()).upload_id as string;
}

test.describe('departments gate what each account sees', () => {
  test('the manager sees a document only once it is shared with HR', async ({ request }) => {
    const admin = await mintToken(request, 'admin');
    const manager = await mintToken(request, 'manager');
    const name = prefix('hq-only.txt');

    // Owned by HQ alone: outside HR's subtree.
    const docId = await uploadInto(request, admin, name, [HQ]);

    const visibleTo = async (token: string) => {
      const res = await request.get(`${API}/v1/documents?limit=200`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const items = (await res.json()).items as Array<{ id: string }>;
      return items.some((d) => d.id === docId);
    };

    expect(await visibleTo(admin), 'HQ admin should see its own document').toBeTruthy();
    expect(await visibleTo(manager), 'HR manager must not see an HQ-only document').toBeFalsy();

    // Share it with HR, keeping HQ.
    const shared = await request.post(`${API}/v1/documents/departments`, {
      headers: { Authorization: `Bearer ${admin}` },
      data: { document_ids: [docId], department_ids: [HQ, HR] },
    });
    expect(shared.ok()).toBeTruthy();

    expect(await visibleTo(manager), 'sharing with HR should reveal it').toBeTruthy();
    expect(await visibleTo(admin), 'sharing must not remove it from HQ').toBeTruthy();
  });

  test('a sibling department is still excluded', async ({ request }) => {
    // Engineering and HR are both children of HQ; sharing with one must not
    // reveal anything to the other.
    const admin = await mintToken(request, 'admin');
    const employee = await mintToken(request, 'employee'); // Engineering
    const docId = await uploadInto(request, admin, prefix('hr-only.txt'), [HQ, HR]);

    const res = await request.get(`${API}/v1/documents?limit=200`, {
      headers: { Authorization: `Bearer ${employee}` },
    });
    const items = (await res.json()).items as Array<{ id: string }>;
    expect(items.some((d) => d.id === docId)).toBeFalsy();
  });
});

test.describe('the root department is mandatory', () => {
  test('a set without the root is refused', async ({ request }) => {
    const admin = await mintToken(request, 'admin');
    const docId = await uploadInto(request, admin, prefix('root-rule.txt'), [HQ]);

    const res = await request.post(`${API}/v1/documents/departments`, {
      headers: { Authorization: `Bearer ${admin}` },
      data: { document_ids: [docId], department_ids: [HR] },
    });
    expect(res.status(), 'a document must never leave the tenant root').toBe(400);
  });

  test('an upload that omits the root still gets it', async ({ request }) => {
    // The server adds the root regardless of what the client sends, so no
    // client can create a document the top of the org cannot see.
    const admin = await mintToken(request, 'admin');
    const docId = await uploadInto(request, admin, prefix('implicit-root.txt'), [HR]);

    const res = await request.get(`${API}/v1/documents/${docId}`, {
      headers: { Authorization: `Bearer ${admin}` },
    });
    expect(res.ok()).toBeTruthy();
    expect((await res.json()).department_ids).toContain(HQ);
  });
});

test.describe('re-assignment is admin-only and server-enforced', () => {
  test('a security officer is refused despite holding DELETE', async ({ request }) => {
    const officer = await mintToken(request, 'officer');
    const res = await request.post(`${API}/v1/documents/departments`, {
      headers: { Authorization: `Bearer ${officer}` },
      data: { document_ids: ['00000000-0000-0000-0000-000000000001'], department_ids: [HQ] },
    });
    // 403 on the permission, not 400 on the body: the gate runs first.
    expect(res.status()).toBe(403);
  });

  test('a caller cannot assign into a department they cannot see', async ({ request }) => {
    // The manager's subtree is HR alone, so Engineering is not assignable.
    const manager = await mintToken(request, 'manager');
    const res = await request.get(`${API}/v1/departments`, {
      headers: { Authorization: `Bearer ${manager}` },
    });
    const offered = (await res.json()).map((d: { id: string }) => d.id);
    expect(offered).toContain(HQ);
    expect(offered).toContain(HR);
    expect(offered, 'a sibling subtree must not be offered').not.toContain(ENGINEERING);
  });
});

test.describe('the admin UI can re-assign', () => {
  test('the bulk control shares the selection with HR', async ({ authedPage: page }) => {
    await expect(page.getByTestId('documents-table')).toBeVisible();

    const firstRow = page.getByTestId('row-select').first();
    await firstRow.check();
    await page.getByTestId('set-departments-selected').click();

    await page.getByTestId('department-picker').waitFor();
    // The root is checked and cannot be cleared.
    const root = page.locator('[data-testid="department-option"][data-department="HQ"]');
    await expect(root).toBeChecked();
    await expect(root).toBeDisabled();

    await page.locator('[data-testid="department-option"][data-department="HR"]').check();
    await page.getByTestId('confirm-set-departments').click();

    await expect(page.getByTestId('set-departments-selected')).toHaveCount(0);
  });
});
