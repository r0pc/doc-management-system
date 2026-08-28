import React, { createContext, useContext, useState, useEffect } from 'react';
import { setAuthToken, getAuthToken } from './client';

export interface UserClaims {
  sub: string;
  tenant_id: string;
  department_id?: string;
  department_path?: string;
  role: 'admin' | 'security_officer' | 'dept_manager' | 'employee' | 'viewer';
  clearance_rank: number;
  email?: string;
  name?: string;
}

export interface Persona {
  id: string;
  label: string;
  role: 'admin' | 'security_officer' | 'dept_manager' | 'employee' | 'viewer';
  clearance: number;
  tenantId: string;
  tenantLabel: string;
  departmentId: string;
  departmentLabel: string;
}

/**
 * Whether the hardcoded dev-persona shim is available at all.
 *
 * `POST /v1/dev/token` is mounted by the backend ONLY when `settings.env ==
 * "dev"` (backend/app/main.py) and raises otherwise, so the persona switcher is
 * dead weight in any other deployment — and shipping a UI that mints admin
 * sessions from a button is exactly the affordance you do not want in a
 * production bundle.
 *
 * `import.meta.env.DEV` is statically replaced by Vite at build time, so in a
 * production build this is the literal `false` and every guarded branch
 * (including the persona list and the switcher) is dropped by dead-code
 * elimination. `VITE_DEV_PERSONAS=false` additionally turns it off in a dev
 * build — e.g. when pointing the dev server at a staging API. There is no value
 * of any environment variable that can turn it ON in a production build.
 */
export const DEV_PERSONAS_ENABLED: boolean =
  import.meta.env.DEV && import.meta.env.VITE_DEV_PERSONAS !== 'false';

export const DEV_PERSONAS: Persona[] = [
  {
    id: 'admin_t1',
    label: 'Alice (Security Admin)',
    role: 'admin',
    clearance: 4,
    tenantId: 'c0000000-0000-0000-0000-000000000001',
    tenantLabel: 'Acme Corp (T1)',
    departmentId: 'c0000000-0000-0000-0000-000000000011',
    departmentLabel: 'HQ (Root)',
  },
  {
    id: 'security_t1',
    label: 'Bob (Security Officer)',
    role: 'security_officer',
    clearance: 3,
    tenantId: 'c0000000-0000-0000-0000-000000000001',
    tenantLabel: 'Acme Corp (T1)',
    departmentId: 'c0000000-0000-0000-0000-000000000011',
    departmentLabel: 'HQ (Root)',
  },
  {
    id: 'employee_t1',
    label: 'Charlie (Engineer)',
    role: 'employee',
    clearance: 2,
    tenantId: 'c0000000-0000-0000-0000-000000000001',
    tenantLabel: 'Acme Corp (T1)',
    departmentId: 'c0000000-0000-0000-0000-000000000013',
    departmentLabel: 'Engineering',
  },
  {
    id: 'dept_manager_t1',
    label: 'Dana (Dept Manager)',
    role: 'dept_manager',
    clearance: 2,
    tenantId: 'c0000000-0000-0000-0000-000000000001',
    tenantLabel: 'Acme Corp (T1)',
    departmentId: 'c0000000-0000-0000-0000-000000000012',
    departmentLabel: 'HR',
  },
  {
    id: 'viewer_t1',
    label: 'Eve (Viewer)',
    role: 'viewer',
    clearance: 1,
    tenantId: 'c0000000-0000-0000-0000-000000000001',
    tenantLabel: 'Acme Corp (T1)',
    departmentId: 'c0000000-0000-0000-0000-000000000011',
    departmentLabel: 'HQ',
  },
];

function personaToClaims(persona: Persona): UserClaims {
  return {
    sub: `dev-${persona.id}`,
    tenant_id: persona.tenantId,
    department_id: persona.departmentId,
    role: persona.role,
    clearance_rank: persona.clearance,
    name: persona.label,
  };
}



/**
 * Decodes the JWT payload for DISPLAY ONLY. The signature is not checked here
 * and cannot be — the claims below drive nothing but which chrome is rendered
 * (invariant #33). Authorization is decided by the API against the verified
 * token; a user who edits this payload changes the menu, not their access.
 */
function parseJwt(token: string): UserClaims | null {
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
    };
  } catch {
    return null;
  }
}

