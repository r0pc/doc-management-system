import { test, expect, API } from './fixtures';

test.describe('admin trains a doc-type prototype', () => {
  test('five ready documents produce a normalised prototype', async ({ request, adminToken }) => {
    const auth = { Authorization: `Bearer ${adminToken}` };
    const docs = await (
      await request.get(`${API}/v1/documents?status=ready&limit=10`, { headers: auth })
    ).json();
    test.skip(docs.items.length < 5, 'needs 5 ready documents');

    const types = await (await request.get(`${API}/v1/admin/doc-types`, { headers: auth })).json();
    const target = types[0].id;

    const res = await request.post(`${API}/v1/admin/doc-types/${target}/prototype`, {
      headers: auth,
      data: { document_ids: docs.items.slice(0, 5).map((d: { id: string }) => d.id) },
    });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.sample_count).toBe(5);
    expect(body.dimension).toBe(384);
    // The centroid is never returned to a client.
    expect(JSON.stringify(body)).not.toContain('centroid');
  });

  test('fewer than five samples is refused', async ({ request, adminToken }) => {
    const auth = { Authorization: `Bearer ${adminToken}` };
    const docs = await (
      await request.get(`${API}/v1/documents?status=ready&limit=3`, { headers: auth })
    ).json();
    const types = await (await request.get(`${API}/v1/admin/doc-types`, { headers: auth })).json();
    const res = await request.post(`${API}/v1/admin/doc-types/${types[0].id}/prototype`, {
      headers: auth,
      data: { document_ids: docs.items.map((d: { id: string }) => d.id) },
    });
    expect([400, 422]).toContain(res.status());
  });

  test('a prototype decision is never reported as calibrated ML', async ({ request, adminToken }) => {
    // #11: cosine similarity is not a probability. Prototype hits carry
    // decided_by='rules' and confidence=0.0, and the UI must not render that
    // 0.0 as "0% confident" — which is the opposite of what happened.
    const auth = { Authorization: `Bearer ${adminToken}` };
    const docs = await (
      await request.get(`${API}/v1/documents?status=ready&limit=50`, { headers: auth })
    ).json();
    for (const d of docs.items) {
      const p = await request.get(`${API}/v1/documents/${d.id}/preview`, { headers: auth });
      if (!p.ok()) continue;
      const j = (await p.json()).justification;
      if (j.decided_by === 'rules' && j.doc_type) {
        expect(j.confidence).toBe(0);
      }
      if (j.decided_by === 'ml') {
        expect(j.confidence).toBeGreaterThan(0);
      }
    }
  });
});
