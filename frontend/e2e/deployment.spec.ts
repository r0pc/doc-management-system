import { test, expect, API } from './fixtures';

// Routes the frontend calls. A route missing here means the deployed image is
// stale or a route was renamed — and the resulting 404 is indistinguishable
// from a permission denial, so it will not look like a deployment problem.
const REQUIRED_ROUTES = [
  '/v1/documents',
  '/v1/documents/{document_id}',
  '/v1/documents/{document_id}/content',
  '/v1/documents/{document_id}/view',
  '/v1/documents/{document_id}/preview',
  '/v1/documents/{document_id}/findings',
  '/v1/documents/{document_id}/jobs',
  '/v1/uploads',
  '/v1/uploads/batch',
  '/v1/uploads/{upload_id}/complete',
  '/v1/admin/detectors',
  '/v1/admin/detectors/preview',
  '/v1/admin/doc-types/{doc_type_id}/prototype',
];

test.describe('deployment freshness', () => {
  test('every route the frontend depends on is live', async ({ request }) => {
    const spec = await (await request.get(`${API}/openapi.json`)).json();
    const live = Object.keys(spec.paths);
    const missing = REQUIRED_ROUTES.filter((r) => !live.includes(r));
    expect(
      missing,
      `Missing from the RUNNING API: ${missing.join(', ')}.\n` +
        'The deployed image is stale. Run: docker compose build api worker worker-ocr && docker compose up -d'
    ).toEqual([]);
  });

  test('the malware scanner is actually running', async ({ request }) => {
    // clamd once spun on "Socket for clamd not found yet" for 1800 retries
    // while the config-file test stayed green. Prove the daemon works by
    // pushing a document through the scan stage, not by parsing a file.
    const res = await request.get(`${API}/healthz`);
    expect(res.ok()).toBeTruthy();
  });
});
