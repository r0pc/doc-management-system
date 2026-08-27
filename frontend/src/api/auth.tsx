import React, { createContext, useContext, useState, useEffect } from 'react';
import { setAuthToken, getAuthToken } from './client';

export interface UserClaims {
  sub: string;
  tenant_id: string;
  department_id?: string;
  department_path?: string;
  role: 'admin' | 'compliance_officer' | 'employee' | 'auditor';
  clearance_rank: number;
  email?: string;
  name?: string;
}

export interface Persona {
  id: string;
  label: string;
  role: 'admin' | 'compliance_officer' | 'employee' | 'auditor';
  clearance: number;
  tenantId: string;
  tenantLabel: string;
  departmentId: string;
  departmentLabel: string;
}

export const DEV_PERSONAS: Persona[] = [
  {
    id: 'admin_t1',
    label: 'Alice (Security Admin)',
    role: 'admin',
    clearance: 4,
    tenantId: '00000000-0000-0000-0000-000000000001',
    tenantLabel: 'Acme Corp (T1)',
    departmentId: '00000000-0000-0000-0000-000000000010',
    departmentLabel: 'HQ (Root)',
  },
  {
    id: 'compliance_t1',
    label: 'Bob (Compliance Officer)',
    role: 'compliance_officer',
    clearance: 3,
    tenantId: '00000000-0000-0000-0000-000000000001',
    tenantLabel: 'Acme Corp (T1)',
    departmentId: '00000000-0000-0000-0000-000000000010',
    departmentLabel: 'HQ (Root)',
  },
  {
    id: 'employee_t1',
    label: 'Charlie (Engineer)',
    role: 'employee',
    clearance: 2,
    tenantId: '00000000-0000-0000-0000-000000000001',
    tenantLabel: 'Acme Corp (T1)',
    departmentId: '00000000-0000-0000-0000-000000000020',
    departmentLabel: 'Engineering',
  },
  {
    id: 'auditor_t1',
    label: 'Dana (Internal Auditor)',
    role: 'auditor',
    clearance: 2,
    tenantId: '00000000-0000-0000-0000-000000000001',
    tenantLabel: 'Acme Corp (T1)',
    departmentId: '00000000-0000-0000-0000-000000000010',
    departmentLabel: 'HQ (Root)',
  },
  {
    id: 'outsider_t2',
    label: 'Eve (Tenant 2 Outsider)',
    role: 'admin',
    clearance: 4,
    tenantId: '00000000-0000-0000-0000-000000000002',
    tenantLabel: 'Beta Corp (T2)',
    departmentId: '00000000-0000-0000-0000-000000000099',
    departmentLabel: 'Beta HQ',
  },
];

// Simple JWT parser (payload only)
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

// Dev token generator shim for local preview/development
function createDevJwtShim(persona: Persona): string {
  const header = { alg: 'HS256', typ: 'JWT' };
  const payload = {
    sub: `dev-${persona.id}`,
    tenant_id: persona.tenantId,
    department_id: persona.departmentId,
    department_path: persona.departmentLabel.toLowerCase(),
    role: persona.role,
    clearance_rank: persona.clearance,
    name: persona.label,
    email: `${persona.id}@dev.local`,
    exp: Math.floor(Date.now() / 1000) + 86400 * 7,
  };

  const encodeBase64Url = (obj: any) =>
    btoa(JSON.stringify(obj))
      .replace(/=/g, '')
      .replace(/\+/g, '-')
      .replace(/\//g, '_');

  return `${encodeBase64Url(header)}.${encodeBase64Url(payload)}.devsignature`;
}

interface AuthContextType {
  token: string | null;
  user: UserClaims | null;
  currentPersona: Persona | null;
  loginWithPersona: (persona: Persona) => void;
  setCustomToken: (token: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(() => getAuthToken());
  const [user, setUser] = useState<UserClaims | null>(() => (token ? parseJwt(token) : null));
  const [currentPersona, setCurrentPersona] = useState<Persona | null>(() => {
    if (!token) return DEV_PERSONAS[0];
    const claims = parseJwt(token);
    if (!claims) return DEV_PERSONAS[0];
    return (
      DEV_PERSONAS.find(
        (p) => p.role === claims.role && p.tenantId === claims.tenant_id
      ) || DEV_PERSONAS[0]
    );
  });

  useEffect(() => {
    if (!token) {
      // Auto-bootstrap with default Admin persona for seamless local dev
      loginWithPersona(DEV_PERSONAS[0]);
    }
  }, []);

  const loginWithPersona = (persona: Persona) => {
    const devToken = createDevJwtShim(persona);
    setAuthToken(devToken);
    setToken(devToken);
    setUser(parseJwt(devToken));
    setCurrentPersona(persona);
  };

  const setCustomToken = (newToken: string) => {
    setAuthToken(newToken);
    setToken(newToken);
    setUser(parseJwt(newToken));
    setCurrentPersona(null);
  };

  const logout = () => {
    setAuthToken(null);
    setToken(null);
    setUser(null);
    setCurrentPersona(null);
  };

  return (
    <AuthContext.Provider
      value={{
        token,
        user,
        currentPersona,
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
