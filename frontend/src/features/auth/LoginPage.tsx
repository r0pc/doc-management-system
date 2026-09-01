import React from 'react';
import { useNavigate, useLocation, Navigate } from 'react-router-dom';
import { Shield, Loader2, AlertCircle } from 'lucide-react';
import { useAuth, DEMO_ACCOUNTS, DemoAccount } from '../../api/auth';

/**
 * The application's front door.
 *
 * Before this page existed the app signed every visitor in as a clearance-4
 * Security Admin the moment it mounted. A session now starts here or not at
 * all.
 *
 * The demo credentials are printed beside the form on purpose: the endpoint
 * that accepts them is mounted only when the backend runs with `env=dev`, and
 * `users` has no password column in any environment. Production authenticates
 * through OIDC and never reaches this route.
 */

const LEVEL_STYLES: Record<string, string> = {
  restricted: 'text-[#cf222e] dark:text-[#f85149]',
  confidential: 'text-[#9a6700] dark:text-[#d29922]',
  internal: 'text-[#0969da] dark:text-[#2f81f7]',
  public: 'text-[#1a7f37] dark:text-[#3fb950]',
};

interface ApiDemoAccount {
  email: string;
  password: string;
  name: string;
  role: string;
  clearance_rank: number;
  level_name: string;
  department: string;
}

/**
 * The accounts to offer.
 *
 * The API is asked first so the page can never print a credential the server
 * has stopped accepting. The bundled list is the fallback for the one case
 * where asking fails — the API being down — because a login page that renders
 * nothing is worse than one showing a list that is almost certainly still
 * right.
 */
