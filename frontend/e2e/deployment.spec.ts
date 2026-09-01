import { test, expect, API } from './fixtures';
import { clientRouteShapes, pathShape } from './helpers/routes';

/**
 * Is the API you are talking to actually running the code in this checkout?
 *
 * This is the failure the hermetic suites structurally cannot see. Both the
 * pytest and vitest suites drive routes through an in-process app that always
 * has current code, so a container three commits behind is invisible to every
 * one of the ~980 tests. The symptom reaches the user as an HTTP error that
 * does not look like a deployment problem at all: a POST to a route the image
 * does not have falls through to `GET /v1/documents/{document_id}`, binds
 * `document_id="auto-classify"`, and comes back 405 Method Not Allowed.
 */

test.describe('deployment freshness', () => {
  test('every route the frontend calls is live on the running API', async ({ request }) => {
    const spec = await (await request.get(`${API}/openapi.json`)).json();
    const live = new Set(Object.keys(spec.paths).map(pathShape));

    const required = clientRouteShapes();
    // A guard that derives nothing proves nothing: if the scan returns almost
    // no routes it has silently broken, and an empty `missing` would read as
    // success. The client calls well over a dozen endpoints.
    expect(required.length, 'route extraction found almost nothing — the scanner is broken').
      toBeGreaterThan(12);

    const missing = required.filter((r) => !live.has(r));
    expect(
      missing,
      `Missing from the RUNNING API: ${missing.join(', ')}.\n` +
        'The deployed image is stale, or a route was renamed on one side only.\n' +
        'Run: docker compose build api worker worker-ocr && docker compose up -d'
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

test.describe('route shape normalisation', () => {
  // The comparison above is only as good as this reduction.
  test('an interpolated segment matches its OpenAPI parameter', () => {
    expect(pathShape('/v1/documents/${documentId}/jobs')).toBe(
      pathShape('/v1/documents/{document_id}/jobs')
    );
  });

  test('a query string is not part of the shape', () => {
    expect(pathShape('/v1/documents?limit=100')).toBe(pathShape('/v1/documents'));
  });

  test('distinct routes stay distinct', () => {
    // The bug that started this: `/v1/documents/auto-classify` is a literal
    // segment, and must NOT be flattened into the `{document_id}` shape —
    // otherwise a missing route would look present.
    expect(pathShape('/v1/documents/auto-classify')).not.toBe(
      pathShape('/v1/documents/{document_id}')
    );
  });
});
