import React, { createContext, useContext, useState, useEffect } from 'react';
import { setAuthToken, getAuthToken } from './client';

export type Role = 'admin' | 'security_officer' | 'dept_manager' | 'employee' | 'viewer';

export interface UserClaims {
  sub: string;
  tenant_id: string;
  department_id?: string;
  department_path?: string;
  role: Role;
  clearance_rank: number;
  email?: string;
  name?: string;
}

/**
 * One demo identity, mirroring `backend/app/security/demo_accounts.py` and the
 * users seeded by migration 0003.
 *
 * `id` is the seeded `oidc_sub` suffix. It matters: the API upserts users on
 * `oidc_sub`, so a subject that does not match the seed silently provisions a
 * second row rather than signing in as the seeded user.
 */
export interface DemoAccount {
  id: string;
  email: string;
  password: string;
  label: string;
  role: Role;
  clearance: number;
  levelName: string;
  tenantId: string;
  tenantLabel: string;
  departmentId: string;
  departmentLabel: string;
}

/**
 * Whether demo sign-in is available at all.
 *
 * `POST /v1/auth/login` is mounted by the backend ONLY when `settings.env ==
 * "dev"` and 404s otherwise, so this whole surface is dead weight in any other
 * deployment — and a login form that hands out admin sessions from published
 * credentials is exactly the affordance you do not want in a production bundle.
 *
 * `import.meta.env.DEV` is statically replaced by Vite at build time, so in a
 * production build this is the literal `false` and every guarded branch is
 * dropped by dead-code elimination. `VITE_DEV_PERSONAS=false` additionally
 * turns it off in a dev build — e.g. when pointing the dev server at a staging
 * API. No environment variable can turn it ON in a production build.
 */
export const DEMO_LOGIN_ENABLED: boolean =
  import.meta.env.DEV && import.meta.env.VITE_DEV_PERSONAS !== 'false';

const TENANT_ID = 'c0000000-0000-0000-0000-000000000001';
const TENANT_LABEL = 'Demo Tenant';
const HQ = 'c0000000-0000-0000-0000-000000000011';
const HR = 'c0000000-0000-0000-0000-000000000012';
const ENGINEERING = 'c0000000-0000-0000-0000-000000000013';

/**
 * The five demo accounts, one per role, covering all four security levels.
 * Highest privilege first — the order the login page lists them in.
 *
 * Kept in step with the backend by `LoginPage` itself: it fetches
 * `/v1/auth/demo-accounts` and prefers the server's list, falling back to this
 * one only when the endpoint is unreachable. The e2e suite asserts the two
 * agree, so a drift fails a test rather than showing a password that does not
 * work.
 */
export const DEMO_ACCOUNTS: DemoAccount[] = DEMO_LOGIN_ENABLED
  ? [
      {
        id: 'admin',
        email: 'admin@example.test',
        password: 'demo-admin',
        label: 'Alice Ahmed',
        role: 'admin',
        clearance: 4,
        levelName: 'restricted',
        tenantId: TENANT_ID,
        tenantLabel: TENANT_LABEL,
        departmentId: HQ,
        departmentLabel: 'HQ',
      },
      {
        id: 'officer',
        email: 'officer@example.test',
        password: 'demo-officer',
        label: 'Bilal Officer',
        role: 'security_officer',
        clearance: 4,
        levelName: 'restricted',
        tenantId: TENANT_ID,
        tenantLabel: TENANT_LABEL,
        departmentId: HQ,
        departmentLabel: 'HQ',
      },
      {
        id: 'manager',
        email: 'manager@example.test',
        password: 'demo-manager',
        label: 'Dania Manager',
        role: 'dept_manager',
        clearance: 3,
        levelName: 'confidential',
        tenantId: TENANT_ID,
        tenantLabel: TENANT_LABEL,
        departmentId: HR,
        departmentLabel: 'HR',
      },
      {
        id: 'employee',
        email: 'employee@example.test',
        password: 'demo-employee',
        label: 'Chaudhry Employee',
        role: 'employee',
        clearance: 2,
        levelName: 'internal',
        tenantId: TENANT_ID,
        tenantLabel: TENANT_LABEL,
        departmentId: ENGINEERING,
        departmentLabel: 'Engineering',
      },
      {
        id: 'viewer',
        email: 'viewer@example.test',
        password: 'demo-viewer',
        label: 'Erum Viewer',
        role: 'viewer',
        clearance: 1,
        levelName: 'public',
        tenantId: TENANT_ID,
        tenantLabel: TENANT_LABEL,
        departmentId: ENGINEERING,
        departmentLabel: 'Engineering',
      },
    ]
  : [];

/**
 * Decodes the JWT payload for DISPLAY ONLY. The signature is not checked here
 * and cannot be — the claims below drive nothing but which chrome is rendered
 * (invariant #33). Authorization is decided by the API against the verified
 * token; a user who edits this payload changes the menu, not their access.
 */
