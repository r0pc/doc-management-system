import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { LoginPage, safeNext, DEFAULT_LANDING } from './LoginPage';
import { AuthProvider, DEMO_ACCOUNTS, SIGN_IN_FAILED } from '../../api/auth';
import { setAuthToken, getAuthToken } from '../../api/client';
import { makeDevToken, jsonResponse, PERSONA_ADMIN } from '../../test-utils';

/**
 * The login page is the application's only front door. Before it existed the
 * app minted a clearance-4 admin session on mount, so the behaviour these tests
 * pin is as much "no session appears on its own" as "credentials work".
 */

const ADMIN = DEMO_ACCOUNTS[0];

let fetchMock: ReturnType<typeof vi.fn>;

/** A successful `POST /v1/auth/login`, carrying a decodable token. */
const loginOk = () =>
  jsonResponse({
    access_token: makeDevToken(PERSONA_ADMIN),
    token_type: 'bearer',
    expires_in: 28800,
    user: { email: ADMIN.email, name: ADMIN.label, role: ADMIN.role },
  });

beforeEach(() => {
  setAuthToken(null);
  fetchMock = vi.fn((url: string) => {
    if (String(url).includes('/v1/auth/demo-accounts')) return Promise.resolve(jsonResponse([]));
    if (String(url).includes('/v1/auth/login')) return Promise.resolve(loginOk());
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderLogin(entry = '/login') {
  return render(
    <AuthProvider demoLoginEnabled>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/documents" element={<div data-testid="documents-page" />} />
          <Route path="/audit" element={<div data-testid="audit-page" />} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>
  );
}

const loginCalls = () =>
  fetchMock.mock.calls.filter((c) => String(c[0]).includes('/v1/auth/login'));

describe('LoginPage — the form', () => {
  it('renders email, password and a submit button', () => {
    renderLogin();
    expect(screen.getByTestId('login-email')).toBeInTheDocument();
    expect(screen.getByTestId('login-password')).toBeInTheDocument();
    expect(screen.getByTestId('login-submit')).toBeInTheDocument();
  });

  it('posts the typed credentials', async () => {
    renderLogin();
    await userEvent.type(screen.getByTestId('login-email'), ADMIN.email);
    await userEvent.type(screen.getByTestId('login-password'), ADMIN.password);
    await userEvent.click(screen.getByTestId('login-submit'));

    await waitFor(() => expect(loginCalls()).toHaveLength(1));
    const body = JSON.parse(String((loginCalls()[0][1] as RequestInit).body));
    expect(body).toEqual({ email: ADMIN.email, password: ADMIN.password });
  });

  it('stores the token and lands on the documents page', async () => {
    renderLogin();
    await userEvent.type(screen.getByTestId('login-email'), ADMIN.email);
    await userEvent.type(screen.getByTestId('login-password'), ADMIN.password);
    await userEvent.click(screen.getByTestId('login-submit'));

    expect(await screen.findByTestId('documents-page')).toBeInTheDocument();
    expect(getAuthToken()).toBeTruthy();
  });

  it('sends nothing until the form is submitted', () => {
    renderLogin();
    expect(loginCalls()).toHaveLength(0);
  });
});

describe('LoginPage — rejection', () => {
  beforeEach(() => {
    fetchMock.mockImplementation((url: string) => {
      if (String(url).includes('/v1/auth/demo-accounts')) return Promise.resolve(jsonResponse([]));
      if (String(url).includes('/v1/auth/login'))
        return Promise.resolve(new Response('{}', { status: 401 }));
      return Promise.resolve(jsonResponse({}));
    });
  });

  it('shows the generic failure message and stays put', async () => {
    renderLogin();
    await userEvent.type(screen.getByTestId('login-email'), ADMIN.email);
    await userEvent.type(screen.getByTestId('login-password'), 'wrong');
    await userEvent.click(screen.getByTestId('login-submit'));

    expect(await screen.findByTestId('login-error')).toHaveTextContent(SIGN_IN_FAILED);
    expect(screen.queryByTestId('documents-page')).not.toBeInTheDocument();
  });

  it('stores no token on a failed sign-in', async () => {
    renderLogin();
    await userEvent.type(screen.getByTestId('login-email'), ADMIN.email);
    await userEvent.type(screen.getByTestId('login-password'), 'wrong');
    await userEvent.click(screen.getByTestId('login-submit'));

    await screen.findByTestId('login-error');
    expect(getAuthToken()).toBeNull();
  });

  it('clears the password field so a stale value is not resubmitted', async () => {
    renderLogin();
    await userEvent.type(screen.getByTestId('login-email'), ADMIN.email);
    await userEvent.type(screen.getByTestId('login-password'), 'wrong');
    await userEvent.click(screen.getByTestId('login-submit'));

    await screen.findByTestId('login-error');
    expect((screen.getByTestId('login-password') as HTMLInputElement).value).toBe('');
    // The email survives, so the user retypes one field rather than two.
    expect((screen.getByTestId('login-email') as HTMLInputElement).value).toBe(ADMIN.email);
  });
});

describe('LoginPage — demo accounts', () => {
  it('lists one account per role', async () => {
    renderLogin();
    const rows = await screen.findAllByTestId('demo-account');
    expect(rows).toHaveLength(DEMO_ACCOUNTS.length);
    expect(rows.map((r) => r.getAttribute('data-role'))).toEqual(
      DEMO_ACCOUNTS.map((a) => a.role)
    );
  });

  it('covers all four security levels', async () => {
    renderLogin();
    await screen.findAllByTestId('demo-account');
    const levels = new Set(DEMO_ACCOUNTS.map((a) => a.clearance));
    expect(levels).toEqual(new Set([1, 2, 3, 4]));
  });

  it('signs in with that account when one is clicked', async () => {
    renderLogin();
    const rows = await screen.findAllByTestId('demo-account');
    await userEvent.click(rows[0]);

    await waitFor(() => expect(loginCalls()).toHaveLength(1));
    const body = JSON.parse(String((loginCalls()[0][1] as RequestInit).body));
    expect(body.email).toBe(DEMO_ACCOUNTS[0].email);
  });

  it('fills the visible email too, so a failure names the account that failed', async () => {
    // Asserted on the failing path deliberately: a successful click navigates
    // away, so the only moment the prefill is observable is the one where it
    // matters — the user still on the page, needing to know which account was
    // tried.
    fetchMock.mockImplementation((url: string) => {
      if (String(url).includes('/v1/auth/demo-accounts')) return Promise.resolve(jsonResponse([]));
      return Promise.resolve(new Response('{}', { status: 401 }));
    });

    renderLogin();
    const rows = await screen.findAllByTestId('demo-account');
    await userEvent.click(rows[0]);

    await screen.findByTestId('login-error');
    expect((screen.getByTestId('login-email') as HTMLInputElement).value).toBe(
      DEMO_ACCOUNTS[0].email
    );
  });

  it('prefers the API list over the bundled one', async () => {
    fetchMock.mockImplementation((url: string) => {
      if (String(url).includes('/v1/auth/demo-accounts'))
        return Promise.resolve(
          jsonResponse([
            {
              email: 'admin@example.test',
              password: 'rotated-password',
              name: 'Alice Ahmed',
              role: 'admin',
              clearance_rank: 4,
              level_name: 'restricted',
              department: 'HQ',
            },
          ])
        );
      return Promise.resolve(loginOk());
    });

    renderLogin();
    await waitFor(async () =>
      expect(await screen.findAllByTestId('demo-account')).toHaveLength(1)
    );
    await userEvent.click(screen.getAllByTestId('demo-account')[0]);

    await waitFor(() => expect(loginCalls()).toHaveLength(1));
    const body = JSON.parse(String((loginCalls()[0][1] as RequestInit).body));
    expect(body.password).toBe('rotated-password');
  });

  it('is not rendered when demo login is disabled', () => {
    render(
      <AuthProvider demoLoginEnabled={false}>
        <MemoryRouter initialEntries={['/login']}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );
    expect(screen.queryByTestId('demo-accounts')).not.toBeInTheDocument();
    // The form itself stays: an OIDC-backed build still needs a sign-in page.
    expect(screen.getByTestId('login-form')).toBeInTheDocument();
  });
});

describe('LoginPage — post-login destination', () => {
  it('returns to the page the guard interrupted', async () => {
    renderLogin('/login?next=%2Faudit');
    await userEvent.type(screen.getByTestId('login-email'), ADMIN.email);
    await userEvent.type(screen.getByTestId('login-password'), ADMIN.password);
    await userEvent.click(screen.getByTestId('login-submit'));

    expect(await screen.findByTestId('audit-page')).toBeInTheDocument();
  });

  it('redirects away immediately when already signed in', async () => {
    setAuthToken(makeDevToken(PERSONA_ADMIN));
    renderLogin();
    expect(await screen.findByTestId('documents-page')).toBeInTheDocument();
  });
});

describe('safeNext — open redirect', () => {
  it('keeps an in-app path', () => {
    expect(safeNext('/audit?q=1')).toBe('/audit?q=1');
  });

  it.each([
    ['https://evil.test/phish', 'an absolute URL'],
    ['//evil.test/phish', 'a protocol-relative URL'],
    ['/\\evil.test', 'a backslash the browser normalises'],
    ['javascript:alert(1)', 'a script URL'],
    [null, 'nothing at all'],
    ['', 'an empty value'],
  ])('refuses %s (%s)', (raw: string | null, _why: string) => {
    expect(safeNext(raw)).toBe(DEFAULT_LANDING);
  });
});