async function createDevJwt(persona: Persona): Promise<string> {
  const response = await fetch('/v1/dev/token', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(persona),
  });

  if (!response.ok) {
    // 404 is the expected shape when the API runs with env != dev: the router
    // is not mounted at all. Treat it the same as any other failure — no token.
    throw new Error(
      response.status === 404
        ? 'The dev token endpoint is not available on this API (it exists only when the backend runs with env=dev).'
        : `Failed to mint dev token from backend (HTTP ${response.status}).`
    );
  }

  const data = await response.json();
  if (!data || typeof data.access_token !== 'string' || data.access_token === '') {
    throw new Error('Dev token endpoint returned no access_token.');
  }
  return data.access_token;
}

interface AuthContextType {
  token: string | null;
  user: UserClaims | null;
  currentPersona: Persona | null;
  /** True once the initial token acquisition has settled (either way). */
  authReady: boolean;
  /** Non-null when the session could not be established. */
  authError: string | null;
  /** True when the dev-persona switcher may be rendered at all. */
  devPersonasEnabled: boolean;
  loginWithPersona: (persona: Persona) => Promise<void>;
  setCustomToken: (token: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export interface AuthProviderProps {
  children: React.ReactNode;
  /**
   * Overrides {@link DEV_PERSONAS_ENABLED}. Tests set this to keep the provider
   * off the network; production code never passes it.
   */
  devPersonasEnabled?: boolean;
  /**
   * Persona to seed the session with when there is no stored token. Defaults to
   * the first dev persona while the shim is enabled, and to `null` otherwise —
   * a production build starts with NO user rather than a fabricated admin.
   */
  initialPersona?: Persona | null;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({
  children,
  devPersonasEnabled = DEV_PERSONAS_ENABLED,
  initialPersona,
}) => {
  const seedPersona =
    initialPersona !== undefined ? initialPersona : devPersonasEnabled ? DEV_PERSONAS[0] : null;

  const [token, setToken] = useState<string | null>(() => getAuthToken());
  const [user, setUser] = useState<UserClaims | null>(() => {
    const stored = getAuthToken();
    if (stored) return parseJwt(stored);
    return seedPersona ? personaToClaims(seedPersona) : null;
  });
  const [currentPersona, setCurrentPersona] = useState<Persona | null>(() => {
    const stored = getAuthToken();
    if (!stored) return seedPersona;
    const claims = parseJwt(stored);
    if (!claims) return seedPersona;
    return (
      DEV_PERSONAS.find((p) => p.role === claims.role && p.tenantId === claims.tenant_id) ??
      seedPersona
    );
  });
  const [authError, setAuthError] = useState<string | null>(null);
  const [authReady, setAuthReady] = useState<boolean>(() => !!getAuthToken());

  const loginWithPersona = async (persona: Persona) => {
    if (!devPersonasEnabled) {
      // Defence in depth: even if a caller reaches this, no dev token is minted
      // outside a dev build.
      setAuthError('Dev persona login is disabled in this build.');
      setAuthReady(true);
      return;
    }
    try {
      const devToken = await createDevJwt(persona);
      setAuthToken(devToken);
      setToken(devToken);
      setUser(personaToClaims(persona));
      setCurrentPersona(persona);
      setAuthError(null);
    } catch (e) {
      // FAIL CLOSED. Previously this only logged, leaving `user` populated from
      // the persona while `token` stayed null — the UI rendered a full admin
      // shell for a session that had no credentials at all, and every request
      // went out unauthenticated. Drop the identity so the UI reflects reality.
      setAuthToken(null);
      setToken(null);
      setUser(null);
      setCurrentPersona(null);
      setAuthError(e instanceof Error ? e.message : 'Failed to establish a session.');
    } finally {
      setAuthReady(true);
    }
  };

  useEffect(() => {
    if (getAuthToken()) {
      setAuthReady(true);
      return;
    }
    if (!devPersonasEnabled || !seedPersona) {
      // No stored token and no dev shim: there is nothing this build can do to
      // authenticate. Surface it instead of pretending someone is signed in.
      setUser(null);
      setCurrentPersona(null);
      setAuthReady(true);
      setAuthError(
        devPersonasEnabled ? null : 'Not signed in. This build has no dev persona shim.'
      );
      return;
    }
    // Runs once on mount; the persona shim has no reactive inputs.
    void loginWithPersona(seedPersona);
  }, []);

  const setCustomToken = (newToken: string) => {
    setAuthToken(newToken);
    setToken(newToken);
    setUser(parseJwt(newToken));
    setCurrentPersona(null);
    setAuthError(null);
    setAuthReady(true);
  };

  const logout = () => {
    setAuthToken(null);
    setToken(null);
    setUser(null);
    setCurrentPersona(null);
    setAuthReady(true);
  };

  return (
    <AuthContext.Provider
      value={{
        token,
        user,
        currentPersona,
        authReady,
        authError,
        devPersonasEnabled,
        loginWithPersona,
        setCustomToken,
        logout,
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