function parseJwt(token: string): (UserClaims & { exp?: number }) | null {
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(
      window
        .atob(base64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    );
    const parsed = JSON.parse(jsonPayload);
    return {
      sub: parsed.sub,
      tenant_id: parsed.tenant_id,
      department_id: parsed.department_id,
      department_path: parsed.department_path,
      role: parsed.role,
      clearance_rank: parsed.clearance_rank ?? parsed.clearance ?? 1,
      email: parsed.email,
      name: parsed.name,
      exp: typeof parsed.exp === 'number' ? parsed.exp : undefined,
    };
  } catch {
    return null;
  }
}

/**
 * Claims from a stored token, or null if it is missing, malformed, or expired.
 *
 * The expiry check is cosmetic like every other client-side check (#33) — the
 * API rejects an expired token whatever this returns. Its job is to send the
 * user to the login page instead of drawing a full application shell over a
 * session that will 401 on its first request.
 */
function claimsFromStoredToken(token: string | null): UserClaims | null {
  if (!token) return null;
  const claims = parseJwt(token);
  if (!claims) return null;
  if (claims.exp !== undefined && claims.exp * 1000 <= Date.now()) return null;
  return claims;
}

/** The message shown for any failed sign-in; the API does not say which half was wrong. */
export const SIGN_IN_FAILED = 'Invalid email or password.';

interface LoginResponse {
  access_token?: string;
  user?: { name?: string; email?: string };
}

async function requestToken(email: string, password: string): Promise<string> {
  let response: Response;
  try {
    response = await fetch('/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
  } catch {
    throw new Error('Could not reach the API. Is the backend running?');
  }

  if (response.status === 401) throw new Error(SIGN_IN_FAILED);
  if (response.status === 404) {
    // The router is not mounted, which is the expected shape when the API runs
    // with env != dev. Say so rather than reporting bad credentials.
    throw new Error(
      'Demo sign-in is not available on this API (it exists only when the backend runs with env=dev).'
    );
  }
  if (!response.ok) throw new Error(`Sign-in failed (HTTP ${response.status}).`);

  const data: LoginResponse = await response.json();
  if (!data || typeof data.access_token !== 'string' || data.access_token === '') {
    throw new Error('The sign-in endpoint returned no access token.');
  }
  return data.access_token;
}

interface AuthContextType {
  token: string | null;
  user: UserClaims | null;
  /** The demo account matching the session, when one does. Display only. */
  currentAccount: DemoAccount | null;
  /** True once the stored session has been inspected. */
  authReady: boolean;
  /** True when the demo sign-in surface may be rendered at all. */
  demoLoginEnabled: boolean;
  /** Resolves on success; rejects with a displayable message otherwise. */
  signIn: (email: string, password: string) => Promise<void>;
  setCustomToken: (token: string) => void;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

function matchAccount(claims: UserClaims | null): DemoAccount | null {
  if (!claims) return null;
  return DEMO_ACCOUNTS.find((a) => `dev-${a.id}` === claims.sub) ?? null;
}

export interface AuthProviderProps {
  children: React.ReactNode;
  /**
   * Overrides {@link DEMO_LOGIN_ENABLED}. Tests set this to keep the provider
   * off the network; production code never passes it.
   */
  demoLoginEnabled?: boolean;
}

/**
 * Holds the session. It never establishes one on its own.
 *
 * This provider used to sign the visitor in as `DEV_PERSONAS[0]` — a
 * clearance-4 Security Admin — on mount, so opening the app in a browser was
 * itself a full-privilege grant with no action taken. Sessions now come from
 * the login page and nowhere else; with no stored token the app renders
 * `/login`, not an admin shell.
 */
export const AuthProvider: React.FC<AuthProviderProps> = ({
  children,
  demoLoginEnabled = DEMO_LOGIN_ENABLED,
}) => {
  const [token, setToken] = useState<string | null>(() => {
    const stored = getAuthToken();
    return claimsFromStoredToken(stored) ? stored : null;
  });
  const [user, setUser] = useState<UserClaims | null>(() => claimsFromStoredToken(getAuthToken()));
  const [authReady, setAuthReady] = useState(false);

  useEffect(() => {
    // An expired or malformed token is worse than none: it makes the app look
    // signed in while every request 401s. Drop it on the way past.
    const stored = getAuthToken();
    if (stored && !claimsFromStoredToken(stored)) setAuthToken(null);
    setAuthReady(true);
  }, []);

  const signIn = async (email: string, password: string) => {
    if (!demoLoginEnabled) {
      // Defence in depth behind the build-time gate: no token is minted here
      // outside a dev build even if a caller reaches this.
      throw new Error('Demo sign-in is disabled in this build.');
    }
    const issued = await requestToken(email, password);
    setAuthToken(issued);
    setToken(issued);
    setUser(parseJwt(issued));
  };

  const setCustomToken = (newToken: string) => {
    setAuthToken(newToken);
    setToken(newToken);
    setUser(parseJwt(newToken));
    setAuthReady(true);
  };

  const signOut = () => {
    setAuthToken(null);
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{
        token,
        user,
        currentAccount: matchAccount(user),
        authReady,
        demoLoginEnabled,
        signIn,
        setCustomToken,
        signOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
  return ctx;
};
