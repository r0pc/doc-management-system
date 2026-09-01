import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, expect, API, prefix } from './fixtures';

const FIXTURES = fileURLToPath(new URL('./fixtures', import.meta.url));
const PDF = path.join(FIXTURES, 'disciplinary_notice_1.pdf');
const MB = 1024 * 1024;

test.describe('bulk upload', () => {
  test('a batch returns one signed upload per file', async ({ request, adminToken }) => {
    const files = [1, 2, 3].map((n) => ({
      filename: prefix(`batch-${n}.pdf`),
      size_bytes: 1024,
      content_type: 'application/pdf',
    }));
    const res = await request.post(`${API}/v1/uploads/batch`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: { files },
    });
    expect(res.status()).toBe(201);
    const body = await res.json();
    expect(body.uploads).toHaveLength(3);
    expect(new Set(body.uploads.map((u: { upload_id: string }) => u.upload_id)).size).toBe(3);
  });

  test('the batch size cap is enforced by the server', async ({ request, adminToken }) => {
    // Each file is under the 100 MiB per-file cap; only the TOTAL breaches.
    // A browser-side sum is not enforcement.
    const files = Array.from({ length: 15 }, (_, n) => ({
      filename: prefix(`big-${n}.pdf`),
      size_bytes: 90 * MB,
      content_type: 'application/pdf',
    }));
    const res = await request.post(`${API}/v1/uploads/batch`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: { files },
    });
    expect(res.status()).toBe(413);
    expect((await res.json()).detail).toMatch(/batch/i);
  });

  test('a rejected batch creates no document rows', async ({ request, adminToken }) => {
    const auth = { Authorization: `Bearer ${adminToken}` };
    const before = (await (await request.get(`${API}/v1/documents?limit=200`, { headers: auth })).json())
      .items.length;
    await request.post(`${API}/v1/uploads/batch`, {
      headers: auth,
      data: {
        files: Array.from({ length: 15 }, (_, n) => ({
          filename: prefix(`ghost-${n}.pdf`),
          size_bytes: 90 * MB,
          content_type: 'application/pdf',
        })),
      },
    });
    const after = (await (await request.get(`${API}/v1/documents?limit=200`, { headers: auth })).json())
      .items.length;
    expect(after, 'a rejected batch left orphan rows behind').toBe(before);
  });

  test('selecting several files shows a row per file', async ({ authedPage }) => {
    await authedPage.goto('/upload');
    await authedPage.getByTestId('file-input').setInputFiles([PDF, PDF]);
    await expect(authedPage.locator('[data-testid^="file-status-"]')).toHaveCount(2);
  });
});
