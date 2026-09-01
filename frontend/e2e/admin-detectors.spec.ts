import { test, expect, API, prefix } from './fixtures';

const SECRET = 'AKIA' + 'J'.repeat(16);

const rule = (over: Record<string, unknown> = {}) => ({
  entity_type: prefix('key').replace(/-/g, '_').toLowerCase(),
  pattern: '\\bAKIA[0-9A-Z]{16}\\b',
  context_words: ['aws', 'secret'],
  validator_kind: 'prefix_charset',
  validator_config: { prefix: 'AKIA', length: 20, charset: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789' },
  level_rank: 4,
  ...over,
});

test.describe('admin defines a sensitive-data detector', () => {
  test('preview returns offsets and never the matched secret', async ({ request, adminToken }) => {
    const res = await request.post(`${API}/v1/admin/detectors/preview`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: { ...rule(), sample_text: `the aws secret is ${SECRET} rotate it` },
    });
    expect(res.ok()).toBeTruthy();
    const raw = await res.text();
    const body = JSON.parse(raw);
    expect(body.matches.length).toBeGreaterThan(0);
    expect(body.matches[0].char_start).toBeGreaterThanOrEqual(0);
    // #12: offsets only, never the matched value.
    expect(raw).not.toContain(SECRET);
    expect(raw).not.toContain('AKIAJ');
  });

  test('a catastrophically backtracking pattern is refused', async ({ request, adminToken }) => {
    for (const evil of ['(a+)+$', '(a|a)*$', '([a-zA-Z]+)*$']) {
      const res = await request.post(`${API}/v1/admin/detectors`, {
        headers: { Authorization: `Bearer ${adminToken}` },
        data: rule({ pattern: evil }),
      });
      expect(res.status(), `${evil} was accepted`).toBe(422);
    }
  });

  test('a rule without a structural validator is refused', async ({ request, adminToken }) => {
    const { validator_kind, ...noValidator } = rule();
    const res = await request.post(`${API}/v1/admin/detectors`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: noValidator,
    });
    expect([400, 422]).toContain(res.status());
  });

  test('the form will not save without pattern, context words and validator', async ({
    authedPage,
  }) => {
    await authedPage.goto('/admin');
    await authedPage.getByRole('tab', { name: /detector/i }).click();
    await expect(authedPage.getByRole('button', { name: /save/i })).toBeDisabled();
  });
});
