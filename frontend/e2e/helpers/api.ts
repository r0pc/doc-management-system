import type { APIRequestContext } from '@playwright/test';

export const API = process.env.E2E_API_URL ?? 'http://127.0.0.1:8000';

export const PERSONAS = {
  admin: {
    id: 'c0000000-0000-0000-0000-000000000101',
    label: 'Alice (Security Admin)',
    role: 'admin',
    clearance: 4,
    tenantId: 'c0000000-0000-0000-0000-000000000001',
    departmentId: 'c0000000-0000-0000-0000-000000000011',
  },
  viewer: {
    id: 'c0000000-0000-0000-0000-000000000105',
    label: 'Viewer',
    role: 'viewer',
    clearance: 1,
    tenantId: 'c0000000-0000-0000-0000-000000000001',
    departmentId: 'c0000000-0000-0000-0000-000000000011',
  },
} as const;

export async function mintToken(
  request: APIRequestContext,
  persona: keyof typeof PERSONAS = 'admin'
): Promise<string> {
  const res = await request.post(`${API}/v1/dev/token`, { data: PERSONAS[persona] });
  if (!res.ok()) {
    throw new Error(
      `dev token minting failed (${res.status()}). Is the API running with env=dev?`
    );
  }
  return (await res.json()).access_token as string;
}

/** Poll a document until it reaches a terminal state. Never sleeps blindly. */
export async function waitForTerminalStatus(
  request: APIRequestContext,
  token: string,
  documentId: string,
  timeoutMs = 60_000
): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  let last = 'unknown';
  while (Date.now() < deadline) {
    const res = await request.get(`${API}/v1/documents/${documentId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok()) {
      last = (await res.json()).status;
      if (['ready', 'failed', 'held'].includes(last)) return last;
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`document ${documentId} stuck at '${last}' after ${timeoutMs}ms`);
}
