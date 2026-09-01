import React from 'react';
import { render, RenderOptions, RenderResult } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider, DemoAccount, DEMO_ACCOUNTS } from './api/auth';
import { setAuthToken } from './api/client';
import { DocumentListItem } from './api/types';

export const PERSONA_ADMIN = DEMO_ACCOUNTS.find((p) => p.role === 'admin')!;
export const PERSONA_SECURITY_OFFICER = DEMO_ACCOUNTS.find((p) => p.role === 'security_officer')!;
export const PERSONA_DEPT_MANAGER = DEMO_ACCOUNTS.find((p) => p.role === 'dept_manager')!;
export const PERSONA_EMPLOYEE = DEMO_ACCOUNTS.find((p) => p.role === 'employee')!;
export const PERSONA_VIEWER = DEMO_ACCOUNTS.find((p) => p.role === 'viewer')!;

/**
 * A QueryClient with retries off. The app's real client retries twice on
 * anything that is not 401/403/404, which would turn a single mocked failure
 * into three fetch calls and make request assertions meaningless.
 */
export function makeTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

export interface RenderAppOptions extends Omit<RenderOptions, 'wrapper'> {
  persona?: DemoAccount | null;
  route?: string;
  queryClient?: QueryClient;
}

/**
 * A JWT-shaped token carrying a persona's claims.
 *
 * `AuthProvider` derives the signed-in user by DECODING the stored token, and a
 * stored token takes precedence over any injected persona. A placeholder string
 * therefore leaves `user` null, which silently closes every `<Can>` gate and
 * makes permission tests assert against an empty shell.
 *
 * The signature is deliberately junk: nothing client-side verifies it, and
 * nothing client-side ever should (invariant #33 — the API re-authorizes).
 */
export function makeDevToken(persona: DemoAccount): string {
  const b64url = (value: object): string =>
    btoa(JSON.stringify(value)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

  const header = b64url({ alg: 'HS256', typ: 'JWT' });
  const payload = b64url({
    sub: `dev-${persona.id}`,
    tenant_id: persona.tenantId,
    department_id: persona.departmentId,
    role: persona.role,
    clearance_rank: persona.clearance,
    name: persona.label,
    aud: 'docmgmt-api',
    exp: Math.floor(Date.now() / 1000) + 3600,
  });
  return `${header}.${payload}.not-a-real-signature`;
}

/**
 * Renders a component inside the providers it needs, with the dev-persona shim
 * DISABLED so `AuthProvider` never reaches for `/v1/auth/login`. The account is
 * injected directly, which keeps every test deterministic and keeps the auth
 * bootstrap out of tests that are not about auth.
 */
export function renderWithProviders(
  ui: React.ReactElement,
  { persona = PERSONA_ADMIN, route = '/', queryClient, ...options }: RenderAppOptions = {}
): RenderResult & { queryClient: QueryClient } {
  const client = queryClient ?? makeTestQueryClient();

  // Seed a token matching the requested persona. Without this the provider
  // decodes whatever happens to be in storage, so `persona` would be silently
  // ignored whenever a test had already stored a token.
  setAuthToken(persona ? makeDevToken(persona) : null);

  const Wrapper: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <QueryClientProvider client={client}>
      <AuthProvider demoLoginEnabled={false}>
        <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  );

  return { ...render(ui, { wrapper: Wrapper, ...options }), queryClient: client };
}

/** A JSON `Response` for a mocked `fetch`. */
export function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

/** An RFC 7807 problem-details error response. */
export function problemResponse(
  status: number,
  problem: Partial<{ type: string; title: string; detail: string; instance: string }> = {}
): Response {
  return new Response(
    JSON.stringify({
      type: problem.type ?? 'about:blank',
      title: problem.title ?? 'Error',
      status,
      detail: problem.detail ?? 'Something went wrong.',
      ...(problem.instance ? { instance: problem.instance } : {}),
    }),
    { status, headers: { 'Content-Type': 'application/problem+json' } }
  );
}

export function makeDocument(overrides: Partial<DocumentListItem> = {}): DocumentListItem {
  return {
    id: '11111111-1111-1111-1111-111111111111',
    filename: 'quarterly-report.pdf',
    status: 'ready',
    level: 'Internal',
    doc_type: 'Report',
    created_at: '2026-08-01T10:00:00Z',
    ...overrides,
  };
}

/** The URL of the Nth `fetch` call, as a string. */
export function fetchUrl(mock: { mock: { calls: unknown[][] } }, index = 0): string {
  const arg = mock.mock.calls[index]?.[0];
  return typeof arg === 'string' ? arg : String(arg);
}

/** The `RequestInit` of the Nth `fetch` call. */
export function fetchInit(mock: { mock: { calls: unknown[][] } }, index = 0): RequestInit {
  return (mock.mock.calls[index]?.[1] as RequestInit) ?? {};
}

/** Reads a header off a `fetch` call's init, whatever form the headers took. */
export function headerFrom(init: RequestInit, name: string): string | null {
  const headers = init.headers;
  if (!headers) return null;
  if (headers instanceof Headers) return headers.get(name);
  if (Array.isArray(headers)) {
    const hit = headers.find(([k]) => k.toLowerCase() === name.toLowerCase());
    return hit ? hit[1] : null;
  }
  const record = headers as Record<string, string>;
  const key = Object.keys(record).find((k) => k.toLowerCase() === name.toLowerCase());
  return key ? record[key] : null;
}
