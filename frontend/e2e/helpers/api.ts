import type { APIRequestContext } from '@playwright/test';

export const API = process.env.E2E_API_URL ?? 'http://127.0.0.1:8000';

/**
 * The demo accounts, mirroring `backend/app/security/demo_accounts.py`.
 *
 * Signing in through `POST /v1/auth/login` rather than minting a token from a
 * persona is deliberate. The dev token endpoint takes the subject from the
 * CALLER, and every caller was passing something the seed does not contain
 * (`dev-c0000000-…-0101` here, `dev-admin_t1` in the frontend). `provision_actor`
 * upserts on `oidc_sub`, so those tokens quietly provisioned duplicate user rows
 * instead of signing in as the seeded users. Login fixes the subject at the
 * server, where it cannot drift.
 */
export const ACCOUNTS = {
  admin: { email: 'admin@example.test', password: 'demo-admin', role: 'admin', clearance: 4 },
  officer: {
    email: 'officer@example.test',
    password: 'demo-officer',
    role: 'security_officer',
    clearance: 4,
  },
  manager: {
    email: 'manager@example.test',
    password: 'demo-manager',
    role: 'dept_manager',
    clearance: 3,
  },
  employee: {
    email: 'employee@example.test',
    password: 'demo-employee',
    role: 'employee',
    clearance: 2,
  },
  viewer: { email: 'viewer@example.test', password: 'demo-viewer', role: 'viewer', clearance: 1 },
} as const;

export type AccountName = keyof typeof ACCOUNTS;

/** Sign in as a demo account and return its bearer token. */
export async function mintToken(
  request: APIRequestContext,
  account: AccountName = 'admin'
): Promise<string> {
  const { email, password } = ACCOUNTS[account];
  const res = await request.post(`${API}/v1/auth/login`, { data: { email, password } });
  if (!res.ok()) {
    throw new Error(
      `sign-in as ${account} failed (${res.status()}). Is the API running with env=dev?`
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
