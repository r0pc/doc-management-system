import { test, expect, API, prefix } from './fixtures';
import { mintToken } from './helpers/api';

test.describe('scriptable content is never served inline', () => {
  test('an uploaded HTML document comes back as an attachment', async ({ request, adminToken }) => {
    // A blob is promoted during the SCAN stage, before extraction, so it keeps
    // mime_sniffed='text/html' even though the document later fails — and the
    // content routes gate on blob_key, not status. Served inline it executes,
    // and the frontend's blob: URL inherits the app's origin.
    const html = Buffer.from('<html><body><script>alert(document.domain)</script></body></html>');
    const name = prefix('xss.html');
    const auth = { Authorization: `Bearer ${adminToken}` };

    const intent = await (
      await request.post(`${API}/v1/uploads`, {
        headers: auth,
        data: { filename: name, size_bytes: html.length, content_type: 'text/html' },
      })
    ).json();
    const fields: Record<string, string> = intent.presigned_put.fields ?? {};
    if (Object.keys(fields).length > 0) {
      await request.post(intent.presigned_put.url, {
        multipart: { ...fields, file: { name, mimeType: 'text/html', buffer: html } },
      });
    } else {
      await request.put(intent.presigned_put.url, {
        headers: { 'Content-Type': 'text/html' },
        data: html,
      });
    }
    await request.post(`${API}/v1/uploads/${intent.upload_id}/complete`, {
      headers: auth,
      data: { size_bytes: html.length },
    });

    // Give the chain a moment to promote the blob, then read the headers.
    await expect(async () => {
      const res = await request.get(`${API}/v1/documents/${intent.upload_id}/view`, {
        headers: auth,
        maxRedirects: 5,
      });
      expect([200, 404, 409]).toContain(res.status());
      if (res.status() !== 200) throw new Error('not servable yet');
      const h = res.headers();
      expect(h['content-type'], 'HTML was served as a scriptable type').not.toMatch(/html|svg|xml/);
      expect(h['content-disposition']).toMatch(/attachment/);
      expect(h['x-content-type-options']).toBe('nosniff');
      expect(h['content-security-policy']).toMatch(/sandbox/);
    }).toPass({ timeout: 45_000 });
  });

  test('a legitimate PDF still renders inline with hardening headers', async ({
    request,
    adminToken,
  }) => {
    const auth = { Authorization: `Bearer ${adminToken}` };
    const docs = await (
      await request.get(`${API}/v1/documents?status=ready&limit=5`, { headers: auth })
    ).json();
    test.skip(docs.items.length === 0, 'needs a ready document');
    const res = await request.get(`${API}/v1/documents/${docs.items[0].id}/view`, {
      headers: auth,
      maxRedirects: 5,
    });
    const h = res.headers();
    expect(h['x-content-type-options']).toBe('nosniff');
    expect(h['content-security-policy']).toMatch(/sandbox/);
  });
});

test.describe('permission gating is server-side', () => {
  const ADMIN_ROUTES: [string, string][] = [
    ['GET', '/v1/admin/detectors'],
    ['POST', '/v1/admin/detectors'],
    ['POST', '/v1/admin/detectors/preview'],
  ];

  for (const [method, route] of ADMIN_ROUTES) {
    test(`a viewer is refused ${method} ${route}`, async ({ request }) => {
      const token = await mintToken(request, 'viewer');
      const res = await request.fetch(`${API}${route}`, {
        method,
        headers: { Authorization: `Bearer ${token}` },
        data: method === 'GET' ? undefined : {},
      });
      expect(res.status(), 'client-side gating is cosmetic (#33)').toBe(403);
    });
  }
});
