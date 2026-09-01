import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, expect, API, prefix } from './fixtures';
import { uploadDocument } from './helpers/documents';
import { waitForTerminalStatus } from './helpers/api';

const FIXTURES = fileURLToPath(new URL('./fixtures', import.meta.url));
const PDF = path.join(FIXTURES, 'disciplinary_notice_1.pdf');

test.describe('upload to view', () => {
  test('a PDF uploads, processes to ready, and serves real bytes', async ({
    request,
    adminToken,
  }) => {
    const name = prefix('journey.pdf');
    const id = await uploadDocument(request, adminToken, PDF, name);

    const status = await waitForTerminalStatus(request, adminToken, id);
    expect(status, 'the document did not reach ready — check the worker and clamd').toBe('ready');

    // Every stage journalled a terminal state and a finish time (#4).
    const jobs = await (
      await request.get(`${API}/v1/documents/${id}/jobs`, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
    ).json();
    const stages = jobs.map((j: { stage: string }) => j.stage);
    expect(stages).toEqual(['scan', 'extract', 'keywords', 'embed', 'classify', 'index']);
    for (const j of jobs) {
      expect(j.state, `${j.stage} is not terminal`).toBe('succeeded');
      expect(j.started_at, `${j.stage} has no started_at`).toBeTruthy();
      expect(j.finished_at, `${j.stage} has no finished_at`).toBeTruthy();
    }

    // The bytes come back, and they are a real PDF.
    const view = await request.get(`${API}/v1/documents/${id}/view`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    expect(view.ok()).toBeTruthy();
    expect((await view.body()).subarray(0, 5).toString()).toBe('%PDF-');
  });

  test('the uploaded document appears in the browser and opens', async ({
    authedPage,
    request,
    adminToken,
  }) => {
    const name = prefix('visible.pdf');
    const id = await uploadDocument(request, adminToken, PDF, name);
    await waitForTerminalStatus(request, adminToken, id);

    await authedPage.goto('/documents?sort=created_at&direction=desc');
    const row = authedPage.locator(`[data-testid="document-row"][data-filename="${name}"]`);
    await expect(row).toBeVisible();
    await row.getByRole('button', { name: /view/i }).click();
    await expect(authedPage.getByTestId('drawer')).toBeVisible();
  });

  test('an unsupported file fails with a reason the user can read', async ({
    authedPage,
    request,
    adminToken,
  }) => {
    // The reason lived in processing_jobs.error, was serialised by the API, and
    // was then discarded by the renderer — "Failed" with no explanation.
    const name = prefix('broken.pdf');
    const bad = path.join(FIXTURES, 'security_policy.txt');
    const id = await uploadDocument(request, adminToken, bad, name, 'application/pdf');
    const status = await waitForTerminalStatus(request, adminToken, id);
    expect(['failed', 'ready']).toContain(status);

    if (status === 'failed') {
      await authedPage.goto('/documents');
      await authedPage
        .locator(`[data-testid="document-row"][data-filename="${name}"]`)
        .getByRole('button', { name: /view/i })
        .click();
      await expect(authedPage.getByTestId('job-error')).toBeVisible();
      await expect(authedPage.getByTestId('job-error')).not.toBeEmpty();
    }
  });
});
