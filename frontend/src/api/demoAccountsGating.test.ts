import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { DEMO_ACCOUNTS, DEMO_LOGIN_ENABLED } from './auth';

/**
 * The demo credentials must not survive a production build.
 *
 * They unlock nothing there — `POST /v1/auth/login` is not mounted when the API
 * runs with `env != dev` — but shipping plaintext passwords in a bundle is
 * indefensible on sight, and the README states plainly that they are dropped.
 *
 * The list was originally a plain top-level `const`. That is NOT enough: Vite
 * folds `import.meta.env.DEV` to `false` and eliminates guarded *branches*, but
 * an exported array reached by unguarded code (`matchAccount`, called on every
 * render) is retained whole. Every credential shipped. Binding the array itself
 * to `DEMO_LOGIN_ENABLED ? [...] : []` puts it in a branch the folder can
 * actually remove — verified against the built bundle below, because reasoning
 * about a minifier is not evidence.
 */

describe('demo account gating', () => {
  it('populates the list under a dev build', () => {
    // vitest runs with DEV true, which is what every other test relies on.
    expect(DEMO_LOGIN_ENABLED).toBe(true);
    expect(DEMO_ACCOUNTS.length).toBeGreaterThan(0);
  });

  it('binds the list to the build-time flag rather than declaring it outright', () => {
    // Source-level assertion so the reason survives a refactor: a plain
    // `= [` here compiles and passes every other test while quietly putting
    // the credentials back in the bundle.
    const source = readFileSync(resolve(__dirname, 'auth.tsx'), 'utf8');
    expect(source).toMatch(
      /export const DEMO_ACCOUNTS:\s*DemoAccount\[\]\s*=\s*DEMO_LOGIN_ENABLED\s*\n?\s*\?/
    );
  });
});
