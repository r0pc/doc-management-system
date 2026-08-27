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

async function createDevJwt(persona: Persona): Promise<string> {
  const response = await fetch('/v1/dev/token', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(persona),
  });

  if (!response.ok) {
    throw new Error('Failed to mint dev token from backend');
  }

  const data = await response.json();
  return data.access_token;
}

interface AuthContextType {
  token: string | null;
  user: UserClaims | null;
  currentPersona: Persona | null;
  loginWithPersona: (persona: Persona) => Promise<void>;
  setCustomToken: (token: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(() => getAuthToken());
  const [user, setUser] = useState<UserClaims | null>(() => {
    if (token) return parseJwt(token);
    return personaToClaims(DEV_PERSONAS[0]);
  });
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

  const loginWithPersona = async (persona: Persona) => {
    try {
      const devToken = await createDevJwt(persona);
      setAuthToken(devToken);
      setToken(devToken);
      setUser(personaToClaims(persona));
      setCurrentPersona(persona);
    } catch (e) {
      console.error('Failed to create signed dev JWT:', e);
    }
  };

  useEffect(() => {
    if (!getAuthToken()) {
      // Async generate the real HS256 signed bearer token
      loginWithPersona(DEV_PERSONAS[0]);
    }
  }, []);

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