function useDemoAccounts(enabled: boolean): DemoAccount[] {
  const [accounts, setAccounts] = React.useState<DemoAccount[]>(DEMO_ACCOUNTS);

  React.useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    void (async () => {
      try {
        const response = await fetch('/v1/auth/demo-accounts');
        if (!response.ok) return;
        const rows: ApiDemoAccount[] = await response.json();
        if (cancelled || !Array.isArray(rows) || rows.length === 0) return;
        setAccounts(
          rows.map((row) => ({
            ...(DEMO_ACCOUNTS.find((a) => a.email === row.email) ?? DEMO_ACCOUNTS[0]),
            email: row.email,
            password: row.password,
            label: row.name,
            role: row.role as DemoAccount['role'],
            clearance: row.clearance_rank,
            levelName: row.level_name,
            departmentLabel: row.department,
          }))
        );
      } catch {
        // Offline or the endpoint is absent: keep the bundled list.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return accounts;
}

export const DEFAULT_LANDING = '/documents';

/**
 * Constrain `?next=` to a path inside this app.
 *
 * The value arrives from the URL, so a crafted `/login?next=https://evil.test`
 * would otherwise turn the post-login redirect into an open redirect — the
 * classic phishing shape, made worse here because it fires on a page whose
 * whole job is collecting credentials. Only a single-slash-rooted path is
 * accepted: `//evil.test` is protocol-relative and must be refused too.
 */
export function safeNext(raw: string | null): string {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//')) return DEFAULT_LANDING;
  // A backslash is normalised to a slash by some browsers, so `/\evil.test`
  // reads as protocol-relative as well.
  if (raw.startsWith('/\\')) return DEFAULT_LANDING;
  return raw;
}

export const LoginPage: React.FC = () => {
  const { signIn, user, authReady, demoLoginEnabled } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = React.useState('');
  const [password, setPassword] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const accounts = useDemoAccounts(demoLoginEnabled);

  // Where the guard wanted to go before it sent the user here.
  const next = safeNext(new URLSearchParams(location.search).get('next'));

  // Already signed in — including the case where a second tab signed in while
  // this one sat on the login page.
  if (authReady && user) return <Navigate to={next} replace />;

  const submit = async (withEmail: string, withPassword: string) => {
    setBusy(true);
    setError(null);
    try {
      await signIn(withEmail, withPassword);
      navigate(next, { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Sign-in failed.');
      setPassword('');
    } finally {
      setBusy(false);
    }
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!busy) void submit(email, password);
  };

  const useAccount = (account: DemoAccount) => {
    // Fill the fields as well as signing in, so it is visible WHICH credentials
    // were used rather than the session appearing from nowhere.
    setEmail(account.email);
    setPassword(account.password);
    if (!busy) void submit(account.email, account.password);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#f6f8fa] dark:bg-[#0d1117] px-4 py-10 transition-colors">
      <div className="w-full max-w-sm" data-testid="login-page">
        <div className="flex flex-col items-center mb-6">
          <div className="p-2 rounded-md bg-[#0969da] dark:bg-[#2f81f7] text-white shadow-xs mb-3">
            <Shield className="w-5 h-5" />
          </div>
          <h1 className="text-lg font-semibold text-[#1f2328] dark:text-[#e6edf3] tracking-tight">
            Secure DMS
          </h1>
          <p className="text-xs text-[#656d76] dark:text-[#848d97] mt-1">
            Sign in to continue
          </p>
        </div>

        <form
          onSubmit={onSubmit}
          data-testid="login-form"
          className="rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#161b22] p-5 shadow-xs"
        >
          {error && (
            <div
              role="alert"
              data-testid="login-error"
              className="mb-4 flex items-start gap-2 rounded-md border border-[#cf222e]/30 bg-[#ffebe9] dark:bg-[#f85149]/10 px-3 py-2 text-xs text-[#cf222e] dark:text-[#f85149]"
            >
              <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <label
            htmlFor="login-email"
            className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1.5"
          >
            Email
          </label>
          <input
            id="login-email"
            data-testid="login-email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full mb-4 px-3 py-1.5 rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] text-sm text-[#1f2328] dark:text-[#e6edf3] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0969da]"
          />

          <label
            htmlFor="login-password"
            className="block text-xs font-semibold text-[#1f2328] dark:text-[#e6edf3] mb-1.5"
          >
            Password
          </label>
          <input
            id="login-password"
            data-testid="login-password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full mb-4 px-3 py-1.5 rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#0d1117] text-sm text-[#1f2328] dark:text-[#e6edf3] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0969da]"
          />

          <button
            type="submit"
            data-testid="login-submit"
            disabled={busy}
            className="w-full flex items-center justify-center gap-2 px-3 py-1.5 rounded-md bg-[#1f883d] hover:bg-[#1a7f37] disabled:opacity-60 text-white text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0969da]"
          >
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        {demoLoginEnabled && (
          <div
            data-testid="demo-accounts"
            className="mt-4 rounded-md border border-[#d0d7de] dark:border-[#30363d] bg-white dark:bg-[#161b22] overflow-hidden"
          >
            <div className="px-3 py-2 border-b border-[#d0d7de] dark:border-[#30363d]">
              <h2 className="text-[11px] font-semibold uppercase tracking-wider text-[#656d76] dark:text-[#848d97]">
                Demo accounts
              </h2>
              <p className="text-[11px] text-[#656d76] dark:text-[#848d97] mt-0.5">
                One per role, covering every security level. Click to sign in.
              </p>
            </div>
            <ul className="divide-y divide-[#d0d7de] dark:divide-[#30363d]">
              {accounts.map((account) => (
                <li key={account.email}>
                  <button
                    type="button"
                    data-testid="demo-account"
                    data-role={account.role}
                    disabled={busy}
                    onClick={() => useAccount(account)}
                    className="w-full px-3 py-2 text-left flex items-start gap-2.5 hover:bg-[#f6f8fa] dark:hover:bg-[#21262d] disabled:opacity-60 transition-colors focus-visible:outline-none focus-visible:bg-[#eaeef2] dark:focus-visible:bg-[#30363d]"
                  >
                    <Shield
                      className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${
                        LEVEL_STYLES[account.levelName] ?? LEVEL_STYLES.internal
                      }`}
                    />
                    <span className="flex-1 min-w-0 text-xs">
                      <span className="block font-semibold text-[#1f2328] dark:text-[#e6edf3]">
                        {account.label}
                      </span>
                      <span className="block text-[11px] text-[#656d76] dark:text-[#848d97] capitalize">
                        {account.role.replace('_', ' ')} · {account.levelName} (C
                        {account.clearance}) · {account.departmentLabel}
                      </span>
                      <span className="block font-mono text-[10px] text-[#656d76] dark:text-[#848d97] truncate">
                        {account.email} / {account.password}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
};
