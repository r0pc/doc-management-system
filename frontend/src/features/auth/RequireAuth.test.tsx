import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { RequireAuth } from './RequireAuth';
import { AuthProvider } from '../../api/auth';
import { setAuthToken } from '../../api/client';
import { makeDevToken, PERSONA_ADMIN } from '../../test-utils';

/**
 * The guard. Cosmetic like every client-side check (#33) — the API refuses an
 * unauthenticated request whatever this renders — but it is what stops the app
 * drawing a full shell for someone with no session, which is precisely what it
 * did while `AuthProvider` signed every visitor in as an administrator.
 */

/** A token whose `exp` is in the past. */
function expiredToken(): string {
  const b64url = (v: object) =>
    btoa(JSON.stringify(v)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  return [
    b64url({ alg: 'HS256', typ: 'JWT' }),
    b64url({
      sub: 'dev-admin',
      tenant_id: PERSONA_ADMIN.tenantId,
      role: 'admin',
      clearance_rank: 4,
      exp: Math.floor(Date.now() / 1000) - 60,
    }),
    'not-a-real-signature',
  ].join('.');
}

function renderGuarded(entry = '/documents') {
  return render(
    <AuthProvider demoLoginEnabled={false}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/login" element={<LoginStub />} />
          <Route
            path="/documents"
            element={
              <RequireAuth>
                <div data-testid="protected" />
              </RequireAuth>
            }
          />
        </Routes>
      </MemoryRouter>
    </AuthProvider>
  );
}

/** Stands in for the login page and exposes the `next` it was handed. */
const LoginStub: React.FC = () => (
  <div data-testid="login-stub" data-next={new URLSearchParams(window.location.search).get('next')}>
    login
  </div>
);

beforeEach(() => {
  setAuthToken(null);
});

describe('RequireAuth', () => {
  it('renders the page for a valid session', async () => {
    setAuthToken(makeDevToken(PERSONA_ADMIN));
    renderGuarded();
    expect(await screen.findByTestId('protected')).toBeInTheDocument();
  });

  it('redirects to the login page with no session', async () => {
    renderGuarded();
    expect(await screen.findByTestId('login-stub')).toBeInTheDocument();
    expect(screen.queryByTestId('protected')).not.toBeInTheDocument();
  });

  it('treats an expired token as no session', async () => {
    setAuthToken(expiredToken());
    renderGuarded();
    expect(await screen.findByTestId('login-stub')).toBeInTheDocument();
  });

  it('discards the expired token rather than leaving it to 401', async () => {
    setAuthToken(expiredToken());
    renderGuarded();
    await screen.findByTestId('login-stub');
    expect(localStorage.getItem('dms_auth_token')).toBeNull();
  });

  it('treats a malformed token as no session', async () => {
    setAuthToken('not.a.jwt');
    renderGuarded();
    expect(await screen.findByTestId('login-stub')).toBeInTheDocument();
  });
});
